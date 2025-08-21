import discord
from discord.ext import commands
from discord import app_commands, ui
import yaml
import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from common import dataio
from common.economy import EconomyDBManager, MONEY_SYMBOL

logger = logging.getLogger(f'ROBIN.{__name__}')

ICONS = {
    'banner': '<:banner:1408138422035415121>'
}

BANNERS_DATA_PATH = Path(__file__).parent / 'banners_data.yaml'

@dataclass
class BannerData:
    """Données d'une bannière."""
    id: str
    name: str
    image_url: str
    price: int
    available: bool = True
    max_quantity: int = 1

class UserBanner:
    """Représente une bannière possédée par un utilisateur."""
    def __init__(self, banner_id: str, is_active: bool = False):
        self.banner_id = banner_id
        self.is_active = is_active

# VUES LAYOUTVIEW ==========================================

class BannersShopView(ui.LayoutView):
    """Vue pour la boutique de bannières."""
    def __init__(self, banners_cog: 'Banners', user: discord.User):
        super().__init__(timeout=300)  # 5 minutes
        self.banners_cog = banners_cog
        self.user = user
        
        # Récupérer toutes les bannières disponibles
        self.available_banners = [banner for banner in banners_cog.banners_data.values() if banner.available]
        
        # Pagination (3 bannières par page)
        self.pages = [self.available_banners[i:i + 3] for i in range(0, len(self.available_banners), 3)]
        if not self.pages:
            self.pages = [[]]
        self.current_page = 0
        
        self.build_interface()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message("Vous ne pouvez pas utiliser ce menu.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        """Appelé quand la vue expire."""
        self._disable_all_buttons()
        self.build_interface()
        
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except:
            pass
    
    def _disable_all_buttons(self):
        """Désactive tous les boutons de la vue."""
        for item in self.children:
            if hasattr(item, 'children'):
                for child in item.children:
                    if hasattr(child, 'children'):
                        for button in child.children:
                            if isinstance(button, ui.Button):
                                button.disabled = True
    
    def build_interface(self):
        """Construit l'interface de la boutique."""
        self.clear_items()
        
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f"## Boutique de Bannières · {len(self.available_banners)} bannières disponibles")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Afficher les bannières de la page courante
        page_banners = self.pages[self.current_page] if self.current_page < len(self.pages) else []
        
        if not page_banners:
            no_banners = ui.TextDisplay("Aucune bannière disponible actuellement.")
            container.add_item(no_banners)
        else:
            user_banners = self.banners_cog.get_user_banners(self.user)
            owned_banner_ids = [b.banner_id for b in user_banners]
            
            # Récupérer le solde de l'utilisateur
            account = self.banners_cog.eco.get_account(self.user)
            user_balance = account.balance
            
            for i, banner in enumerate(page_banners):
                # Titre avec nom (sans emoji)
                banner_title = ui.TextDisplay(f"### {banner.name}")
                
                # Déterminer l'état du bouton
                is_owned = banner.id in owned_banner_ids
                has_enough_money = user_balance >= banner.price
                
                if is_owned:
                    # Déjà possédée - proposer la revente
                    sell_price = banner.price // 2
                    price_info = f"**Prix d'achat :** ~~{banner.price}{MONEY_SYMBOL}~~ · **Revente :** {sell_price}{MONEY_SYMBOL}"
                    button = BannerSellButton(banner.id, banner.name, sell_price)
                elif not has_enough_money:
                    # Fonds insuffisants
                    price_info = f"**Prix :** {banner.price}{MONEY_SYMBOL} · *Solde : {user_balance}{MONEY_SYMBOL}*"
                    button = ui.Button(label="Fonds insuffisants", style=discord.ButtonStyle.danger, disabled=True)
                else:
                    # Peut acheter
                    price_info = f"**Prix :** {banner.price}{MONEY_SYMBOL}"
                    button = BannerBuyButton(banner.id, banner.name, banner.price)
                
                banner_info = ui.TextDisplay(price_info)
                
                # Créer la section avec le bouton
                banner_section = ui.Section(banner_title, banner_info, accessory=button)
                container.add_item(banner_section)
                
                # Ajouter l'image via MediaGallery
                if banner.image_url:
                    media_gallery = ui.MediaGallery()
                    media_gallery.add_item(media=banner.image_url, description=banner.name)
                    container.add_item(media_gallery)
                
                # Séparateur entre bannières (sauf la dernière)
                if i < len(page_banners) - 1:
                    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        
        self.add_item(container)
        
        # Navigation si nécessaire
        if len(self.pages) > 1:
            navigation = BannersShopNavigationButtons()
            self.add_item(navigation)
            navigation.update_buttons()
        
        # Bouton fermer en bas dans un ActionRow
        close_row = ui.ActionRow()
        close_button = CloseButton()
        close_row.add_item(close_button)
        self.add_item(close_row)
    
    def update_display(self):
        """Met à jour l'affichage de la boutique."""
        self.build_interface()

class BannersSelectionView(ui.LayoutView):
    """Vue pour sélectionner sa bannière active."""
    def __init__(self, banners_cog: 'Banners', user: discord.User):
        super().__init__(timeout=300)  # 5 minutes
        self.banners_cog = banners_cog
        self.user = user
        
        # Récupérer les bannières possédées
        self.user_banners = banners_cog.get_user_banners(user)
        
        # Pagination (3 bannières par page)
        self.pages = [self.user_banners[i:i + 3] for i in range(0, len(self.user_banners), 3)]
        if not self.pages:
            self.pages = [[]]
        self.current_page = 0
        
        self.build_interface()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message("Vous ne pouvez pas utiliser ce menu.", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        """Appelé quand la vue expire."""
        self._disable_all_buttons()
        self.build_interface()
        
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
        except:
            pass
    
    def _disable_all_buttons(self):
        """Désactive tous les boutons de la vue."""
        for item in self.children:
            if hasattr(item, 'children'):
                for child in item.children:
                    if hasattr(child, 'children'):
                        for button in child.children:
                            if isinstance(button, ui.Button):
                                button.disabled = True
    
    def build_interface(self):
        """Construit l'interface de sélection."""
        self.clear_items()
        
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f"## Mes Bannières · {len(self.user_banners)} possédées")
        container.add_item(header)
        
        # Bouton pour retirer la bannière actuelle
        current_banner = self.banners_cog.get_current_banner(self.user)
        if current_banner:
            remove_button = RemoveBannerButton()
            remove_info = ui.TextDisplay("*Cliquez pour retirer votre bannière actuelle*")
            remove_section = ui.Section(remove_info, accessory=remove_button)
            container.add_item(remove_section)
        
        container.add_item(ui.Separator())
        
        # Afficher les bannières de la page courante
        page_banners = self.pages[self.current_page] if self.current_page < len(self.pages) else []
        
        if not page_banners:
            no_banners = ui.TextDisplay("Vous ne possédez aucune bannière.\nUtilisez `/banners shop` pour en acheter.")
            container.add_item(no_banners)
        else:
            for i, user_banner in enumerate(page_banners):
                banner_data = self.banners_cog.banners_data.get(user_banner.banner_id)
                if not banner_data:
                    continue
                
                # Titre avec nom et statut (sans emoji)
                if user_banner.is_active:
                    banner_title = ui.TextDisplay(f"### {banner_data.name} (Actuelle)")
                    button = ui.Button(label="Actuelle", style=discord.ButtonStyle.success, disabled=True)
                else:
                    banner_title = ui.TextDisplay(f"### {banner_data.name}")
                    # Utiliser seulement le bouton utiliser (la vente se fait dans la boutique)
                    button = BannerSelectButton(user_banner.banner_id, banner_data.name)
                
                # Créer la section
                banner_section = ui.Section(banner_title, accessory=button)
                container.add_item(banner_section)
                
                # Ajouter l'image via MediaGallery
                if banner_data.image_url:
                    media_gallery = ui.MediaGallery()
                    media_gallery.add_item(media=banner_data.image_url, description=banner_data.name)
                    container.add_item(media_gallery)
                
                # Séparateur entre bannières (sauf la dernière)
                if i < len(page_banners) - 1:
                    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        
        self.add_item(container)
        
        # Navigation si nécessaire
        if len(self.pages) > 1:
            navigation = BannersSelectionNavigationButtons()
            self.add_item(navigation)
            navigation.update_buttons()
        
        # Bouton fermer en bas dans un ActionRow
        close_row = ui.ActionRow()
        close_button = CloseButton()
        close_row.add_item(close_button)
        self.add_item(close_row)
    
    def update_display(self):
        """Met à jour l'affichage de la sélection."""
        # Recharger les bannières de l'utilisateur
        self.user_banners = self.banners_cog.get_user_banners(self.user)
        self.pages = [self.user_banners[i:i + 3] for i in range(0, len(self.user_banners), 3)]
        if not self.pages:
            self.pages = [[]]
        # S'assurer que la page actuelle est valide
        if self.current_page >= len(self.pages):
            self.current_page = max(0, len(self.pages) - 1)
        self.build_interface()

# BOUTONS ==========================================

class BannerBuyButton(ui.Button['BannersShopView']):
    """Bouton pour acheter une bannière."""
    def __init__(self, banner_id: str, banner_name: str, price: int):
        super().__init__(label="Acheter", style=discord.ButtonStyle.success)
        self.banner_id = banner_id
        self.banner_name = banner_name
        self.price = price
    
    async def callback(self, interaction: discord.Interaction):
        """Lance l'achat de la bannière."""
        account = self.view.banners_cog.eco.get_account(interaction.user)
        
        # Vérifier si déjà possédée (sécurité supplémentaire)
        user_banners = self.view.banners_cog.get_user_banners(interaction.user)
        if any(b.banner_id == self.banner_id for b in user_banners):
            return await interaction.response.send_message(f"**ERREUR** · Vous possédez déjà cette bannière.", ephemeral=True)
        
        # Vérifier le solde (sécurité supplémentaire)
        if account.balance < self.price:
            return await interaction.response.send_message(
                f"**SOLDE INSUFFISANT** · Vous n'avez pas assez de fonds pour cet achat.",
                ephemeral=True
            )
        
        try:
            # Effectuer l'achat
            account.withdraw(self.price, f"Achat bannière - {self.banner_name}")
            
            # Ajouter la bannière à l'inventaire
            self.view.banners_cog.add_user_banner(interaction.user, self.banner_id)
            
            # Mettre à jour l'affichage de la boutique (sans message de confirmation)
            await interaction.response.defer()
            
            try:
                self.view.update_display()
                if hasattr(self.view, 'message') and self.view.message:
                    await self.view.message.edit(view=self.view)
            except Exception as edit_error:
                print(f"Erreur lors de la mise à jour de la boutique: {edit_error}")
            
        except Exception as e:
            await interaction.response.send_message(f"**ERREUR** · {str(e)}", ephemeral=True)

class BannerSelectButton(ui.Button['BannersSelectionView']):
    """Bouton pour sélectionner une bannière comme active."""
    def __init__(self, banner_id: str, banner_name: str):
        super().__init__(label="Utiliser", style=discord.ButtonStyle.primary)
        self.banner_id = banner_id
        self.banner_name = banner_name
    
    async def callback(self, interaction: discord.Interaction):
        """Définit cette bannière comme active."""
        try:
            self.view.banners_cog.set_current_banner(interaction.user, self.banner_id)
            
            # Mettre à jour l'affichage (sans message de confirmation)
            await interaction.response.defer()
            
            try:
                self.view.update_display()
                if hasattr(self.view, 'message') and self.view.message:
                    await self.view.message.edit(view=self.view)
            except Exception as edit_error:
                print(f"Erreur lors de la mise à jour: {edit_error}")
            
        except Exception as e:
            await interaction.response.send_message(f"**ERREUR** · {str(e)}", ephemeral=True)

class BannerSellButton(ui.Button):
    """Bouton pour vendre une bannière."""
    def __init__(self, banner_id: str, banner_name: str, sell_price: int):
        super().__init__(label=f"Vendre ({sell_price}{MONEY_SYMBOL})", style=discord.ButtonStyle.danger)
        self.banner_id = banner_id
        self.banner_name = banner_name
        self.sell_price = sell_price
    
    async def callback(self, interaction: discord.Interaction):
        """Vend la bannière."""
        try:
            # Vérifier que la bannière n'est pas active
            current_banner = self.view.banners_cog.get_current_banner(interaction.user)
            if current_banner and current_banner.banner_id == self.banner_id:
                return await interaction.response.send_message(
                    f"**ERREUR** · Vous ne pouvez pas vendre votre bannière active. Changez d'abord de bannière ou retirez-la.",
                    ephemeral=True
                )
            
            # Effectuer la vente
            account = self.view.banners_cog.eco.get_account(interaction.user)
            account.deposit(self.sell_price, f"Vente bannière - {self.banner_name}")
            
            # Retirer la bannière de l'inventaire
            self.view.banners_cog.remove_user_banner(interaction.user, self.banner_id)
            
            # Mettre à jour l'affichage (sans message de confirmation)
            await interaction.response.defer()
            
            try:
                self.view.update_display()
                if hasattr(self.view, 'message') and self.view.message:
                    await self.view.message.edit(view=self.view)
            except Exception as edit_error:
                print(f"Erreur lors de la mise à jour: {edit_error}")
            
        except Exception as e:
            await interaction.response.send_message(f"**ERREUR** · {str(e)}", ephemeral=True)

class RemoveBannerButton(ui.Button['BannersSelectionView']):
    """Bouton pour retirer la bannière actuelle."""
    def __init__(self):
        super().__init__(label="Retirer la bannière", style=discord.ButtonStyle.secondary)
    
    async def callback(self, interaction: discord.Interaction):
        """Retire la bannière actuelle."""
        try:
            self.view.banners_cog.remove_current_banner(interaction.user)
            
            # Mettre à jour l'affichage (sans message de confirmation)
            await interaction.response.defer()
            
            try:
                self.view.update_display()
                if hasattr(self.view, 'message') and self.view.message:
                    await self.view.message.edit(view=self.view)
            except Exception as edit_error:
                print(f"Erreur lors de la mise à jour: {edit_error}")
            
        except Exception as e:
            await interaction.response.send_message(f"**ERREUR** · {str(e)}", ephemeral=True)

class CloseButton(ui.Button):
    """Bouton pour fermer le menu."""
    def __init__(self):
        super().__init__(label="Fermer", style=discord.ButtonStyle.secondary)
    
    async def callback(self, interaction: discord.Interaction):
        """Ferme le menu en supprimant le message."""
        try:
            await interaction.response.defer()
            if hasattr(self.view, 'message') and self.view.message:
                await self.view.message.delete()
        except Exception as e:
            print(f"Erreur lors de la fermeture: {e}")

# NAVIGATION ==========================================

class BannersShopNavigationButtons(ui.ActionRow['BannersShopView']):
    """Boutons de navigation pour la boutique."""
    def __init__(self):
        super().__init__()
        self.previous_button = ui.Button(label="Précédent", style=discord.ButtonStyle.secondary)
        self.next_button = ui.Button(label="Suivant", style=discord.ButtonStyle.secondary)
        
        self.previous_button.callback = self.previous_page
        self.next_button.callback = self.next_page
        
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
    
    async def previous_page(self, interaction: discord.Interaction):
        """Page précédente."""
        if self.view.current_page > 0:
            self.view.current_page -= 1
            self.view.build_interface()
            await interaction.response.edit_message(view=self.view)
        else:
            await interaction.response.defer()
    
    async def next_page(self, interaction: discord.Interaction):
        """Page suivante."""
        if self.view.current_page < len(self.view.pages) - 1:
            self.view.current_page += 1
            self.view.build_interface()
            await interaction.response.edit_message(view=self.view)
        else:
            await interaction.response.defer()
    
    def update_buttons(self):
        """Met à jour l'état des boutons."""
        self.previous_button.disabled = (self.view.current_page <= 0)
        self.next_button.disabled = (self.view.current_page >= len(self.view.pages) - 1)

class BannersSelectionNavigationButtons(ui.ActionRow['BannersSelectionView']):
    """Boutons de navigation pour la sélection."""
    def __init__(self):
        super().__init__()
        self.previous_button = ui.Button(label="Précédent", style=discord.ButtonStyle.secondary)
        self.next_button = ui.Button(label="Suivant", style=discord.ButtonStyle.secondary)
        
        self.previous_button.callback = self.previous_page
        self.next_button.callback = self.next_page
        
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
    
    async def previous_page(self, interaction: discord.Interaction):
        """Page précédente."""
        if self.view.current_page > 0:
            self.view.current_page -= 1
            self.view.build_interface()
            await interaction.response.edit_message(view=self.view)
        else:
            await interaction.response.defer()
    
    async def next_page(self, interaction: discord.Interaction):
        """Page suivante."""
        if self.view.current_page < len(self.view.pages) - 1:
            self.view.current_page += 1
            self.view.build_interface()
            await interaction.response.edit_message(view=self.view)
        else:
            await interaction.response.defer()
    
    def update_buttons(self):
        """Met à jour l'état des boutons."""
        self.previous_button.disabled = (self.view.current_page <= 0)
        self.next_button.disabled = (self.view.current_page >= len(self.view.pages) - 1)

# COG PRINCIPAL ==========================================

class Banners(commands.Cog):
    """Système de bannières pour les profils utilisateurs."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = dataio.get_instance(self)
        
        # Tables de base de données
        user_banners = dataio.TableBuilder(
            '''CREATE TABLE IF NOT EXISTS user_banners (
                user_id INTEGER,
                banner_id TEXT,
                is_active INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, banner_id)
                )'''
        )
        
        self.data.map_builders('global', user_banners)
        
        # Charger les données des bannières
        self._load_banners_data()
        
        # Économie
        self.eco = EconomyDBManager()
    
    async def cog_unload(self):
        self.data.close_all()
    
    def _load_banners_data(self):
        """Charge les données des bannières depuis le fichier YAML."""
        if not BANNERS_DATA_PATH.exists():
            logger.error(f"Le fichier de bannières '{BANNERS_DATA_PATH}' n'existe pas.")
            self.banners_data = {}
            return
        
        with open(BANNERS_DATA_PATH, 'r', encoding='utf-8') as f:
            raw_data = yaml.safe_load(f) or {}
        
        self.banners_data = {}
        for banner_id, data in raw_data.items():
            self.banners_data[banner_id] = BannerData(
                id=banner_id,
                name=data.get('name', 'Sans nom'),
                image_url=data.get('image_url', ''),
                price=data.get('price', 0),
                available=data.get('available', True),
                max_quantity=data.get('max_quantity', 1)
            )
        
        logger.info(f"Chargé {len(self.banners_data)} bannières.")
    
    # GESTION DES BANNIÈRES UTILISATEUR ==========================================
    
    def get_user_banners(self, user: discord.User | discord.Member) -> list[UserBanner]:
        """Récupère toutes les bannières d'un utilisateur."""
        results = self.data.get().fetchall(
            'SELECT banner_id, is_active FROM user_banners WHERE user_id = ?',
            user.id
        )
        
        user_banners = []
        for banner_id, is_active in results:
            user_banners.append(UserBanner(banner_id, bool(is_active)))
        
        return user_banners
    
    def add_user_banner(self, user: discord.User | discord.Member, banner_id: str):
        """Ajoute une bannière à l'inventaire de l'utilisateur."""
        self.data.get().execute(
            'INSERT OR IGNORE INTO user_banners (user_id, banner_id, is_active) VALUES (?, ?, ?)',
            user.id, banner_id, 0
        )
    
    def remove_user_banner(self, user: discord.User | discord.Member, banner_id: str):
        """Retire une bannière de l'inventaire de l'utilisateur."""
        self.data.get().execute(
            'DELETE FROM user_banners WHERE user_id = ? AND banner_id = ?',
            user.id, banner_id
        )
    
    def get_current_banner(self, user: discord.User | discord.Member) -> Optional[UserBanner]:
        """Récupère la bannière actuellement active de l'utilisateur."""
        result = self.data.get().fetchone(
            'SELECT banner_id FROM user_banners WHERE user_id = ? AND is_active = 1',
            user.id
        )
        
        if result:
            return UserBanner(result[0], True)
        return None
    
    def fetch_current_banner_data(self, user: discord.User | discord.Member) -> Optional[BannerData]:
        """Récupère les données de la bannière actuellement active de l'utilisateur."""
        current_banner = self.get_current_banner(user)
        if current_banner:
            return self.banners_data.get(current_banner.banner_id)
        return None
    
    def set_current_banner(self, user: discord.User | discord.Member, banner_id: str):
        """Définit une bannière comme active (et désactive les autres)."""
        # Désactiver toutes les bannières
        self.data.get().execute(
            'UPDATE user_banners SET is_active = 0 WHERE user_id = ?',
            user.id
        )
        
        # Activer la bannière choisie
        self.data.get().execute(
            'UPDATE user_banners SET is_active = 1 WHERE user_id = ? AND banner_id = ?',
            user.id, banner_id
        )
    
    def remove_current_banner(self, user: discord.User | discord.Member):
        """Retire la bannière actuellement active."""
        self.data.get().execute(
            'UPDATE user_banners SET is_active = 0 WHERE user_id = ?',
            user.id
        )
    
    # COMMANDES ==========================================
    
    banners_group = app_commands.Group(name="banners", description="Commandes liées aux bannières.")
    
    @banners_group.command(name="shop")
    async def cmd_banners_shop(self, interaction: discord.Interaction):
        """Parcourir, acheter et vendre des bannières dans la boutique."""
        view = BannersShopView(self, interaction.user)
        await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
        
        # Stocker la référence au message pour pouvoir le modifier lors de l'expiration
        view.message = await interaction.original_response()
    
    @banners_group.command(name="select")
    async def cmd_banners_select(self, interaction: discord.Interaction):
        """Choisir votre bannière active parmi celles que vous possédez."""
        view = BannersSelectionView(self, interaction.user)
        await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
        
        # Stocker la référence au message pour pouvoir le modifier lors de l'expiration
        view.message = await interaction.original_response()

async def setup(bot):
    await bot.add_cog(Banners(bot))