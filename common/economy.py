import logging
import sqlite3
import time
import hashlib
import string
from contextlib import closing
from pathlib import Path
from datetime import datetime
from typing import Iterable, Callable, Union

import discord

logger = logging.getLogger('Economy')

DB_PATH = Path('common/global/')

STARTING_BALANCE = 250  # Solde initial pour les nouveaux comptes
MONEY_SYMBOL = 'g' # Symbole de la monnaie utilisée dans les opérations

# Exceptions ================================

class EconomyError(Exception):
    """Exception de base pour les erreurs économiques."""
    pass

class AccountError(EconomyError):
    """Exception pour les erreurs liées aux comptes."""
    pass

class InsufficientFundsError(AccountError):
    """Exception pour les fonds insuffisants."""
    pass

class OperationError(EconomyError):
    """Exception pour les erreurs liées aux operations."""
    pass

class InvalidAmountError(OperationError):
    """Exception pour les montants invalides dans les operations."""
    pass

# ID Generation ================================

IDG_ALPHA = string.digits + string.ascii_uppercase + string.ascii_lowercase
IDG_BASE = len(IDG_ALPHA)

def to_base62(num: int) -> str:
    if num == 0:
        return IDG_ALPHA[0]
    chars = []
    while num > 0:
        num, rem = divmod(num, IDG_BASE)
        chars.append(IDG_ALPHA[rem])
    return ''.join(reversed(chars))

def generate_id(user_id: int, balance: int, description: str, timestamp: int = None) -> str:
    if timestamp is None:
        timestamp = int(time.time())
    if isinstance(timestamp, datetime):
        timestamp = int(timestamp.timestamp())
    if not isinstance(user_id, int) or not isinstance(balance, int):
        raise TypeError("user_id and balance must be integers.")
    
    # Encodage de l'horodatage en base62
    ts_part = to_base62(timestamp)

    # Petit hash pour différencier en cas de collisions
    data = f"{user_id}-{balance}-{description}".encode()
    h = hashlib.blake2s(data, digest_size=2).digest()  # 16 bits
    hash_num = int.from_bytes(h, "big")
    hash_part = to_base62(hash_num)

    return f"{ts_part}{hash_part}"

# Classes =================================

class EconomyDBManager:
    """Gestionnaire de la base de données économique."""
    _instance = None
    
    def __new__(cls, db_path: Path = DB_PATH):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: Path = DB_PATH):
        if self._initialized:
            return
        
        self.db_path = db_path
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        self.conn = self._connect()
        self._initialize(self.conn)
        self._initialized = True

    def __del__(self):
        if self.conn:
            self.conn.close()
        
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path / 'economy.db')
        conn.row_factory = sqlite3.Row
        return conn
    
    def _initialize(self, connection: sqlite3.Connection):
        with closing(connection.cursor()) as cursor:
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS economy (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT {STARTING_BALANCE}
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    delta INTEGER,
                    description TEXT,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES economy(user_id)
                )
            ''')
            self.conn.commit()
            
    # Comptes -----------------------------
    
    def get_account(self, user: discord.User | discord.Member) -> 'BankAccount':
        """Retourne le compte bancaire d'un utilisateur."""
        return BankAccount(user, self)
    
    def get_accounts(self, users: Iterable[discord.User | discord.Member]) -> Iterable['BankAccount']:
        """Retourne les comptes bancaires pour une liste d'utilisateurs."""
        return (self.get_account(user) for user in users)
    
    # Opérations -----------------------------
    
    def get_operation_by_id(self, operation_id: str) -> 'Operation':
        """Retourne une opération par son ID."""
        with closing(self.conn.cursor()) as cursor:
            cursor.execute('SELECT * FROM operations WHERE id = ?', (operation_id,))
            row = cursor.fetchone()
            if row:
                return Operation.from_row(row)
            else:
                raise OperationError(f"Aucune opération trouvée avec l'ID {operation_id}.")
    
    def get_operations(self, func: Callable[['Operation'], bool] = None) -> Iterable['Operation']:
        """Retourne toutes les opérations, filtrées si un filtre est fourni."""
        with closing(self.conn.cursor()) as cursor:
            cursor.execute('SELECT * FROM operations ORDER BY timestamp DESC')
            rows = cursor.fetchall()
            operations = [Operation.from_row(row) for row in rows]
            if func:
                operations = filter(func, operations)
            return operations
    
    
class BankAccount:
    """Représente un compte bancaire d'utilisateur."""
    def __init__(self, 
                 user: discord.User | discord.Member,
                 db_manager: EconomyDBManager):
        self.user = user
        self.db_manager = db_manager
        
        self._balance : int = self._load_balance()
        
    def __repr__(self):
        return f"BankAccount(user={self.user}, balance={self.balance})"
    
    def _load_balance(self) -> int:
        with closing(self.db_manager.conn.cursor()) as cursor:
            cursor.execute('SELECT balance FROM economy WHERE user_id = ?', (self.user.id,))
            row = cursor.fetchone()
            if row:
                return row['balance']
            else:
                self._create_account()
                return STARTING_BALANCE
            
    def _create_account(self):
        with closing(self.db_manager.conn.cursor()) as cursor:
            cursor.execute('INSERT INTO economy (user_id, balance) VALUES (?, ?)', 
                           (self.user.id, STARTING_BALANCE))
            self.db_manager.conn.commit()
    
    # Solde --------------------------------
    
    @property
    def balance(self) -> int:
        """Retourne le solde du compte."""
        return self._balance
    
    def __update_balance(self, new_balance: int):
        new_balance = int(new_balance)  # Assure que le solde est un entier
        
        with closing(self.db_manager.conn.cursor()) as cursor:
            cursor.execute('UPDATE economy SET balance = ? WHERE user_id = ?',
                           (new_balance, self.user.id))
            self.db_manager.conn.commit()
        self._balance = new_balance
            
    def __register_operation(self, new_balance: int, description: str) -> 'Operation':
        new_balance = int(new_balance)  # Assure que le solde est un entier
        
        delta = new_balance - self.balance
        if delta == 0:
            return
        operation = Operation(
            user_id=int(self.user.id),  # Conversion explicite en entier
            delta=delta,
            description=description
        )
        operation.save(self.db_manager)
        self.__update_balance(new_balance)
        return operation
        
    def assign(self, value: int, description: str = "Ajustement de solde") -> 'Operation':
        """Affecte un montant au solde du compte."""
        if value < 0:
            raise InvalidAmountError("Le montant doit être positif pour l'affectation.")
        return self.__register_operation(value, description)
    
    def deposit(self, value: int, description: str = "Entrée de fonds") -> 'Operation':
        """Dépose un montant sur le compte."""
        if value <= 0:
            raise InvalidAmountError("Le montant doit être supérieur à zéro pour le dépôt.")
        
        new_balance = self.balance + value
        return self.__register_operation(new_balance, description)
    
    def withdraw(self, value: int, description: str = "Retrait de fonds") -> 'Operation':
        """Retire un montant du compte."""
        value = abs(value)  # Assure que le montant est positif
        
        if self.balance < value:
            raise InsufficientFundsError("Fonds insuffisants pour le retrait.")
        
        new_balance = self.balance - value
        return self.__register_operation(new_balance, description)
    
    def reverse(self, operation: Union['Operation', str]) -> 'Operation':
        """Effectue une opération inverse d'une opération existante."""
        if isinstance(operation, str):
            operation_id = operation
            operation = self.db_manager.get_operation_by_id(operation_id)
        elif not isinstance(operation, Operation):
            raise TypeError("L'opération doit être une instance de Operation ou un ID d'opération.")
        if operation.user_id != self.user.id:
            raise AccountError("L'opération ne correspond pas à ce compte.")
        new_balance = self.balance - operation.delta
        if new_balance < 0:
            raise InsufficientFundsError("Le solde ne peut pas devenir négatif après l'annulation.")
        return self.__register_operation(new_balance, f"Annulation de l'opération {operation.id}")
    
    def rollback(self, target_operation: Union['Operation', str]) -> Iterable['Operation']:
        """Annule toutes les opérations jusqu'à une opération cible (incluse)."""
        if isinstance(target_operation, str):
            operation_id = target_operation
            target_operation = self.db_manager.get_operation_by_id(operation_id)
        elif not isinstance(target_operation, Operation):
            raise TypeError("L'opération doit être une instance de Operation ou un ID d'opération.")
        if target_operation.user_id != self.user.id:
            raise AccountError("L'opération ne correspond pas à ce compte.")
        
        operations = self.db_manager.get_operations(
            func=lambda op: op.user_id == self.user.id
        )
        
        to_rollback = []
        for op in operations:
            to_rollback.append(op)
            if op.id == target_operation.id:
                break
        else:
            raise OperationError("L'opération cible n'a pas été trouvée dans l'historique.")
        
        rolled_back_ops = []
        for op in to_rollback:
            rolled_back_op = self.reverse(op)
            if rolled_back_op:
                rolled_back_ops.append(rolled_back_op)
        
        return rolled_back_ops
    
    # Transactions -----------------------------
    
    def get_recent_operations(self, limit: int = 5) -> Iterable['Operation']:
        """Retourne les opérations récentes du compte."""
        ops = self.db_manager.get_operations(
            func=lambda op: op.user_id == self.user.id
        )
        return list(ops)[:limit]
    
    # Statistiques -----------------------------
    
    def get_variation_since(self, since: int | float) -> int:
        """Retourne la variation du solde depuis un timestamp donné."""
        ops = self.db_manager.get_operations(
            func=lambda op: op.user_id == self.user.id and op.timestamp >= since
        )
        return sum(op.delta for op in ops) or 0
    
    def get_rank_in_guild(self, guild: discord.Guild, ignore_bots: bool = True) -> int:
        """Retourne le rang du compte dans la guilde."""
        members = guild.members
        if ignore_bots:
            members = [m for m in members if not m.bot]
        accounts = self.db_manager.get_accounts(members)
        sorted_accounts = sorted(accounts, key=lambda acc: acc.balance, reverse=True)
        for rank, account in enumerate(sorted_accounts, start=1):
            if account.user.id == self.user.id:
                return rank
    
    
class Operation:
    """Représente une opération économique sur un compte."""
    def __init__(self, 
                 user_id: int,
                 delta: int,
                 description: str,
                 timestamp: int = None):
        self.user_id = user_id
        self.delta = delta
        self.description = description
        self.timestamp = timestamp or int(time.time())
        
        self.id = generate_id(user_id, delta, description, self.timestamp)
        
    def __repr__(self):
        return f"Operation(user_id={self.user_id}, delta={self.delta}, description='{self.description}', timestamp={self.timestamp})"
    
    def to_dict(self) -> dict:
        """Convertit l'opération en dictionnaire pour la sérialisation."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'delta': self.delta,
            'description': self.description,
            'timestamp': self.timestamp
        }
        
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Operation':
        """Crée une instance d'Operation à partir d'une ligne de la base de données."""
        return cls(
            user_id=row['user_id'],
            delta=row['delta'],
            description=row['description'],
            timestamp=row['timestamp']  # Directement un int depuis la DB
        )

    def save(self, db_manager: EconomyDBManager):
        """Enregistre l'opération dans la base de données."""
        with closing(db_manager.conn.cursor()) as cursor:
            cursor.execute('INSERT INTO operations (id, user_id, delta, description, timestamp) VALUES (?, ?, ?, ?, ?)',
                           (self.id, self.user_id, self.delta, self.description, self.timestamp))
            db_manager.conn.commit()
