import logging
import random
from datetime import datetime, timedelta
from typing import Any, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

from common import dataio
from common.economy import EconomyDBManager, BankAccount, Operation, MONEY_SYMBOL
from common.cooldowns import command_cooldown

logger = logging.getLogger(f'ROBIN.{__name__.split(".")[-1]}')

# Configuration ==========================================

ICONS = {
    'cooking': '<:cooking:1407888355827515545>',
    'delivery': '<:delivery:1407892548923559966>',
    'pickpocket': '<:pickpocket:1407902184871301252>'
}

# Jobs ==========================================

# Livreur ---------------------------
DELIVERY_EVENTS = [
    {
        "text": "`🚴‍♂️` Livraison sans problème, le client est satisfait !",
        "label": "Classique",
        "tip_range": (15, 25)
    },
    {
        "text": "`🌧️` Il pleut, mais vous livrez quand même à temps !",
        "label": "Sous la pluie",
        "tip_range": (20, 35)
    },
    {
        "text": "`🚗` Vous évitez de justesse un embouteillage !",
        "label": "Embouteillages",
        "tip_range": (20, 30)
    },
    {
        "text": "`🍕` Le client vous donne un pourboire généreux !",
        "label": "Pourboire généreux",
        "tip_range": (30, 45)
    },
    {
        "text": "`🐕` Un chien vous poursuit, mais vous réussissez à fuir !",
        "label": "Chien en colère",
        "tip_range": (15, 30)
    },
    {
        "text": "`📱` Vous trouvez la bonne adresse du premier coup !",
        "label": "Adresse trouvée",
        "tip_range": (15, 25)
    },
    {
        "text": "`🚲` Votre vélo a un petit problème, mais vous réparez rapidement !",
        "label": "Réparation rapide",
        "tip_range": (10, 25)
    },
    {
        "text": "`🌟` Le client vous félicite pour votre rapidité !",
        "label": "Client satisfait",
        "tip_range": (30, 40)
    },
    {
        "text": "`🚦` Tous les feux sont verts sur votre trajet !",
        "label": "Feux verts",
        "tip_range": (20, 35)
    },
    {
        "text": "`📦` Vous livrez plusieurs commandes en une tournée !",
        "label": "Livraison multiple",
        "tip_range": (35, 50)
    },
    {   "text": "`🚧` Pécresse avait prévu des travaux sur votre chemin, mais vous passez à travers !",
        "label": "Chantier",
        "tip_range": (10, 25)}
]

# Pickpocket ---------------------------
PICKPOCKET_EVENTS = [
    {
        "text": "`🎯` Vous volez discrètement dans la poche d'un passant !",
        "amount_range": (9, 18)
    },
    {
        "text": "`👥` Vous bousculez quelqu'un 'accidentellement' et récupérez de la monnaie !",
        "amount_range": (7, 17)
    },
    {
        "text": "`💼` Vous trouvez un portefeuille par terre avec un peu d'argent dedans !",
        "amount_range": (7, 17)
    },
    {
        "text": "`🎪` Vous profitez de la distraction d'un spectacle de rue pour voler !",
        "amount_range": (7, 12)
    },
    {
        "text": "`☂️` Sous prétexte d'aider quelqu'un avec son parapluie, vous lui prenez des pièces !",
        "amount_range": (6, 9)
    },
    {
        "text": "`🏃‍♂️` Vous faites du jogging et 'accidentellement' heurtez quelqu'un !",
        "amount_range": (9, 18)
    },
    {
        "text": "`📱` Pendant que quelqu'un regarde son téléphone, vous lui prenez sa monnaie !",
        "amount_range": (3, 10)
    }
]

# Cuisinier --------------------------- ---------------------------
PLATS = {
    "Omelette": ["œufs", "sel", "poivre"],
    "Pizza": ["pâte", "sauce tomate", "fromage"],
    "Soupe": ["eau", "carottes", "oignons"],
    "Salade": ["laitue", "tomates"],
    "Smoothie": ["banane", "lait"],
    "Riz sauté": ["riz", "oignons", "sauce soja"],
    "Tarte salée": ["pâte", "œufs", "crème"],
    "Burger": ["pain", "steak"],
    "Crêpe sucrée": ["farine", "œufs", "lait"]
}
COMPAT_PLATS = {
    "Omelette": {
        "idéal": ["fromage", "champignons", "épinards"],
        "alternatif": ["jambon", "pommes de terre", "courgette"],
        "risqué": ["chocolat", "fraises", "thon"],
    },
    "Pizza": {
        "idéal": ["champignons", "jambon", "olives"],
        "alternatif": ["anchois", "poivrons", "poulet"],
        "risqué": ["banane", "ananas", "fraise"],
    },
    "Soupe": {
        "idéal": ["céleri", "poireaux", "pomme de terre"],
        "alternatif": ["courgette", "navet", "champignons"],
        "risqué": ["banane", "fraise", "cacao"],
    },
    "Salade": {
        "idéal": ["concombre", "oignons rouges", "huile d'olive"],
        "alternatif": ["pomme", "fromage de chèvre", "poulet"],
        "risqué": ["banane", "thon en boîte", "fraise"],
    },
    "Smoothie": {
        "idéal": ["fraise", "mangue", "kiwi"],
        "alternatif": ["pomme", "ananas", "pêche"],
        "risqué": ["tomate", "concombre", "avocat"],
    },
    "Riz sauté": {
        "idéal": ["œuf", "crevettes", "petits pois"],
        "alternatif": ["champignons", "poulet", "tofu"],
        "risqué": ["banane", "pomme", "chocolat"],
    },
    "Tarte salée": {
        "idéal": ["épinards", "poireaux", "fromage"],
        "alternatif": ["saumon", "courgette", "champignons"],
        "risqué": ["pomme", "banane", "fraise"],
    },
    "Burger": {
        "idéal": ["fromage", "salade", "tomates"],
        "alternatif": ["œuf", "champignons", "avocat"],
        "risqué": ["ananas", "pomme", "poire"],
    },
    "Crêpe sucrée": {
        "idéal": ["sucre", "chocolat", "fruits"],
        "alternatif": ["confiture", "crème chantilly", "noisettes"],
        "risqué": ["fromage", "thon", "tomate"]
    }
}

class CookGameView(ui.LayoutView):
    """Vue pour le mini-jeu de cuisine."""
    def __init__(self, account: BankAccount, plat: str, ingredients: dict, user: discord.User):
        super().__init__(timeout=60)
        self.account = account
        self.plat = plat
        self.ingredients = ingredients
        self.user = user
        self.result = None
        
        self._setup_layout()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message("Vous ne pouvez pas utiliser ce menu.", ephemeral=True)
            return False
        return True
    
    def _setup_layout(self):
        """Configure la mise en page du mini-jeu."""
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f'## {ICONS['cooking']} Cuisinez le plat\n### **Un client demande : __{self.plat}__**')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Ingrédients de base
        base_ingredients = ', '.join(PLATS[self.plat])
        ingredients_text = ui.TextDisplay(f'Ingrédients déjà présents : {base_ingredients}')
        container.add_item(ingredients_text)
        
        # Instructions
        instructions = ui.TextDisplay("**Complétez le plat en choisissant un ingrédient parmi les options ci-dessous :**")
        container.add_item(instructions)
        
        # Section des boutons d'ingrédients
        ingredient_section = IngredientSelection(self.ingredients)
        container.add_item(ingredient_section)
        
        self.add_item(container)
    
    async def on_timeout(self):
        """Appelé quand le timeout est atteint."""
        for item in self.children:
            if hasattr(item, 'children'):
                for child in item.children:
                    if isinstance(child, IngredientSelection):
                        for button in child.children:
                            button.disabled = True
        
    def calculate_tip(self, ingredient_category: str) -> int:
        """Calcule le tip basé sur la catégorie d'ingrédient choisi."""
        base_tip = 30
        
        if ingredient_category == "idéal":
            # 70% chance pour le tip maximum, 25% pour moyen, 5% pour minimum
            weights = [0.05, 0.25, 0.70]
            tips = [base_tip, base_tip * 1.5, base_tip * 2]
        elif ingredient_category == "alternatif":
            # 40% chance pour tip maximum, 40% pour moyen, 20% pour minimum
            weights = [0.20, 0.40, 0.40]
            tips = [base_tip, base_tip * 1.5, base_tip * 2]
        else:  # risqué
            # 10% chance pour tip maximum, 20% pour moyen, 70% pour minimum
            weights = [0.70, 0.20, 0.10]
            tips = [base_tip, base_tip * 1.5, base_tip * 2]
        
        return random.choices(tips, weights=weights)[0]
    
    async def show_result(self, interaction: discord.Interaction, tip: int, ingredient: str):
        """Affiche le résultat en modifiant la LayoutView."""
        # Vider le contenu actuel
        self.clear_items()
        
        container = ui.Container()
        
        # En-tête du résultat
        header = ui.TextDisplay(f'## {ICONS['cooking']} Plat terminé !\n**Vous avez réalisé : __{self.plat}__ avec *{ingredient}***')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Message basé sur le montant gagné
        if tip >= 60:
            result_msg = "*Excellent ! Le client a adoré !*"
        elif tip >= 45:
            result_msg = "*Très bien ! Un plat réussi !*"
        else:
            result_msg = "*Pas mal ! Mais le retour était un peu mitigé...*"
        
        result_text = ui.TextDisplay(result_msg)
        container.add_item(result_text)
        
        # Informations sur les gains
        earnings_text = ui.TextDisplay(f"**Pourboire gagné** · *+{tip}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        container.add_item(earnings_text)

        self.add_item(container)
        
        await interaction.response.edit_message(view=self)

class IngredientSelection(ui.ActionRow['CookGameView']):
    """Ligne d'action pour la sélection d'ingrédients."""
    def __init__(self, ingredients: dict):
        super().__init__()
        self.ingredients = ingredients
        
        # Créer un bouton pour chaque ingrédient
        for i, (ingredient, category) in enumerate(ingredients.items()):
            if i < 3:  # Limite à 3 boutons par ActionRow
                button = IngredientButton(ingredient, category)
                self.add_item(button)

class IngredientButton(ui.Button['CookGameView']):
    """Bouton pour sélectionner un ingrédient."""
    def __init__(self, ingredient: str, category: str):
        # Tous les boutons ont le même style pour ne pas révéler la catégorie
        super().__init__(label=ingredient.capitalize(), style=discord.ButtonStyle.secondary)
        self.ingredient = ingredient
        self.category = category
    
    async def callback(self, interaction: discord.Interaction):
        """Callback quand un ingrédient est sélectionné."""
        # Calculer le tip
        tip = int(self.view.calculate_tip(self.category))
        
        # Effectuer le dépôt
        self.view.account.deposit(tip, f"Travail de cuisinier - {self.view.plat}")
        
        # Modifier la LayoutView pour afficher le résultat
        await self.view.show_result(interaction, tip, self.ingredient)
        self.view.stop()

# Livreur Game View ---------------------------
class DeliveryGameView(ui.LayoutView):
    """Vue pour le mini-jeu de livraison."""
    def __init__(self, account: BankAccount, user: discord.User):
        super().__init__(timeout=30)
        self.account = account
        self.user = user
        self.event = random.choice(DELIVERY_EVENTS)
        self.tip = random.randint(self.event["tip_range"][0], self.event["tip_range"][1])
        
        self._setup_layout()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message("Vous ne pouvez pas utiliser ce menu.", ephemeral=True)
            return False
        return True
    
    def _setup_layout(self):
        """Configure la mise en page du mini-jeu."""
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f"## {ICONS['delivery']} Livraison de colis")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Instructions avec bouton en accessoire
        instructions = ui.TextDisplay('**Cliquez sur "Commencer" pour voir ce qui vous arrive !**')
        delivery_button = DeliveryButton()
        instruction_section = ui.Section(instructions, accessory=delivery_button)
        container.add_item(instruction_section)
        
        self.add_item(container)
    
    async def show_result(self, interaction: discord.Interaction):
        """Affiche le résultat de la livraison."""
        # Effectuer le dépôt
        self.account.deposit(self.tip, f"Travail de livreur - {self.event['label']}")
        
        # Vider le contenu actuel
        self.clear_items()
        
        container = ui.Container()
        
        # Résultat et description de l'événement
        header = ui.TextDisplay(f'## {ICONS['delivery']} Livraison terminée · {self.event["label"]}')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        event_text = ui.TextDisplay(f"*{self.event['text']}*")
        container.add_item(event_text)
        
        # Gains
        earnings_text = ui.TextDisplay(f"**Gains** · *+{self.tip}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        container.add_item(earnings_text)
        
        self.add_item(container)
        
        await interaction.response.edit_message(view=self)

class DeliveryButton(ui.Button['DeliveryGameView']):
    """Bouton pour commencer la livraison."""
    def __init__(self):
        super().__init__(label="Commencer", style=discord.ButtonStyle.primary)
    
    async def callback(self, interaction: discord.Interaction):
        """Callback pour démarrer la livraison."""
        await self.view.show_result(interaction)
        self.view.stop()

# Pickpocket Game View ---------------------------
class PickpocketGameView(ui.LayoutView):
    """Vue pour le mini-jeu de pickpocket."""
    def __init__(self, account: BankAccount, guild_members: list, user: discord.User):
        super().__init__(timeout=30)
        self.account = account
        self.guild_members = guild_members
        self.user = user
        self.event = random.choice(PICKPOCKET_EVENTS)
        self.amount = random.randint(self.event["amount_range"][0], self.event["amount_range"][1])
        self.target = None
        
        self._setup_layout()
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie que seul l'utilisateur qui a lancé la commande peut interagir."""
        if interaction.user != self.user:
            await interaction.response.send_message("Vous ne pouvez pas utiliser ce menu.", ephemeral=True)
            return False
        return True
    
    def _setup_layout(self):
        """Configure la mise en page du mini-jeu."""
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f"## {ICONS['pickpocket']} Activité de pickpocket")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Instructions avec bouton en accessoire
        instructions = ui.TextDisplay('**Cliquez sur "Commencer" pour voir ce qui se passe !**')
        pickpocket_button = PickpocketButton()
        instruction_section = ui.Section(instructions, accessory=pickpocket_button)
        container.add_item(instruction_section)
        
        self.add_item(container)
    
    async def show_result(self, interaction: discord.Interaction):
        """Affiche le résultat du pickpocket."""
        # Sélectionner une cible aléatoire (excluant le joueur lui-même)
        available_targets = [member for member in self.guild_members if member.id != self.account.user.id]
        
        if not available_targets:
            # Aucune cible disponible
            await self._show_no_target_result(interaction)
            return
        
        self.target = random.choice(available_targets)
        target_account = self.account.db_manager.get_account(self.target)
        
        # Vérifier si la cible a assez d'argent
        if target_account.balance >= self.amount:
            # Vol réussi
            target_account.withdraw(self.amount, f"Volé par {self.account.user.display_name}")
            self.account.deposit(self.amount, f"Pickpocket sur {self.target.display_name}")
            await self._show_success_result(interaction)
        else:
            # Cible trop pauvre, vol partiel ou échec
            available_amount = target_account.balance
            if available_amount > 0:
                target_account.withdraw(available_amount, f"Volé par {self.account.user.display_name}")
                self.account.deposit(available_amount, f"Pickpocket partiel sur {self.target.display_name}")
                await self._show_partial_result(interaction, available_amount)
            else:
                # Échec total
                await self._show_failure_result(interaction)
    
    async def _show_success_result(self, interaction: discord.Interaction):
        """Affiche le résultat d'un vol réussi."""
        self.clear_items()
        container = ui.Container()
        
        header = ui.TextDisplay(f'## {ICONS["pickpocket"]} Opération réussie')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        event_text = ui.TextDisplay(f"*{self.event['text']}*")
        container.add_item(event_text)
        
        result_text = ui.TextDisplay(f"**Cible** · *{self.target.mention}*\n**Montant volé** · *+{self.amount}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        container.add_item(result_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self, allowed_mentions=discord.AllowedMentions.none())
    
    async def _show_partial_result(self, interaction: discord.Interaction, stolen: int):
        """Affiche le résultat d'un vol partiel."""
        self.clear_items()
        container = ui.Container()
        
        header = ui.TextDisplay(f'## {ICONS["pickpocket"]} Vol partiel')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        event_text = ui.TextDisplay("*Vous tentez votre coup mais la cible n'avait pas beaucoup d'argent...*")
        container.add_item(event_text)
        
        result_text = ui.TextDisplay(f"**Cible** · *{self.target.mention}*\n**Montant volé** · *+{stolen}{MONEY_SYMBOL}*\n**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***")
        container.add_item(result_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self, allowed_mentions=discord.AllowedMentions.none())
    
    async def _show_failure_result(self, interaction: discord.Interaction):
        """Affiche le résultat d'un échec."""
        self.clear_items()
        container = ui.Container()
        
        header = ui.TextDisplay(f"## {ICONS["pickpocket"]} Échec de l'opération")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        event_text = ui.TextDisplay("*Vous tentez votre coup mais la cible n'avait absolument rien sur elle !*")
        container.add_item(event_text)
        
        result_text = ui.TextDisplay(f"**Cible** · *{self.target.mention}*\n**Résultat** · *Aucun gain*")
        container.add_item(result_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self, allowed_mentions=discord.AllowedMentions.none())
    
    async def _show_no_target_result(self, interaction: discord.Interaction):
        """Affiche le résultat quand aucune cible n'est disponible."""
        self.clear_items()
        container = ui.Container()
        
        header = ui.TextDisplay(f'## {ICONS["pickpocket"]} Pas de cible')
        container.add_item(header)
        container.add_item(ui.Separator())
        
        event_text = ui.TextDisplay("*Il n'y a personne d'autre sur ce serveur à voler !*")
        container.add_item(event_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self)

class PickpocketButton(ui.Button['PickpocketGameView']):
    """Bouton pour commencer le pickpocket."""
    def __init__(self):
        super().__init__(label="Commencer", style=discord.ButtonStyle.danger)
    
    async def callback(self, interaction: discord.Interaction):
        """Callback pour démarrer le pickpocket."""
        await self.view.show_result(interaction)
        self.view.stop()
        
# COG ===========================================

class Jobs(commands.Cog):
    """Système de jobs (avec mini-jeux) pour gagner de l'argent."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = dataio.get_instance(self)
        self.eco = EconomyDBManager()
        self.job_cooldowns = {}  # Dictionnaire pour stocker les cooldowns des utilisateurs
    
    @app_commands.command(name="work")
    @app_commands.rename(work_type="travail")
    @app_commands.choices(
        work_type=[
            app_commands.Choice(name="Livreur (+ Aléatoire)", value="livreur"),
            app_commands.Choice(name="Cuisinier (+ Gains)", value="cuisinier"),
            app_commands.Choice(name="Pickpocket (+ Social)", value="pickpocket"),
        ])
    @command_cooldown(10800, cooldown_name="Travail")  # Cooldown de 3 heures
    async def cmd_job(self, interaction: discord.Interaction, work_type: str):
        """Effectuer une tâche pour gagner de l'argent
        
        :param work_type: Travail à effectuer"""
        
        if work_type.lower() == "livreur":
            account = self.eco.get_account(interaction.user)
            view = DeliveryGameView(account, interaction.user)
            await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
            
        elif work_type.lower() == "cuisinier":
            account = self.eco.get_account(interaction.user)
        
            # Choisir un plat aléatoirement
            plat = random.choice(list(PLATS.keys()))
            
            # Choisir 3 ingrédients aléatoirement (un de chaque catégorie)
            plat_compat = COMPAT_PLATS[plat]
            ingredients = {}
            
            for category in ["idéal", "alternatif", "risqué"]:
                ingredient = random.choice(plat_compat[category])
                ingredients[ingredient] = category
            
            # Créer la vue du mini-jeu
            view = CookGameView(account, plat, ingredients, interaction.user)
            
            await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
            
        elif work_type.lower() == "pickpocket":
            account = self.eco.get_account(interaction.user)
            
            # Récupérer les membres du serveur (excluant les bots)
            guild_members = [member for member in interaction.guild.members if not member.bot]
            
            # Créer la vue du mini-jeu
            view = PickpocketGameView(account, guild_members, interaction.user)
            
            await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
            
        else:
            await interaction.response.send_message(
                "**ERREUR** · Ce type de travail n'est pas encore implémenté.",
                ephemeral=True
            )
            await interaction.response.send_message(
                "**ERREUR** · Ce type de travail n'est pas encore implémenté.",
                ephemeral=True
            )
        
async def setup(bot):
    await bot.add_cog(Jobs(bot))
