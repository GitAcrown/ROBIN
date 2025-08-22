import logging
import sqlite3
import time
import hashlib
import string
from contextlib import closing
from pathlib import Path
from datetime import datetime
from typing import Iterable, Callable, Union, Optional, Any
import functools

import discord
from discord.ext import commands

logger = logging.getLogger('Cooldowns')

DB_PATH = Path('common/global/')

# Exceptions ================================================

class CooldownError(Exception):
    """Exception levée pour les erreurs de cooldown."""
    pass

class CooldownActiveError(CooldownError):
    """Exception levée quand un cooldown est encore actif."""
    def __init__(self, message: str, remaining_time: float):
        super().__init__(message)
        self.remaining_time = remaining_time

class CooldownNotFoundError(CooldownError):
    """Exception levée quand un cooldown n'existe pas."""
    pass

# Classes ================================================

class CooldownManager:
    """Gestionnaire centralisé des cooldowns avec système de buckets."""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.db_path = DB_PATH / 'cooldowns.db'
        DB_PATH.mkdir(parents=True, exist_ok=True)
        
        self.conn = self._connect()
        self._initialize()
        self._initialized = True
        
        # Cache des buckets
        self._buckets: dict[str, 'CooldownBucket'] = {}

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
        
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _initialize(self):
        with closing(self.conn.cursor()) as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cooldowns (
                    bucket_key TEXT NOT NULL,
                    cooldown_name TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    metadata TEXT,
                    PRIMARY KEY (bucket_key, cooldown_name)
                )
            ''')
            # Index pour améliorer les performances
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_expires_at 
                ON cooldowns (expires_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_bucket_key 
                ON cooldowns (bucket_key)
            ''')
            self.conn.commit()
    
    def _generate_bucket_key(self, entity: Any) -> str:
        """Génère une clé unique pour un bucket d'entité."""
        if isinstance(entity, (discord.User, discord.Member)):
            return f"user_{entity.id}"
        elif isinstance(entity, discord.Guild):
            return f"guild_{entity.id}"
        elif isinstance(entity, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            return f"channel_{entity.id}"
        elif isinstance(entity, discord.Role):
            return f"role_{entity.id}"
        elif isinstance(entity, discord.Thread):
            return f"thread_{entity.id}"
        elif hasattr(entity, 'id'):
            return f"generic_{entity.id}"
        elif isinstance(entity, (int, str)):
            return f"custom_{entity}"
        else:
            raise ValueError(f"Type d'entité non supporté: {type(entity)}")
    
    def get(self, entity: Any) -> 'CooldownBucket':
        """Retourne le bucket de cooldowns pour une entité."""
        bucket_key = self._generate_bucket_key(entity)
        
        if bucket_key not in self._buckets:
            self._buckets[bucket_key] = CooldownBucket(bucket_key, self, entity)
            
        return self._buckets[bucket_key]
    
    def cleanup_expired(self) -> int:
        """Nettoie tous les cooldowns expirés."""
        current_time = int(time.time())
        with closing(self.conn.cursor()) as cursor:
            cursor.execute('DELETE FROM cooldowns WHERE expires_at <= ?', (current_time,))
            deleted_count = cursor.rowcount
            self.conn.commit()
        logger.debug(f"Nettoyé {deleted_count} cooldowns expirés")
        return deleted_count
    
    def get_all_active_buckets(self) -> list[str]:
        """Retourne toutes les clés de buckets ayant des cooldowns actifs."""
        current_time = int(time.time())
        with closing(self.conn.cursor()) as cursor:
            cursor.execute('SELECT DISTINCT bucket_key FROM cooldowns WHERE expires_at > ?', (current_time,))
            return [row['bucket_key'] for row in cursor.fetchall()]
    
    def get_entities_with_cooldown(self, cooldown_name: str) -> list[dict]:
        """
        Retourne toutes les entités ayant un cooldown spécifique actif.
        
        Args:
            cooldown_name: Nom du cooldown à rechercher
            
        Returns:
            list[dict]: Liste de dictionnaires contenant les informations des entités
                       Format: {'bucket_key': str, 'entity_type': str, 'entity_id': str, 'cooldown': Cooldown}
        """
        current_time = int(time.time())
        entities = []
        
        with closing(self.conn.cursor()) as cursor:
            cursor.execute(
                'SELECT * FROM cooldowns WHERE cooldown_name = ? AND expires_at > ? ORDER BY expires_at ASC',
                (cooldown_name, current_time)
            )
            rows = cursor.fetchall()
            
            for row in rows:
                cooldown = Cooldown.from_row(row)
                bucket_key = row['bucket_key']
                
                # Parse le bucket_key pour extraire le type et l'ID
                if '_' in bucket_key:
                    entity_type, entity_id = bucket_key.split('_', 1)
                else:
                    entity_type = 'unknown'
                    entity_id = bucket_key
                
                entities.append({
                    'bucket_key': bucket_key,
                    'entity_type': entity_type,
                    'entity_id': entity_id,
                    'cooldown': cooldown
                })
        
        return entities
    
    def get_cooldown_statistics(self, cooldown_name: str) -> dict:
        """
        Retourne des statistiques sur un cooldown spécifique.
        
        Args:
            cooldown_name: Nom du cooldown à analyser
            
        Returns:
            dict: Statistiques du cooldown
        """
        current_time = int(time.time())
        
        with closing(self.conn.cursor()) as cursor:
            # Cooldowns actifs
            cursor.execute(
                'SELECT COUNT(*) as active_count FROM cooldowns WHERE cooldown_name = ? AND expires_at > ?',
                (cooldown_name, current_time)
            )
            active_count = cursor.fetchone()['active_count']
            
            # Cooldowns expirés (historique)
            cursor.execute(
                'SELECT COUNT(*) as expired_count FROM cooldowns WHERE cooldown_name = ? AND expires_at <= ?',
                (cooldown_name, current_time)
            )
            expired_count = cursor.fetchone()['expired_count']
            
            # Types d'entités avec ce cooldown
            cursor.execute(
                'SELECT DISTINCT bucket_key FROM cooldowns WHERE cooldown_name = ? AND expires_at > ?',
                (cooldown_name, current_time)
            )
            bucket_keys = [row['bucket_key'] for row in cursor.fetchall()]
            
            entity_types = {}
            for key in bucket_keys:
                if '_' in key:
                    entity_type = key.split('_', 1)[0]
                    entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
                else:
                    entity_types['unknown'] = entity_types.get('unknown', 0) + 1
        
        return {
            'cooldown_name': cooldown_name,
            'active_count': active_count,
            'expired_count': expired_count,
            'total_count': active_count + expired_count,
            'entity_types': entity_types
        }


class CooldownBucket:
    """Bucket de cooldowns pour une entité spécifique."""
    
    def __init__(self, bucket_key: str, manager: CooldownManager, entity: Any = None):
        self.bucket_key = bucket_key
        self.manager = manager
        self.entity = entity  # Référence optionnelle vers l'entité
    
    def __repr__(self):
        return f"CooldownBucket(key='{self.bucket_key}')"
    
    def set(self, cooldown_name: str, duration: Union[int, float], metadata: str = None) -> 'Cooldown':
        """Définit un cooldown dans ce bucket."""
        if duration <= 0:
            raise ValueError("La durée du cooldown doit être positive")
        
        current_time = int(time.time())
        expires_at = current_time + int(duration)
        
        cooldown = Cooldown(
            bucket_key=self.bucket_key,
            cooldown_name=cooldown_name,
            expires_at=expires_at,
            created_at=current_time,
            metadata=metadata
        )
        
        cooldown.save(self.manager)
        logger.debug(f"Cooldown '{cooldown_name}' défini pour bucket '{self.bucket_key}' (expire dans {duration}s)")
        return cooldown
    
    def get(self, cooldown_name: str) -> Optional['Cooldown']:
        """Récupère un cooldown spécifique de ce bucket."""
        with closing(self.manager.conn.cursor()) as cursor:
            cursor.execute(
                'SELECT * FROM cooldowns WHERE bucket_key = ? AND cooldown_name = ?',
                (self.bucket_key, cooldown_name)
            )
            row = cursor.fetchone()
            
            if row:
                cooldown = Cooldown.from_row(row)
                if cooldown.is_expired():
                    # Supprime automatiquement le cooldown expiré
                    self.remove(cooldown_name)
                    return None
                return cooldown
            return None
    
    def has(self, cooldown_name: str) -> bool:
        """Vérifie si un cooldown est actif dans ce bucket."""
        cooldown = self.get(cooldown_name)
        return cooldown is not None and not cooldown.is_expired()
    
    def remaining(self, cooldown_name: str) -> float:
        """Retourne le temps restant d'un cooldown (0 si expiré ou inexistant)."""
        cooldown = self.get(cooldown_name)
        if cooldown and not cooldown.is_expired():
            return cooldown.remaining_time()
        return 0.0
    
    def check(self, cooldown_name: str, raise_error: bool = True) -> bool:
        """Vérifie un cooldown et lève une exception si actif (optionnel)."""
        remaining = self.remaining(cooldown_name)
        
        if remaining > 0:
            if raise_error:
                raise CooldownActiveError(
                    f"Cooldown '{cooldown_name}' actif pour '{self.bucket_key}'",
                    remaining
                )
            return False
        return True
    
    def update_expiration(self, cooldown_name: str, new_duration: Union[int, float] = None, new_expires_at: int = None) -> bool:
        """
        Met à jour l'expiration d'un cooldown existant.
        
        Args:
            cooldown_name: Nom du cooldown à modifier
            new_duration: Nouvelle durée en secondes depuis maintenant (optionnel)
            new_expires_at: Nouveau timestamp d'expiration absolu (optionnel)
            
        Returns:
            bool: True si le cooldown a été mis à jour, False s'il n'existe pas
            
        Note:
            Si new_duration ET new_expires_at sont fournis, new_expires_at prendra la priorité.
        """
        if new_duration is None and new_expires_at is None:
            raise ValueError("Au moins un paramètre (new_duration ou new_expires_at) doit être fourni")
        
        # Vérifie d'abord si le cooldown existe
        cooldown = self.get(cooldown_name)
        if not cooldown:
            return False
        
        # Calcule le nouveau timestamp d'expiration
        if new_expires_at is not None:
            expires_at = new_expires_at
        else:
            current_time = int(time.time())
            expires_at = current_time + int(new_duration)
        
        with closing(self.manager.conn.cursor()) as cursor:
            cursor.execute(
                'UPDATE cooldowns SET expires_at = ? WHERE bucket_key = ? AND cooldown_name = ?',
                (expires_at, self.bucket_key, cooldown_name)
            )
            updated = cursor.rowcount > 0
            self.manager.conn.commit()
        
        if updated:
            logger.debug(f"Cooldown '{cooldown_name}' du bucket '{self.bucket_key}' mis à jour (nouvelle expiration: {expires_at})")
        return updated
    
    def remove(self, cooldown_name: str) -> bool:
        """Supprime un cooldown spécifique de ce bucket."""
        with closing(self.manager.conn.cursor()) as cursor:
            cursor.execute(
                'DELETE FROM cooldowns WHERE bucket_key = ? AND cooldown_name = ?',
                (self.bucket_key, cooldown_name)
            )
            deleted = cursor.rowcount > 0
            self.manager.conn.commit()
            
        if deleted:
            logger.debug(f"Cooldown '{cooldown_name}' supprimé du bucket '{self.bucket_key}'")
        return deleted
    
    def clear(self) -> int:
        """Supprime tous les cooldowns de ce bucket."""
        with closing(self.manager.conn.cursor()) as cursor:
            cursor.execute(
                'DELETE FROM cooldowns WHERE bucket_key = ?',
                (self.bucket_key,)
            )
            deleted_count = cursor.rowcount
            self.manager.conn.commit()
            
        logger.debug(f"Supprimé {deleted_count} cooldowns du bucket '{self.bucket_key}'")
        return deleted_count
    
    def get_all(self) -> list['Cooldown']:
        """Retourne tous les cooldowns actifs de ce bucket."""
        with closing(self.manager.conn.cursor()) as cursor:
            cursor.execute(
                'SELECT * FROM cooldowns WHERE bucket_key = ? ORDER BY expires_at ASC',
                (self.bucket_key,)
            )
            rows = cursor.fetchall()
            
            active_cooldowns = []
            for row in rows:
                cooldown = Cooldown.from_row(row)
                if not cooldown.is_expired():
                    active_cooldowns.append(cooldown)
                else:
                    # Nettoie les cooldowns expirés au passage
                    self.remove(cooldown.cooldown_name)
            
            return active_cooldowns


class Cooldown:
    """Représente un cooldown individuel."""
    
    def __init__(self,
                 bucket_key: str,
                 cooldown_name: str,
                 expires_at: int,
                 created_at: int,
                 metadata: str = None):
        self.bucket_key = bucket_key
        self.cooldown_name = cooldown_name
        self.expires_at = expires_at
        self.created_at = created_at
        self.metadata = metadata
    
    def __repr__(self):
        return f"Cooldown(bucket='{self.bucket_key}', name='{self.cooldown_name}', expires_at={self.expires_at})"
    
    @property
    def duration(self) -> int:
        """Retourne la durée totale du cooldown en secondes."""
        return self.expires_at - self.created_at
    
    def is_expired(self) -> bool:
        """Vérifie si le cooldown a expiré."""
        return int(time.time()) >= self.expires_at
    
    def remaining_time(self) -> float:
        """Retourne le temps restant en secondes (0 si expiré)."""
        if self.is_expired():
            return 0.0
        return self.expires_at - time.time()
    
    def format_remaining_time(self) -> str:
        """Retourne le temps restant formaté (ex: '2h 15m 30s')."""
        remaining = self.remaining_time()
        if remaining <= 0:
            return "Expiré"
        
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0 or not parts:  # Affiche les secondes si c'est tout ce qui reste
            parts.append(f"{seconds}s")
        
        return " ".join(parts)
    
    def format_cooldown_message(self) -> str:
        """Retourne un message formaté pour l'affichage d'erreur de cooldown."""
        remaining = self.remaining_time()
        if remaining <= 0:
            return "**COOLDOWN** · Le cooldown a expiré."
        
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        seconds = int(remaining % 60)
        
        time_parts = []
        if hours > 0:
            time_parts.append(f"**{hours}h**")
        if minutes > 0:
            time_parts.append(f"**{minutes}m**")
        if seconds > 0 or not time_parts:  # Affiche les secondes si c'est tout ce qui reste
            time_parts.append(f"**{seconds}s**")
        
        time_str = " ".join(time_parts)
        return f"**COOLDOWN** · Vous devez attendre encore {time_str}."
    
    def progress(self) -> float:
        """Retourne le pourcentage de progression (0.0 à 1.0)."""
        elapsed = int(time.time()) - self.created_at
        return min(1.0, elapsed / self.duration) if self.duration > 0 else 1.0
    
    def to_dict(self) -> dict:
        """Convertit le cooldown en dictionnaire."""
        return {
            'bucket_key': self.bucket_key,
            'cooldown_name': self.cooldown_name,
            'expires_at': self.expires_at,
            'created_at': self.created_at,
            'metadata': self.metadata,
            'remaining_time': self.remaining_time(),
            'is_expired': self.is_expired()
        }
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Cooldown':
        """Crée une instance de Cooldown à partir d'une ligne de base de données."""
        return cls(
            bucket_key=row['bucket_key'],
            cooldown_name=row['cooldown_name'],
            expires_at=row['expires_at'],
            created_at=row['created_at'],
            metadata=row['metadata']
        )
    
    def save(self, manager: CooldownManager):
        """Sauvegarde le cooldown dans la base de données."""
        with closing(manager.conn.cursor()) as cursor:
            cursor.execute('''
                INSERT OR REPLACE INTO cooldowns 
                (bucket_key, cooldown_name, expires_at, created_at, metadata) 
                VALUES (?, ?, ?, ?, ?)
            ''', (
                self.bucket_key, self.cooldown_name, 
                self.expires_at, self.created_at, self.metadata
            ))
            manager.conn.commit()


# Décorateurs ================================================

def command_cooldown(duration: Union[int, float], 
             cooldown_name: str = None,
             per: type = None,
             error_message: str = None):
    """
    Décorateur pour ajouter un cooldown à une commande Discord.
    
    Args:
        duration: Durée du cooldown en secondes
        cooldown_name: Nom du cooldown (optionnel, utilise le nom de la fonction par défaut)
        per: Type d'entité pour le cooldown (discord.User, discord.Guild, discord.TextChannel, etc.)
             Par défaut: discord.User
        error_message: Message d'erreur personnalisé
    
    Examples:
        @cooldown(3600)  # 1h par utilisateur
        @cooldown(1800, per=discord.Guild)  # 30min par serveur
        @cooldown(300, per=discord.TextChannel)  # 5min par channel
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Détecte le contexte selon le type de commande
            ctx = None
            interaction = None
            
            if args and hasattr(args[0], 'bot'):  # Cog method
                if len(args) > 1:
                    if hasattr(args[1], 'response'):  # Slash command
                        interaction = args[1]
                    else:  # Text command
                        ctx = args[1]
            elif args and hasattr(args[0], 'response'):  # Direct slash command
                interaction = args[0]
            elif args and hasattr(args[0], 'send'):  # Direct text command
                ctx = args[0]
            
            # Extrait les entités selon le type de contexte
            if interaction:
                user = interaction.user
                guild = interaction.guild
                channel = interaction.channel
            elif ctx:
                user = ctx.author
                guild = ctx.guild
                channel = ctx.channel
            else:
                raise ValueError("Impossible de déterminer le contexte de la commande")
            
            # Détermine l'entité selon le paramètre 'per'
            if per is None or per in (discord.User, discord.Member):
                entity = user
            elif per == discord.Guild:
                entity = guild
                if entity is None:
                    raise ValueError("Cooldown per Guild mais pas dans un serveur")
            elif per in (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel):
                entity = channel
                if entity is None:
                    raise ValueError("Cooldown per Channel mais pas de channel trouvé")
            else:
                # Pour des types custom ou autres
                entity = per  # Utilise directement la valeur fournie
            
            cd_name = cooldown_name or func.__name__
            manager = CooldownManager()
            bucket = manager.get(entity)
            
            # Vérifie le cooldown
            try:
                bucket.check(cd_name)
            except CooldownActiveError as e:
                # Récupère le cooldown pour utiliser la méthode de formatage
                cooldown = bucket.get(cd_name)
                
                if error_message:
                    remaining = int(e.remaining_time)
                    msg = error_message.format(remaining=remaining)
                elif cooldown:
                    msg = cooldown.format_cooldown_message()
                else:
                    remaining = int(e.remaining_time)
                    msg = f"Commande en cooldown. Attendez encore {remaining} secondes."
                
                if interaction:
                    if interaction.response.is_done():
                        await interaction.followup.send(msg, ephemeral=True)
                    else:
                        await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await ctx.send(msg)
                return
            
            # Exécute la fonction
            result = await func(*args, **kwargs)
            
            # Applique le cooldown après succès
            bucket.set(cd_name, duration)
            
            return result
        
        return wrapper
    return decorator


def require_no_cooldown(cooldown_name: str, 
                       on_entity: Any = None,
                       error_message: str = None):
    """
    Décorateur qui vérifie qu'un cooldown n'est pas actif avant d'exécuter.
    
    Args:
        cooldown_name: Nom du cooldown à vérifier
        on_entity: Entité spécifique (si None, utilise l'utilisateur par défaut)
        error_message: Message d'erreur personnalisé
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Même logique de détection de contexte
            ctx = None
            interaction = None
            
            if args and hasattr(args[0], 'bot'):
                if len(args) > 1:
                    if hasattr(args[1], 'response'):
                        interaction = args[1]
                    else:
                        ctx = args[1]
            elif args and hasattr(args[0], 'response'):
                interaction = args[0]
            elif args and hasattr(args[0], 'send'):
                ctx = args[0]
            
            if interaction:
                user = interaction.user
                guild = interaction.guild
                channel = interaction.channel
            elif ctx:
                user = ctx.author
                guild = ctx.guild
                channel = ctx.channel
            else:
                raise ValueError("Impossible de déterminer le contexte")
            
            # Sélectionne l'entité
            entity = on_entity or user
            
            manager = CooldownManager()
            bucket = manager.get(entity)
            
            try:
                bucket.check(cooldown_name)
            except CooldownActiveError as e:
                # Récupère le cooldown pour utiliser la méthode de formatage
                cooldown = bucket.get(cooldown_name)
                
                if error_message:
                    msg = error_message
                elif cooldown:
                    msg = cooldown.format_cooldown_message()
                else:
                    remaining = int(e.remaining_time)
                    msg = f"Action bloquée par un cooldown ({remaining}s restantes)"
                
                if interaction:
                    if interaction.response.is_done():
                        await interaction.followup.send(msg, ephemeral=True)
                    else:
                        await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await ctx.send(msg)
                return
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# Fonctions utilitaires ================================================

def get_bucket(entity: Any) -> CooldownBucket:
    """Fonction utilitaire pour obtenir le bucket de cooldowns d'une entité."""
    manager = CooldownManager()
    return manager.get(entity)

def cleanup_expired_cooldowns() -> int:
    """Fonction utilitaire pour nettoyer les cooldowns expirés."""
    manager = CooldownManager()
    return manager.cleanup_expired()

def get_all_cooldowns(entity: Any) -> list[Cooldown]:
    """Récupère tous les cooldowns actifs d'une entité."""
    bucket = get_bucket(entity)
    return bucket.get_all()

def set_cooldown(entity: Any, cooldown_name: str, duration: Union[int, float], 
                metadata: str = None) -> Cooldown:
    """Définit rapidement un cooldown pour une entité."""
    bucket = get_bucket(entity)
    return bucket.set(cooldown_name, duration, metadata)

def check_cooldown(entity: Any, cooldown_name: str) -> bool:
    """Vérifie rapidement si une entité a un cooldown actif."""
    bucket = get_bucket(entity)
    return bucket.has(cooldown_name)

def get_remaining_time(entity: Any, cooldown_name: str) -> float:
    """Récupère rapidement le temps restant d'un cooldown."""
    bucket = get_bucket(entity)
    return bucket.remaining(cooldown_name)

def update_cooldown_expiration(entity: Any, cooldown_name: str, 
                             new_duration: Union[int, float] = None, 
                             new_expires_at: int = None) -> bool:
    """
    Met à jour l'expiration d'un cooldown pour une entité.
    
    Args:
        entity: L'entité (User, Guild, Channel, etc.)
        cooldown_name: Nom du cooldown à modifier
        new_duration: Nouvelle durée en secondes depuis maintenant (optionnel)
        new_expires_at: Nouveau timestamp d'expiration absolu (optionnel)
        
    Returns:
        bool: True si le cooldown a été mis à jour, False s'il n'existe pas
        
    Examples:
        # Étendre le cooldown de 30 minutes supplémentaires
        update_cooldown_expiration(user, "daily_bonus", new_duration=1800)
        
        # Définir une expiration absolue
        update_cooldown_expiration(guild, "event_cd", new_expires_at=1692720000)
    """
    bucket = get_bucket(entity)
    return bucket.update_expiration(cooldown_name, new_duration, new_expires_at)

def get_entities_with_cooldown(cooldown_name: str) -> list[dict]:
    """
    Récupère toutes les entités ayant un cooldown spécifique actif.
    
    Args:
        cooldown_name: Nom du cooldown à rechercher
        
    Returns:
        list[dict]: Liste des entités avec leurs informations
        
    Example:
        entities = get_entities_with_cooldown("daily_bonus")
        for entity in entities:
            print(f"{entity['entity_type']} {entity['entity_id']} expire dans {entity['cooldown'].remaining_time()}s")
    """
    manager = CooldownManager()
    return manager.get_entities_with_cooldown(cooldown_name)

def get_cooldown_statistics(cooldown_name: str) -> dict:
    """
    Récupère des statistiques détaillées sur un cooldown spécifique.
    
    Args:
        cooldown_name: Nom du cooldown à analyser
        
    Returns:
        dict: Statistiques complètes du cooldown
        
    Example:
        stats = get_cooldown_statistics("daily_bonus")
        print(f"Cooldown actif sur {stats['active_count']} entités")
        print(f"Types d'entités: {stats['entity_types']}")
    """
    manager = CooldownManager()
    return manager.get_cooldown_statistics(cooldown_name)
    