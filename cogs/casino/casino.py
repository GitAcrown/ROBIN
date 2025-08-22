import logging
import random

import discord
from discord import app_commands, ui
from discord.ext import commands

from common.economy import EconomyDBManager, BankAccount, MONEY_SYMBOL
from common.cooldowns import command_cooldown

logger = logging.getLogger('ROBIN.Casino')

ICONS = {
    'slot': '<:slot:1408041936920510484>',
    'roulette': '<:roulette:1408222142771757279>'
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
        gains_table = ui.TextDisplay('**Tableau des gains :**\n```\nFruits mélangés   1x\nFruit identique   3x\nTrèfle            4x\nPièce d\'or        6x\n```\n*Gains = multiplicateur × votre mise*')
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
            gain_amount = self.winnings - self.bet
            result_text = ui.TextDisplay(f"**Résultat** · *{win_type} !*\n**Gains nets** · *+{gain_amount}{MONEY_SYMBOL}* (total reçu: +{self.winnings}{MONEY_SYMBOL})\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
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

class RouletteView(ui.LayoutView):
    """Vue pour la roulette."""
    def __init__(self, account: BankAccount, bet: int, bet_type: str, bet_value: str, user: discord.User):
        super().__init__(timeout=60)
        self.account = account
        self.bet = bet
        self.bet_type = bet_type
        self.bet_value = bet_value
        self.user = user
        self.result_number = None
        self.result_color = None
        self.winnings = 0
        
        # Définition des numéros de la roulette avec leurs couleurs
        self.red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        self.black_numbers = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
        
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
        header = ui.TextDisplay(f'# {ICONS['roulette']} Roulette\n## Mise : {self.bet}{MONEY_SYMBOL} sur {self._format_bet()}')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Tableau des gains
        gains_table = ui.TextDisplay('**Tableau des gains :**\n```\nRouge/Noir        +1x (total 2x)\nPair/Impair       +1x (total 2x)\nDouzaines         +2x (total 3x)\nNuméro exact     +35x (total 36x)\n```\n*Gains nets + remboursement de votre mise*')
        container.add_item(gains_table)
        container.add_item(ui.Separator())
        
        # Instructions avec bouton en accessoire
        instructions = ui.TextDisplay('**Prêt à tenter votre chance ? Cliquez pour lancer la bille !**')
        spin_button = RouletteSpinButton()
        instruction_section = ui.Section(instructions, accessory=spin_button)
        container.add_item(instruction_section)
        
        self.add_item(container)
    
    def _format_bet(self):
        """Formate l'affichage du pari."""
        if self.bet_type == "couleur":
            color_display = "ROUGE" if self.bet_value == "rouge" else "NOIR"
            return f"**{color_display}**"
        elif self.bet_type == "parite":
            parity_display = "PAIR" if self.bet_value == "pair" else "IMPAIR"
            return f"**{parity_display}**"
        elif self.bet_type == "douzaine":
            if self.bet_value == "1":
                return "**PREMIÈRE DOUZAINE** (1-12)"
            elif self.bet_value == "2":
                return "**DEUXIÈME DOUZAINE** (13-24)"
            else:
                return "**TROISIÈME DOUZAINE** (25-36)"
        elif self.bet_type == "numero":
            if self.bet_value == "0":
                return f"**NUMÉRO ZÉRO**"
            else:
                return f"**NUMÉRO {self.bet_value}**"
        return self.bet_value
    
    def _get_color(self, number: int) -> str:
        """Retourne la couleur d'un numéro."""
        if number == 0:
            return "vert"
        elif number in self.red_numbers:
            return "rouge"
        else:
            return "noir"
    
    def _get_color_emoji(self, color: str) -> str:
        """Retourne l'emoji correspondant à la couleur."""
        if color == "rouge":
            return "🔴"
        elif color == "noir":
            return "⚫"
        else:
            return "🟢"
    
    async def spin_roulette(self, interaction: discord.Interaction):
        """Lance la roulette."""
        # Déduire la mise
        self.account.withdraw(self.bet, "Roulette - mise")
        
        # Générer le numéro gagnant (0-36)
        self.result_number = random.randint(0, 36)
        self.result_color = self._get_color(self.result_number)
        
        # Calculer les gains
        win_type = ""
        multiplier = 0
        
        if self.bet_type == "couleur":
            if self.bet_value == self.result_color and self.result_number != 0:
                multiplier = 1  # 2x au total (mise + 1x mise)
                win_type = f"{self.bet_value.capitalize()}"
            # Le zéro fait perdre les paris couleur
        
        elif self.bet_type == "parite":
            if self.result_number == 0:
                pass  # Le zéro fait perdre les paris pair/impair
            elif self.bet_value == "pair" and self.result_number % 2 == 0:
                multiplier = 1  # 2x au total (mise + 1x mise)
                win_type = "Pair"
            elif self.bet_value == "impair" and self.result_number % 2 == 1:
                multiplier = 1  # 2x au total (mise + 1x mise)
                win_type = "Impair"
        
        elif self.bet_type == "douzaine":
            # Le zéro fait perdre les paris douzaine
            if self.result_number != 0:
                if self.bet_value == "1" and 1 <= self.result_number <= 12:
                    multiplier = 2  # 3x au total (mise + 2x mise)
                    win_type = "Première douzaine"
                elif self.bet_value == "2" and 13 <= self.result_number <= 24:
                    multiplier = 2  # 3x au total (mise + 2x mise)
                    win_type = "Deuxième douzaine"
                elif self.bet_value == "3" and 25 <= self.result_number <= 36:
                    multiplier = 2  # 3x au total (mise + 2x mise)
                    win_type = "Troisième douzaine"
        
        elif self.bet_type == "numero":
            if int(self.bet_value) == self.result_number:
                multiplier = 35  # 36x au total (mise + 35x mise)
                win_type = f"Numéro {self.result_number}"
        
        # Calculer les gains (remboursement + gains)
        if multiplier > 0:
            self.winnings = self.bet + (self.bet * multiplier)
            self.account.deposit(self.winnings, f"Roulette - {win_type}")
        else:
            self.winnings = 0
        
        # Afficher le résultat
        await self._show_result(interaction, win_type)
    
    async def _show_result(self, interaction: discord.Interaction, win_type: str):
        """Affiche le résultat de la roulette."""
        self.clear_items()
        container = ui.Container()
        
        # En-tête avec résultat
        color_emoji = self._get_color_emoji(self.result_color)
        if win_type:
            header = ui.TextDisplay(f'## {ICONS['roulette']} Roulette · {win_type}')
        else:
            header = ui.TextDisplay(f'## {ICONS['roulette']} Roulette · Perdu')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Affichage du résultat avec style amélioré
        color_emoji = self._get_color_emoji(self.result_color)
        result_display = f"## {color_emoji} **{self.result_number}** {color_emoji}"
        result_text = ui.TextDisplay(result_display)
        container.add_item(result_text)
        
        # Informations détaillées avec style amélioré
        if self.result_number == 0:
            number_info = "**Zéro** · *Vert - La banque gagne (tous les paris simples perdent)*"
        else:
            parity = "Pair" if self.result_number % 2 == 0 else "Impair"
            if 1 <= self.result_number <= 12:
                dozen = "1ère douzaine"
            elif 13 <= self.result_number <= 24:
                dozen = "2ème douzaine"
            else:
                dozen = "3ème douzaine"
            color_text = "Rouge" if self.result_color == "rouge" else "Noir"
            number_info = f"**{self.result_number}** · *{color_text}, {parity}, {dozen}*"
        
        container.add_item(ui.TextDisplay(number_info))
        container.add_item(ui.Separator())
        
        # Résultats financiers avec style amélioré
        if self.winnings > 0:
            gain_amount = self.winnings - self.bet
            result_text = ui.TextDisplay(f"**Félicitations !** · *{win_type}*\n**Gains nets** · *+{gain_amount}{MONEY_SYMBOL}* (total reçu: +{self.winnings}{MONEY_SYMBOL})\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        else:
            result_text = ui.TextDisplay(f"**Pas de chance** · *Aucune combinaison gagnante*\n**Perte** · *-{self.bet}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        container.add_item(result_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self)

class RouletteSpinButton(ui.Button['RouletteView']):
    """Bouton pour lancer la roulette."""
    def __init__(self):
        super().__init__(label="Lancer la bille", style=discord.ButtonStyle.primary)
    
    async def callback(self, interaction: discord.Interaction):
        """Callback pour lancer la roulette."""
        await self.view.spin_roulette(interaction)
        self.view.stop()

class Casino(commands.GroupCog, group_name="casino", description="Mini-jeux d'argent divers et variés"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.eco = EconomyDBManager()
        self.roulette = {}
    
    async def bet_value_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplétion pour bet_value."""
        choices = [
            # Couleurs
            app_commands.Choice(name="Rouge", value="rouge"),
            app_commands.Choice(name="Noir", value="noir"),
            # Parité
            app_commands.Choice(name="Pair", value="pair"),
            app_commands.Choice(name="Impair", value="impair"),
            # Douzaines (utiliser des valeurs distinctes)
            app_commands.Choice(name="Première douzaine (1-12)", value="douzaine1"),
            app_commands.Choice(name="Deuxième douzaine (13-24)", value="douzaine2"),
            app_commands.Choice(name="Troisième douzaine (25-36)", value="douzaine3"),
            # Numéros populaires
            app_commands.Choice(name="Numéro 0 (Zéro)", value="0"),
            app_commands.Choice(name="Numéro 1", value="1"),
            app_commands.Choice(name="Numéro 2", value="2"),
            app_commands.Choice(name="Numéro 3", value="3"),
            app_commands.Choice(name="Numéro 7", value="7"),
            app_commands.Choice(name="Numéro 17", value="17"),
            app_commands.Choice(name="Numéro 23", value="23"),
            app_commands.Choice(name="Numéro 32", value="32")
        ]
        
        # Filtrer selon ce que tape l'utilisateur
        if current:
            current_lower = current.lower()
            filtered_choices = []
            
            # Si c'est un nombre, ajouter ce numéro en premier (seulement s'il n'existe pas déjà)
            if current.isdigit():
                try:
                    num = int(current)
                    if 0 <= num <= 36:
                        # Vérifier si ce numéro n'est pas déjà dans les choix existants
                        existing_values = [choice.value for choice in choices]
                        if current not in existing_values:
                            filtered_choices.append(app_commands.Choice(name=f"Numéro {current}", value=current))
                except ValueError:
                    pass
            
            # Ajouter les choix qui matchent
            for choice in choices:
                if (current_lower in choice.name.lower() or 
                    current_lower in choice.value.lower()):
                    filtered_choices.append(choice)
            
            return filtered_choices[:25]
        
        return choices[:25]
        
    @app_commands.command(name="slot")
    @app_commands.rename(bet="mise")
    @command_cooldown(120, cooldown_name="slot")
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

    @app_commands.command(name="roulette")
    @app_commands.rename(bet="mise", bet_value="valeur")
    @app_commands.autocomplete(bet_value=bet_value_autocomplete)
    @command_cooldown(120, cooldown_name="roulette")
    async def cmd_roulette(self, interaction: discord.Interaction, bet: app_commands.Range[int, 20, 200], bet_value: str):
        """Jouer à la roulette européenne
        
        :param bet: Montant mis en jeu (compris entre 20 et 200)
        :param bet_value: Valeur du pari (rouge/noir, pair/impair, douzaine1-3, numéros 0-36)
        """
        account = self.eco.get_account(interaction.user)
        
        # Vérifier le solde
        if account.balance < bet:
            return await interaction.response.send_message(f"**SOLDE INSUFFISANT** · Vous n'avez pas assez d'argent pour miser **{bet}{MONEY_SYMBOL}**. Votre solde actuel est de ***{account.balance}{MONEY_SYMBOL}***.", ephemeral=True)
        
        # Déterminer le type de pari automatiquement
        bet_value = bet_value.lower()
        bet_type = None
        
        if bet_value in ["rouge", "noir"]:
            bet_type = "couleur"
        elif bet_value in ["pair", "impair"]:
            bet_type = "parite"
        elif bet_value in ["douzaine1", "douzaine2", "douzaine3"]:
            bet_type = "douzaine"
            # Convertir les valeurs de douzaine pour le traitement
            if bet_value == "douzaine1":
                bet_value = "1"
            elif bet_value == "douzaine2":
                bet_value = "2"
            elif bet_value == "douzaine3":
                bet_value = "3"
        else:
            # Vérifier si c'est un numéro
            try:
                num = int(bet_value)
                if 0 <= num <= 36:
                    bet_type = "numero"
                else:
                    raise ValueError
            except ValueError:
                return await interaction.response.send_message(
                    "**ERREUR** · Valeur de pari invalide. Utilisez : `rouge`, `noir`, `pair`, `impair`, `douzaine1-3` ou `0-36` (numéros).", 
                    ephemeral=True
                )
        
        # Créer la vue du jeu
        view = RouletteView(account, bet, bet_type, bet_value, interaction.user)
        await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
                
async def setup(bot):
    await bot.add_cog(Casino(bot))
