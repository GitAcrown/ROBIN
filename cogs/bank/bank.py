import logging
import yaml
from datetime import datetime, timedelta
from typing import Any, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

from common import dataio
from common.economy import EconomyDBManager, BankAccount, Operation, MONEY_SYMBOL

from cogs.banners.banners import Banners, BannerData

logger = logging.getLogger(f'ROBIN.{__name__.split(".")[-1]}')

ICONS = {
    'robin': '<:robin:1407801633181536377>',
    'coins': '<:coins:1407802826259959808>',
    'chart': '<:chart:1407806060244373545>',
    'ranking': '<:ranking:1407806476000563210>',
    'piggybank': '<:piggybank:1407801979052232735>',
    'transfer': '<:transfer:1407809257495072829>'
}

# UI -------------------------------------------

class BankAccountView(ui.LayoutView):
    def __init__(self, account: BankAccount, user: discord.User, guild: discord.Guild | None = None, banner: BannerData | None = None):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.account = account
        self.user = user
        
        container = ui.Container()
        
        self.header = ui.TextDisplay(f"## {ICONS['piggybank']} Compte bancaire · {account.user.mention}")
        container.add_item(self.header)
    
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
        
        self.balance = ui.TextDisplay(f"{ICONS['coins']} **Solde** · ***{account.balance}{MONEY_SYMBOL}***")
        
        var_time = (datetime.now() - timedelta(days=1)).timestamp()
        var_since = account.get_variation_since(var_time)
        self.variance = ui.TextDisplay(f"{ICONS['chart']} **Variation sur 24h** · *{var_since:+d}{MONEY_SYMBOL}*")
        
        rank = account.get_rank_in_guild(guild) if guild else None
        if rank:
            self.rank = ui.TextDisplay(f"{ICONS['ranking']} **Rang sur *{guild.name}*** · *#{rank}*")
        
        self.thumb = ui.Thumbnail(media=account.user.display_avatar.url)
        
        self.top_section = ui.Section(self.balance, self.variance, accessory=self.thumb)
        if rank:
            self.top_section.add_item(self.rank)
            
        container.add_item(self.top_section)
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
        
        self.trs_title = ui.TextDisplay("### Dernières opérations")
        container.add_item(self.trs_title)
        
        operations = account.get_recent_operations(limit=5)
        if not operations:
            self.trs = ui.TextDisplay("Aucune opération récente.")
        else:
            trs_text = "\n".join(
                f"{op.delta:+d}{MONEY_SYMBOL} {op.description or 'Aucun détail'}"
                for op in operations
            )
            self.trs = ui.TextDisplay(f"```diff\n{trs_text}```")
            
        container.add_item(self.trs)
        
        if banner:
            container.add_item(ui.Separator())
            media_gallery = ui.MediaGallery()
            media_gallery.add_item(media=banner.image_url)
            container.add_item(media_gallery)
        
        self.add_item(container)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message(
                "**ERREUR** · Vous ne pouvez pas interagir avec ce menu.", 
                ephemeral=True
            )
            return False
        return True
        
class NavigationButtons(ui.ActionRow['OperationHistoryView']):
    def __init__(self):
        super().__init__()
        
    def update_buttons(self):
        if not self.view or not hasattr(self.view, 'pages'):
            return
            
        total_pages = len(self.view.pages)
        current = self.view.current_page
        
        self.first_page.disabled = (current == 0) or self.view.is_finished()
        self.previous_page.disabled = (current == 0) or self.view.is_finished()
        self.next_page.disabled = (current >= total_pages - 1) or self.view.is_finished()
        self.last_page.disabled = (current >= total_pages - 1) or self.view.is_finished()
        
        self.page_info.label = f"Page {current + 1}/{total_pages}" if total_pages > 0 else "Page 1/1"
    
    @ui.button(label='<<', style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished():
            self.view.current_page = 0
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view, allowed_mentions=discord.AllowedMentions.none())
    
    @ui.button(label='<', style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished() and self.view.current_page > 0:
            self.view.current_page -= 1
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view, allowed_mentions=discord.AllowedMentions.none())
    
    @ui.button(label='Page 1/1', style=discord.ButtonStyle.primary, disabled=True)
    async def page_info(self, interaction: discord.Interaction, button: ui.Button):
        pass
    
    @ui.button(label='>', style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished() and self.view.current_page < len(self.view.pages) - 1:
            self.view.current_page += 1
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view, allowed_mentions=discord.AllowedMentions.none())
    
    @ui.button(label='>>', style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished():
            self.view.current_page = len(self.view.pages) - 1
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view, allowed_mentions=discord.AllowedMentions.none())

class RankingView(ui.LayoutView):
    """Vue pour afficher le classement des utilisateurs par solde."""
    def __init__(self, sorted_accounts: list, user_account: BankAccount, user_rank: int, guild: discord.Guild, user: discord.User):
        super().__init__(timeout=300)
        self.sorted_accounts = sorted_accounts
        self.user_account = user_account
        self.user_rank = user_rank
        self.guild = guild
        self.user = user
        
        self._setup_layout()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message(
                "**ERREUR** · Vous ne pouvez pas interagir avec ce menu.", 
                ephemeral=True
            )
            return False
        return True
    
    def _setup_layout(self):
        """Configure la mise en page du classement."""
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f"## {ICONS['ranking']} Classement · {self.guild.name}")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Top 20
        ranking_text = "**Top 20 des plus riches :**\n"
        for i, account in enumerate(self.sorted_accounts[:20], start=1):
            # Emoji pour les podium
            if i == 1:
                emoji = "🥇"
            elif i == 2:
                emoji = "🥈" 
            elif i == 3:
                emoji = "🥉"
            else:
                emoji = f"**{i}.**"
            
            ranking_text += f"{emoji} {account.user.mention} · ***{account.balance}{MONEY_SYMBOL}***\n"
        
        ranking_display = ui.TextDisplay(ranking_text)
        container.add_item(ranking_display)
        
        
        container.add_item(ui.Separator())
        user_section_text = f"**Votre position :**\n**{self.user_rank}.** {self.user_account.user.mention} · ***{self.user_account.balance}{MONEY_SYMBOL}***"
        user_section = ui.TextDisplay(user_section_text)
        container.add_item(user_section)
        
        # Footer
        container.add_item(ui.Separator())
        footer_text = f"*Total de {len(self.sorted_accounts)} comptes sur ce serveur*"
        footer = ui.TextDisplay(footer_text)
        container.add_item(footer)
        
        self.add_item(container)

class OperationHistoryView(ui.LayoutView):
    def __init__(self, account: BankAccount, user: discord.User):
        super().__init__(timeout=300)
        self.account = account
        self.user = user
        
        operations = account.get_recent_operations(limit=200)
        self.pages = [operations[i:i + 5] for i in range(0, len(operations), 5)]
        if not self.pages:
            self.pages = [[]]
        self.current_page = 0
        
        self.build_interface()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message(
                "**ERREUR** · Vous ne pouvez pas interagir avec ce menu.", 
                ephemeral=True
            )
            return False
        return True
        
    def build_interface(self):
        self.clear_items()
        
        container = ui.Container()
        
        header = ui.TextDisplay(f"## {ICONS['robin']} Historique des opérations · {self.account.user.mention}")
        container.add_item(header)
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
        
        # Ajouter les sections d'opérations
        page_ops = self.pages[self.current_page] if self.current_page < len(self.pages) else []
        
        if not page_ops:
            no_ops = ui.TextDisplay("Aucune opération trouvée.")
            container.add_item(no_ops)
        else:
            for i, op in enumerate(page_ops):
                try:
                    # Créer une section pour chaque opération
                    timestamp_str = datetime.fromtimestamp(op.timestamp).strftime('%d/%m/%y à %H:%M')
                    desc = op.description or 'Aucun détail'
                    
                    # Titre avec montant (sans émojis)
                    if op.delta > 0:
                        op_title = ui.TextDisplay(f"### +{op.delta}{MONEY_SYMBOL}")
                    else:
                        op_title = ui.TextDisplay(f"### {op.delta}{MONEY_SYMBOL}")
                    
                    # Description et timestamp
                    op_info = ui.TextDisplay(f"**{desc}**\n-# {timestamp_str}")
                    
                    # Bouton avec l'ID (désactivé)
                    op_id_button = ui.Button(label=f"#{op.id}", style=discord.ButtonStyle.secondary, disabled=True)
                    
                    # Créer la section
                    op_section = ui.Section(op_title, op_info, accessory=op_id_button)
                    container.add_item(op_section)
                    
                    # Ajouter un séparateur après chaque opération (sauf la dernière)
                    if i < len(page_ops) - 1:
                        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
                    
                except Exception:
                    # En cas d'erreur, section simple
                    error_section = ui.Section(
                        ui.TextDisplay("### Erreur de lecture"),
                        ui.TextDisplay("Impossible de lire cette opération")
                    )
                    container.add_item(error_section)
                    
                    # Séparateur après erreur aussi
                    if i < len(page_ops) - 1:
                        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        
        self.add_item(container)
        
        if len(self.pages) > 1:
            navigation = NavigationButtons()
            self.add_item(navigation)
            navigation.update_buttons()
    
    def update_display(self):
        self.build_interface()


class TransfertView(ui.LayoutView):
    def __init__(self, sender: BankAccount, sender_op: Operation, recipient: BankAccount, recipient_op: Operation, amount: int, user: discord.User, reason: str | None = None):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.reason = reason
        self.user = user
        
        container = ui.Container()
        
        self.header = ui.TextDisplay(f"## {ICONS['transfer']} Transfert de fonds")
        container.add_item(self.header)
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
        
        sender_title = ui.TextDisplay(f"### Émetteur · {sender.user.mention}")
        sender_info_txt = f"↑ Transfert de ***{amount}{MONEY_SYMBOL}***\n**Nouveau solde** · *{sender.balance}{MONEY_SYMBOL}*"
        if reason:
            sender_info_txt += f"\n**Raison** · *{reason}*"
        sender_info = ui.TextDisplay(sender_info_txt)
        sender_op = ui.TextDisplay(f"-# Opération #{sender_op.id}")
        sender_thumb = ui.Thumbnail(media=sender.user.display_avatar.url)
        self.sender_section = ui.Section(sender_title, sender_info, sender_op, accessory=sender_thumb)
        container.add_item(self.sender_section)
        
        container.add_item(ui.Separator())
        
        recipient_title = ui.TextDisplay(f"### Bénéficiaire · {recipient.user.mention}")
        recipient_info = ui.TextDisplay(f"↓ Réception de ***{amount}{MONEY_SYMBOL}***\n**Nouveau solde** · *{recipient.balance}{MONEY_SYMBOL}*")
        recipient_op = ui.TextDisplay(f"-# Opération #{recipient_op.id}")
        recipient_thumb = ui.Thumbnail(media=recipient.user.display_avatar.url)
        self.recipient_section = ui.Section(recipient_title, recipient_info, recipient_op, accessory=recipient_thumb)
        container.add_item(self.recipient_section)
        
        self.add_item(container)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message(
                "**ERREUR** · Vous ne pouvez pas interagir avec ce menu.", 
                ephemeral=True
            )
            return False
        return True

# COG ===========================================

class Bank(commands.Cog):
    """Module de gestion de la banque et des transactions économiques."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.eco = EconomyDBManager()
        
    # Bannières de profil --------------------------------
    
    def get_user_banner(self, user: discord.User | discord.Member) -> Optional[BannerData]:
        """Récupère la bannière de profil d'un utilisateur."""
        cog: Banners = self.bot.get_cog('Banners')
        if cog:
            return cog.fetch_current_banner_data(user)
        return None
        
    # COMMANDES ------------------------------------------
    
    @app_commands.command(name='account')
    @app_commands.rename(user='utilisateur')
    async def cmd_account(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        """Affiche les informations bancaires d'un utilisateur.
        
        :param user: Autre utilisateur à afficher
        """
        user = user or interaction.user
        account = self.eco.get_account(user)
        
        if not account:
            return interaction.response.send_message(f"Aucun compte trouvé pour {user.name}.", ephemeral=True)
        
        banner = self.get_user_banner(user)
        
        view = BankAccountView(account, interaction.user, guild=interaction.guild, banner=banner)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none()
        )
        
    @app_commands.command(name='history')
    @app_commands.rename(user='utilisateur', limit='limite')
    async def cmd_history(self, interaction: discord.Interaction, user: Optional[discord.User] = None, limit: app_commands.Range[int, 1, 100] = 10):
        """Affiche l'historique des opérations d'un utilisateur.
        
        :param user: Utilisateur dont afficher l'historique (par défaut l'utilisateur de la commande)
        :param limit: Nombre d'opérations à afficher (par défaut 10, maximum 100)
        """
        user = user or interaction.user
        account = self.eco.get_account(user)
        if not account:
            return await interaction.response.send_message(f"Aucun compte trouvé pour {user.name}.", ephemeral=True)
        
        view = OperationHistoryView(account, interaction.user)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none()
        )
        
    @app_commands.command(name='ranking')
    @app_commands.guild_only()
    async def cmd_ranking(self, interaction: discord.Interaction):
        """Affiche le classement des utilisateurs par solde."""
        guild = interaction.guild
        members = [m for m in guild.members if not m.bot]
        accounts = self.eco.get_accounts(members)
        
        # Trier les comptes par solde
        sorted_accounts = sorted(accounts, key=lambda acc: acc.balance, reverse=True)
        if not sorted_accounts:
            return await interaction.response.send_message("Aucun compte trouvé dans ce serveur.", ephemeral=True)
        
        # Trouver le rang de l'utilisateur qui a lancé la commande
        user_account = self.eco.get_account(interaction.user)
        user_rank = None
        for i, account in enumerate(sorted_accounts, start=1):
            if account.user.id == interaction.user.id:
                user_rank = i
                break
        
        # Créer la vue LayoutView
        view = RankingView(sorted_accounts, user_account, user_rank, guild, interaction.user)
        await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
        
    @app_commands.command(name='transfer')
    @app_commands.guild_only()
    @app_commands.rename(user='utilisateur', amount='montant', reason='raison', notify='notifier')
    async def cmd_transfer(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1], reason: Optional[app_commands.Range[str, 1, 32]] = None, notify: bool = False):
        """Transfère de l'argent à un autre utilisateur.
    
        :param user: Utilisateur à qui transférer de l'argent
        :param amount: Montant à transférer
        :param reason: Raison du transfert (optionnel)
        :param notify: Notifier ou non l'utilisateur destinataire (par défaut désactivé)
        """
        if user.id == interaction.user.id:
            return await interaction.response.send_message("**IMPOSSIBLE** × Vous ne pouvez pas vous transférer de l'argent à vous-même.", ephemeral=True)
        
        sender = self.eco.get_account(interaction.user)
        recipient = self.eco.get_account(user)
        
        if not sender or not recipient:
            return await interaction.response.send_message("**ERREUR** × Un des comptes n'existe pas.", ephemeral=True)
        if sender.balance < amount:
            return await interaction.response.send_message("**ERREUR** × Vous n'avez pas assez d'argent pour ce transfert.", ephemeral=True)
        
        sop = sender.withdraw(amount, f"Transfert vers {user.name}" + (f" ({reason})" if reason else ""))
        rop = recipient.deposit(amount, f"Transfert de {interaction.user.name}" + (f" ({reason})" if reason else ""))
        view = TransfertView(sender, sop, recipient, rop, amount, interaction.user, reason)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none() if not notify else discord.AllowedMentions(users=[user])
        )
        
    # ADMINISTRATION ---------------------------------
    
    admin_group = app_commands.Group(name='admin', description="Commandes d'administration de la banque.", default_permissions=discord.Permissions(administrator=True))
    
    @admin_group.command(name='adjust')
    @app_commands.rename(user='utilisateur', amount='montant', reason='raison')
    async def cmd_adjust(self, interaction: discord.Interaction, user: discord.User, amount: int, reason: Optional[app_commands.Range[str, 1, 32]] = None):
        """Ajoute ou retire de l'argent à un utilisateur.
        
        :param user: Utilisateur à modifier
        :param amount: Montant à ajouter (positif) ou retirer (négatif)
        :param reason: Raison de la modification (optionnel)
        """
        account = self.eco.get_account(user)
        if not account:
            return await interaction.response.send_message(f"Aucun compte trouvé pour {user.name}.", ephemeral=True)
        if amount == 0:
            return await interaction.response.send_message("**ERREUR** × Le montant doit être différent de zéro.", ephemeral=True)
        if amount > 0:
            op = account.deposit(amount, f"Modif. par {interaction.user.name}" + (f" ({reason})" if reason else ""))
            result = f"**AJOUTÉ** · +{amount}{MONEY_SYMBOL} à {user.mention}."
        else:
            op = account.withdraw(-amount, f"Modif. par {interaction.user.name}" + (f" ({reason})" if reason else ""))
            result = f"**RETIRÉ** · -{-amount}{MONEY_SYMBOL} de {user.mention}."
        await interaction.response.send_message(
            f"{result}\n**Nouveau solde** · *{account.balance}{MONEY_SYMBOL}*",
            allowed_mentions=discord.AllowedMentions(users=[user])
        )
        # Log l'opération
        logger.info(f"i --- {interaction.user.name} a modifié le compte de {user.name}: {amount}{MONEY_SYMBOL} ({reason or 'Aucune raison'})")
        
    @admin_group.command(name='rollback')
    @app_commands.rename(user='utilisateur', operation_id='opération')
    async def cmd_rollback(self, interaction: discord.Interaction, user: discord.User, operation_id: str):
        """Annule toutes les opérations jusqu'à une opération spécifique
        
        :param user: Utilisateur dont annuler les opérations
        :param operation_id: ID de l'opération jusqu'à laquelle annuler (incluse)
        """
        if '#' in operation_id:
            operation_id = operation_id.replace('#', '')
        
        account = self.eco.get_account(user)
        if not account:
            return await interaction.response.send_message(f"Aucun compte trouvé pour {user.name}.", ephemeral=True)
        
        opes = account.rollback(operation_id)
        if not opes:
            return await interaction.response.send_message(f"Aucune opération trouvée avec l'ID `{operation_id}` pour {user.name}.", ephemeral=True)
        
        await interaction.response.send_message(
            f"**ANNULATION EFFECTUÉE** · {len(opes)} opérations annulées pour {user.mention}.\n**Nouveau solde** · *{account.balance}{MONEY_SYMBOL}*",
            allowed_mentions=discord.AllowedMentions(users=[user])
        )
        
        # Log l'opération
        logger.info(f"i --- {interaction.user.name} a annulé {len(opes)} opérations du compte de {user.name} jusqu'à l'opération #{operation_id}")
        
    @cmd_rollback.autocomplete('operation_id')
    async def autocomplete_operation_id(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Fournit des suggestions pour l'autocomplétion de l'ID d'opération."""
        user = interaction.namespace['user']
        if not user:
            return []
        
        account = self.eco.get_account(user)
        if not account:
            return []
        
        operations = account.get_recent_operations(limit=20)
        choices = [
            app_commands.Choice(name=f"#{op.id} ({op.delta:+d}{MONEY_SYMBOL})", value=str(op.id))
            for op in operations if current in str(op.id)
        ]
        return choices[:20]
        
async def setup(bot):
    await bot.add_cog(Bank(bot))
