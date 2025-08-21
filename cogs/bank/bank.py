import logging
import yaml
from datetime import datetime, timedelta
from typing import Any, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

from common import dataio
from common.economy import EconomyDBManager, BankAccount, Operation, MONEY_SYMBOL

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
    def __init__(self, account: BankAccount, guild: discord.Guild | None = None):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.account = account
        
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
        self.add_item(container)
        
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
            await interaction.response.edit_message(view=self.view)
    
    @ui.button(label='<', style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished() and self.view.current_page > 0:
            self.view.current_page -= 1
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view)
    
    @ui.button(label='Page 1/1', style=discord.ButtonStyle.primary, disabled=True)
    async def page_info(self, interaction: discord.Interaction, button: ui.Button):
        pass
    
    @ui.button(label='>', style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished() and self.view.current_page < len(self.view.pages) - 1:
            self.view.current_page += 1
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view)
    
    @ui.button(label='>>', style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: ui.Button):
        if self.view and not self.view.is_finished():
            self.view.current_page = len(self.view.pages) - 1
            self.view.update_display()
            self.update_buttons()
            await interaction.response.edit_message(view=self.view)

class OperationHistoryView(ui.LayoutView):
    def __init__(self, account: BankAccount):
        super().__init__(timeout=300)
        self.account = account
        
        operations = account.get_recent_operations(limit=200)
        self.pages = [operations[i:i + 5] for i in range(0, len(operations), 5)]
        if not self.pages:
            self.pages = [[]]
        self.current_page = 0
        
        self.build_interface()
        
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
    def __init__(self, sender: BankAccount, sender_op: Operation, recipient: BankAccount, recipient_op: Operation, amount: int, reason: str | None = None):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.reason = reason
        
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

# COG ===========================================

class Bank(commands.Cog):
    """Module de gestion de la banque et des transactions économiques."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.eco = EconomyDBManager()
        
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
        
        view = BankAccountView(account, guild=interaction.guild)
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
        
        view = OperationHistoryView(account)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none()
        )
        
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
        view = TransfertView(sender, sop, recipient, rop, amount, reason)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none() if not notify else discord.AllowedMentions(users=[user])
        )
        
    # ADMINISTRATION ---------------------------------
    
    @app_commands.command(name='adjust')
    @app_commands.checks.has_permissions(administrator=True)
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
        
async def setup(bot):
    await bot.add_cog(Bank(bot))
