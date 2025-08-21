import logging
import random

import discord
from discord import app_commands, ui
from discord.ext import commands

from common.economy import EconomyDBManager, BankAccount, MONEY_SYMBOL

logger = logging.getLogger('ROBIN.Casino')

ICONS = {
    'slot': '<:slot:1408041936920510484>'
}

class SlotMachineView(ui.LayoutView):
    """Vue pour la machine à sous."""
    def __init__(self, account: BankAccount, bet: int, user: discord.User):
        super().__init__(timeout=60)
        self.account = account
        self.bet = bet
        self.user = user
        self.symbols = ['🍎', '🪙', '🍇', '🍌', '🍀']
        self.wheel = ['🍀', '🍎', '🪙', '🍇', '🍌', '🍀', '🍎']
        self.result = None
        self.winnings = 0
        
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
        """Configure la mise en page initiale."""
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f'# {ICONS['slot']} Machine à sous\n## Mise : {self.bet}{MONEY_SYMBOL}')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Tableau des gains
        gains_table = ui.TextDisplay('**Tableau des gains :**\n```\n🍎🍊🍇 3x Fruits mélangés = Mise remboursée\n🍎🍎🍎 3x Fruit identique = Mise + 2x Mise\n🍀🍀🍀 3x Trèfle         = Mise + 3x Mise\n🪙🪙🪙 3x Pièce          = Mise + 5x Mise\n```\n*Vous êtes toujours remboursé de votre mise quand vous gagnez !*')
        container.add_item(gains_table)
        container.add_item(ui.Separator())
        
        # Instructions avec bouton en accessoire
        instructions = ui.TextDisplay('**Cliquez sur "Lancer" pour jouer !**')
        play_button = SlotPlayButton()
        instruction_section = ui.Section(instructions, accessory=play_button)
        container.add_item(instruction_section)
        
        self.add_item(container)
    
    def _generate_column(self, previous_center=None):
        """Génère une colonne de la machine à sous."""
        if previous_center:
            try:
                pv_index = self.wheel.index(previous_center)
                center = random.choice([
                    self.wheel[pv_index - 1], 
                    self.wheel[pv_index], 
                    self.wheel[(pv_index + 1) % len(self.wheel)]
                ])
            except (ValueError, IndexError):
                center = random.choice(self.symbols)
        else:
            center = random.choice(self.symbols)
        
        center_index = self.symbols.index(center)
        top = self.wheel[(center_index + 2) % len(self.wheel)]
        bottom = self.wheel[center_index]
        
        return top, center, bottom
    
    async def play_slot(self, interaction: discord.Interaction):
        """Lance la machine à sous."""
        # Déduire la mise
        self.account.withdraw(self.bet, "Machine à sous - mise")
        
        # Générer les colonnes
        cola = self._generate_column()
        colb = self._generate_column(cola[1])
        colc = self._generate_column(colb[1])
        
        columns = [cola, colb, colc]
        center_row = [columns[0][1], columns[1][1], columns[2][1]]
        
        # Calculer les gains
        win_type = ""
        fruits = ['🍎', '🍇', '🍌']
        
        # Vérifier si tous les symboles sont identiques
        if center_row[0] == center_row[1] == center_row[2]:
            if center_row[0] in fruits:
                self.winnings = self.bet + (self.bet * 2)  # Remboursement + 2x la mise
                win_type = "3x Fruit identique"
            elif center_row[0] == '🍀':
                self.winnings = self.bet + (self.bet * 3)  # Remboursement + 3x la mise
                win_type = "3x Trèfle"
            elif center_row[0] == '🪙':
                self.winnings = self.bet + (self.bet * 5)  # Remboursement + 5x la mise  
                win_type = "3x Pièce d'or"
        # Vérifier si tous les symboles sont des fruits (même différents)
        elif all(symbol in fruits for symbol in center_row):
            self.winnings = self.bet  # Remboursement seulement
            win_type = "3x Fruits mélangés"
        else:
            self.winnings = 0
            win_type = ""
        
        # Déposer les gains si il y en a
        if self.winnings > 0:
            self.account.deposit(self.winnings, f"Machine à sous - {win_type}")
        
        # Afficher le résultat
        await self._show_result(interaction, columns, win_type)
    
    async def _show_result(self, interaction: discord.Interaction, columns: list, win_type: str):
        """Affiche le résultat de la machine à sous."""
        self.clear_items()
        container = ui.Container()
        
        # En-tête avec résultat
        if win_type:
            header = ui.TextDisplay(f'## {ICONS['slot']} Machine à sous · {win_type}')
        else:
            header = ui.TextDisplay(f'## {ICONS['slot']} Machine à sous · Perdu')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Affichage de la machine
        slot_display = f"```\n┇{columns[0][0]}┋{columns[1][0]}┋{columns[2][0]}┇\n"
        slot_display += f"▸{columns[0][1]}▪{columns[1][1]}▪{columns[2][1]}◂\n"
        slot_display += f"┇{columns[0][2]}┋{columns[1][2]}┋{columns[2][2]}┇\n```"
        
        machine_text = ui.TextDisplay(slot_display)
        container.add_item(machine_text)
        
        # Résultats
        if self.winnings > 0:
            result_text = ui.TextDisplay(f"**Résultat** · *{win_type} !*\n**Gains** · *+{self.winnings}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        else:
            result_text = ui.TextDisplay(f"**Résultat** · *Aucune combinaison gagnante*\n**Perte** · *-{self.bet}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        container.add_item(result_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self)

class SlotPlayButton(ui.Button['SlotMachineView']):
    """Bouton pour jouer à la machine à sous."""
    def __init__(self):
        super().__init__(label="Lancer", style=discord.ButtonStyle.primary)
    
    async def callback(self, interaction: discord.Interaction):
        """Callback pour jouer."""
        await self.view.play_slot(interaction)
        self.view.stop()

class Casino(commands.GroupCog, group_name="casino", description="Mini-jeux d'argent divers et variés"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.eco = EconomyDBManager()
        self.roulette = {}
        
    @app_commands.command(name="slot")
    @app_commands.checks.cooldown(1, 120)
    @app_commands.rename(bet="mise")
    async def slot_machine(self, interaction: discord.Interaction, bet: app_commands.Range[int, 10, 100]):
        """Jouer à la machine à sous

        :param bet: Montant mis en jeu (compris entre 10 et 100)
        """
        account = self.eco.get_account(interaction.user)
        
        # Vérifier le solde
        if account.balance < bet:
            return await interaction.response.send_message(f"**SOLDE INSUFFISANT** · Vous n'avez pas assez d'argent pour miser **{bet}{MONEY_SYMBOL}**. Votre solde actuel est de ***{account.balance}{MONEY_SYMBOL}***.", ephemeral=True)
        
        # Créer la vue du jeu
        view = SlotMachineView(account, bet, interaction.user)
        await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
                
async def setup(bot):
    await bot.add_cog(Casino(bot))
