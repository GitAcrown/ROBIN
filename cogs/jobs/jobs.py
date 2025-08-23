import logging
import random
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

from common import dataio
from common.economy import EconomyDBManager, BankAccount, Operation, MONEY_SYMBOL
from common.cooldowns import check_cooldown_state, set_cooldown

logger = logging.getLogger(f'ROBIN.{__name__.split(".")[-1]}')

# Configuration ==========================================

ICONS = {
    'cooking': '<:cooking:1407888355827515545>',
    'delivery': '<:delivery:1407892548923559966>',
    'pickpocket': '<:pickpocket:1407902184871301252>',
    'hacker': '<:hacking:1408485940485292103>'
}

COOLDOWNS = {
    'cooking': 3600 * 1,      # 1h - Gains moyens/élevés
    'delivery': 3600 * 0.75,  # 45m - Gains moyens
    'pickpocket': 3600 * 0.5, # 30min - Gains faibles
    'hacker': 3600 * 1        # 1h - Gains élevés mais difficile
}

# Fonctions utilitaires ==========================================

def normalize_string(text: str) -> str:
    """Retire les accents et caractères spéciaux d'une chaîne."""
    # Convertir en majuscules
    text = text.upper().strip()
    # Retirer les accents
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    return text

def format_next_work_time(work_type: str):
    """Affiche le temps jusqu'au prochain travail disponible."""
    cooldown = COOLDOWNS.get(work_type)
    if not cooldown:
        return ""
    
    return f"-# Vous pourrez retravailler dans **{int(cooldown // 60)} minutes**"

# Jobs ==========================================

# Livreur ---------------------------
DELIVERY_EVENTS = [
    {
        "text": "`🚴‍♂️` Livraison sans problème, le client est satisfait !",
        "label": "Classique",
        "tip_range": (12, 20)
    },
    {
        "text": "`⛈️` Il pleut, mais vous arrivez à l'heure !",
        "label": "Pluie",
        "tip_range": (15, 25)
    },
    {
        "text": "`🚧` Vous évitez les travaux en prenant un raccourci !",
        "label": "Détour",
        "tip_range": (15, 22)
    },
    {
        "text": "`📞` Le client vous appelle pour changer l'adresse !",
        "label": "Changement",
        "tip_range": (20, 30)
    },
    {
        "text": "`🐕` Un chien vous poursuit, mais vous réussissez à fuir !",
        "label": "Chien en colère",
        "tip_range": (10, 20)
    },
    {
        "text": "`📱` Vous trouvez la bonne adresse du premier coup !",
        "label": "Adresse trouvée",
        "tip_range": (12, 18)
    },
    {
        "text": "`🚲` Votre vélo a un petit problème, mais vous réparez rapidement !",
        "label": "Réparation rapide",
        "tip_range": (8, 18)
    },
    {
        "text": "`🌟` Le client vous félicite pour votre rapidité !",
        "label": "Client satisfait",
        "tip_range": (22, 28)
    },
    {
        "text": "`🚦` Tous les feux sont verts sur votre trajet !",
        "label": "Feux verts",
        "tip_range": (15, 25)
    },
    {
        "text": "`📦` Vous livrez plusieurs commandes en une tournée !",
        "label": "Livraison multiple",
        "tip_range": (25, 35)
    },
    {
        "text": "`🚧` Pécresse avait prévu des travaux sur votre chemin, mais vous passez à travers !",
        "label": "Chantier",
        "tip_range": (8, 18)
    }
]

# Pickpocket ---------------------------
PICKPOCKET_EVENTS = [
    {
        "text": "`🎯` Vous volez discrètement dans la poche d'un passant !",
        "amount_range": (5, 12)
    },
    {
        "text": "`👥` Vous bousculez quelqu'un 'accidentellement' et récupérez de la monnaie !",
        "amount_range": (4, 10)
    },
    {
        "text": "`💼` Vous trouvez un portefeuille par terre avec un peu d'argent dedans !",
        "amount_range": (4, 10)
    },
    {
        "text": "`🎪` Vous profitez de la distraction d'un spectacle de rue pour voler !",
        "amount_range": (4, 8)
    },
    {
        "text": "`☂️` Sous prétexte d'aider quelqu'un avec son parapluie, vous lui prenez des pièces !",
        "amount_range": (3, 6)
    },
    {
        "text": "`🏃‍♂️` Vous faites du jogging et 'accidentellement' heurtez quelqu'un !",
        "amount_range": (5, 12)
    },
    {
        "text": "`📱` Pendant que quelqu'un regarde son téléphone, vous lui prenez sa monnaie !",
        "amount_range": (2, 7)
    }
]

# Hacker ---------------------------
HACKER_SEQUENCES = [
    # Culture générale
    {"code": "BAGUETTE", "hint": "[France] Pain traditionnel français", "reward": 28},
    {"code": "MINECRAFT", "hint": "[Jeu vidéo] Jeu de construction en blocs", "reward": 30},
    {"code": "NAPOLEON", "hint": "[Histoire] Empereur français célèbre", "reward": 32},
    {"code": "CROISSANT", "hint": "[Nourriture] Viennoiserie française", "reward": 30},
    {"code": "POKEMON", "hint": "[Culture pop] Attrapez-les tous !", "reward": 28},
    {"code": "DRACAUFEU", "hint": "[Jeu vidéo] Dragon de type feu et vol", "reward": 35},
    {"code": "NUTELLA", "hint": "[Marque] Pâte à tartiner", "reward": 26},
    {"code": "RICKROLL", "hint": "[Internet] Piège musical célèbre (EN)", "reward": 38},
    
    # Informatique
    {"code": "FIREWALL", "hint": "[Informatique] Protection informatique (EN)", "reward": 35},
    {"code": "BACKDOOR", "hint": "[Informatique] Accès secret (EN)", "reward": 38},
    {"code": "MALWARE", "hint": "[Informatique] Logiciel malveillant (EN)", "reward": 32},
    {"code": "PHISHING", "hint": "[Informatique] Hameçonnage par email (EN)", "reward": 36},
    {"code": "OVERFLOW", "hint": "[Informatique] Dépassement de mémoire (EN)", "reward": 42},
    {"code": "KEYLOGGER", "hint": "[Informatique] Surveillant de frappe (EN)", "reward": 45},
    {"code": "ROOTKIT", "hint": "[Informatique] Outil d'accès root caché (EN)", "reward": 48},
    {"code": "SPYWARE", "hint": "[Informatique] Logiciel espion (EN)", "reward": 40},
    {"code": "B64DECODE", "hint": "[Informatique] Encodage classique web (EN)", "reward": 50},
    {"code": "SQLINJECTION", "hint": "[Informatique] Attaque de base de données (EN)", "reward": 55},
    {"code": "BRUTEFORCE", "hint": "[Informatique] Méthode de cassage par force (EN)", "reward": 52},
    {"code": "ZERODAY", "hint": "[Informatique] Faille inédite et inconnue (EN)", "reward": 58},
    {"code": "RANSOMWARE", "hint": "[Informatique] Logiciel de rançon (EN)", "reward": 54},
    {"code": "CRYPTOCURRENCY", "hint": "[Informatique] Monnaie numérique décentralisée (EN)", "reward": 65},
    {"code": "BLOCKCHAIN", "hint": "[Tech] Technologie de chaîne de blocs (EN)", "reward": 62},
    {"code": "CYBERSECURITY", "hint": "[Informatique] Sécurité informatique (EN)", "reward": 68},
    {"code": "PENETRATION", "hint": "[Informatique] Test d'intrusion", "reward": 60},
    {"code": "VULNERABILITY", "hint": "[Informatique] Faille de sécurité (EN)", "reward": 65},
    {"code": "AUTHENTICATION", "hint": "[Informatique] Processus de vérification (EN)", "reward": 70},
    {"code": "OBFUSCATION", "hint": "[Informatique] Technique de masquage (EN)", "reward": 58},
    {"code": "STEGANOGRAPHIE", "hint": "[Informatique] Art de cacher des données", "reward": 72},
    {"code": "BOTNET", "hint": "[Informatique] Réseau de machines infectées (EN)", "reward": 45},
    {"code": "EXPLOIT", "hint": "[Informatique] Faille à exploiter (EN)", "reward": 42},
    {"code": "PAYLOAD", "hint": "[Informatique] Charge utile malveillante (EN)", "reward": 48}
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
    },
    "Crêpe salée": {
        "idéal": ["jambon", "fromage", "œuf"],
        "alternatif": ["champignons", "épinards", "poulet"],
        "risqué": ["chocolat", "banane", "fraise"]
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
        base_tip = 22
        
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
        
        container.add_item(ui.Separator())
        
        # Temps jusqu'au prochain travail
        next_work_text = ui.TextDisplay(format_next_work_time('cooking'))
        container.add_item(next_work_text)

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
        
        container.add_item(ui.Separator())
        
        # Temps jusqu'au prochain travail
        next_work_text = ui.TextDisplay(format_next_work_time('delivery'))
        container.add_item(next_work_text)
        
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
        
        container.add_item(ui.Separator())
        
        # Temps jusqu'au prochain travail
        next_work_text = ui.TextDisplay(format_next_work_time('pickpocket'))
        container.add_item(next_work_text)
        
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
        
        container.add_item(ui.Separator())
        
        # Temps jusqu'au prochain travail
        next_work_text = ui.TextDisplay(format_next_work_time('pickpocket'))
        container.add_item(next_work_text)
        
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
        
        container.add_item(ui.Separator())
        
        # Temps jusqu'au prochain travail
        next_work_text = ui.TextDisplay(format_next_work_time('pickpocket'))
        container.add_item(next_work_text)
        
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

# Hacker Game View ---------------------------
class HackerGameView(ui.LayoutView):
    """Vue pour le mini-jeu de hacking avec déchiffrage de code."""
    def __init__(self, account: BankAccount, user: discord.User):
        super().__init__(timeout=120)  # 2 minutes pour résoudre
        self.account = account
        self.user = user
        self.sequence_data = random.choice(HACKER_SEQUENCES)
        self.solved = False
        
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
        header = ui.TextDisplay(f"## {ICONS['hacker']} Piratage de système")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        # Informations sur la mission
        mission_text = ui.TextDisplay(
            f"**Récompense** · *{self.sequence_data['reward']}{MONEY_SYMBOL}*\n"
            f"**Indice** · *{self.sequence_data['hint']}*"
        )
        container.add_item(mission_text)
        
        # Code à deviner (masqué)
        code_length = len(self.sequence_data["code"])
        masked_code = "▪" * code_length
        code_text = ui.TextDisplay(f"### Mot de passe à décrypter : `{masked_code}` ({code_length} lettres)")
        container.add_item(code_text)
        
        # Input modal trigger
        hack_button = HackAttemptButton()
        button_section = ui.Section(
            ui.TextDisplay("**Entrez le mot de passe que vous pensez avoir trouvé :**"),
            accessory=hack_button
        )
        container.add_item(button_section)
        
        self.add_item(container)
    
    async def attempt_hack(self, interaction: discord.Interaction, guess: str):
        """Traite une tentative de piratage."""
        guess_normalized = normalize_string(guess)
        code_normalized = normalize_string(self.sequence_data["code"])
        
        # Vider le contenu actuel
        self.clear_items()
        container = ui.Container()
        
        # En-tête
        header = ui.TextDisplay(f"## {ICONS['hacker']} Piratage de système")
        container.add_item(header)
        container.add_item(ui.Separator())
        
        if guess_normalized == code_normalized:
            # Réussite !
            self.solved = True
            
            # Affichage du succès
            success_text = ui.TextDisplay("**Excellent !** Vous avez décrypté le mot de passe !")
            container.add_item(success_text)
            
            code_text = ui.TextDisplay(f"### Mot de passe décrypté : `{self.sequence_data['code']}` ✅")
            container.add_item(code_text)
            
            # Récompense
            reward = self.sequence_data["reward"]
            self.account.deposit(reward, f"Hacking réussi - {self.sequence_data['code']}")
            
            container.add_item(ui.Separator())
            success_reward = ui.TextDisplay(
                f"**Mission accomplie !**\n"
                f"**Récompense** · *+{reward}{MONEY_SYMBOL}*\n"
                f"**Nouveau solde** · ***{self.account.balance}{MONEY_SYMBOL}***"
            )
            container.add_item(success_reward)
            
            container.add_item(ui.Separator())
            
            # Temps jusqu'au prochain travail
            next_work_text = ui.TextDisplay(format_next_work_time('hacker'))
            container.add_item(next_work_text)
        else:
            # Échec
            failure_text = ui.TextDisplay("**Mot de passe incorrect !** Tentative échouée.")
            container.add_item(failure_text)
            
            container.add_item(ui.Separator())
            failure_info = ui.TextDisplay(
                f"**Piratage échoué !**\n"
                f"*Le mot de passe n'est pas déchiffré...*\n"
                f"**Aucune récompense**"
            )
            container.add_item(failure_info)
            
            container.add_item(ui.Separator())
            
            # Temps jusqu'au prochain travail
            next_work_text = ui.TextDisplay(format_next_work_time('hacker'))
            container.add_item(next_work_text)
        
        self.add_item(container)
        await interaction.response.edit_message(view=self)
        self.stop()

class HackAttemptButton(ui.Button['HackerGameView']):
    """Bouton pour tenter de déchiffrer le code."""
    def __init__(self):
        super().__init__(label="Entrer le mot de passe", style=discord.ButtonStyle.primary)
    
    async def callback(self, interaction: discord.Interaction):
        """Ouvre un modal pour entrer la tentative."""
        modal = HackModal(self.view)
        await interaction.response.send_modal(modal)

class HackModal(ui.Modal):
    """Modal pour entrer le mot de passe."""
    def __init__(self, game_view: HackerGameView):
        super().__init__(title="Décryptage du mot de passe")
        self.game_view = game_view
    
    code_input = ui.TextInput(
        label="Votre tentative",
        placeholder="Entrez le mot de passe que vous pensez avoir trouvé...",
        max_length=20,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        """Traite la soumission du mot de passe."""
        await self.game_view.attempt_hack(interaction, self.code_input.value)

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
            app_commands.Choice(name="Livreur (Aléatoire)", value="livreur"),
            app_commands.Choice(name="Cuisinier (Choix multiple)", value="cuisinier"),
            app_commands.Choice(name="Pickpocket (Vol)", value="pickpocket"),
            app_commands.Choice(name="Hacker (Déchiffrage)", value="hacker")
        ])
    @check_cooldown_state('travail', active=False)
    async def cmd_job(self, interaction: discord.Interaction, work_type: str):
        """Effectuer une tâche pour gagner de l'argent
        
        :param work_type: Travail à effectuer"""
        
        if work_type.lower() == "livreur":
            account = self.eco.get_account(interaction.user)
            view = DeliveryGameView(account, interaction.user)
            await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
            set_cooldown(interaction.user, 'travail', COOLDOWNS['delivery'])
            
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
            set_cooldown(interaction.user, 'travail', COOLDOWNS['cooking'])
            
        elif work_type.lower() == "pickpocket":
            account = self.eco.get_account(interaction.user)
            
            # Récupérer les membres du serveur (excluant les bots)
            guild_members = [member for member in interaction.guild.members if not member.bot]
            
            # Créer la vue du mini-jeu
            view = PickpocketGameView(account, guild_members, interaction.user)
            await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
            set_cooldown(interaction.user, 'travail', COOLDOWNS['pickpocket'])
            
        elif work_type.lower() == "hacker":
            account = self.eco.get_account(interaction.user)
            
            # Créer la vue du mini-jeu de hacking
            view = HackerGameView(account, interaction.user)
            await interaction.response.send_message(view=view, allowed_mentions=discord.AllowedMentions.none())
            set_cooldown(interaction.user, 'travail', COOLDOWNS['hacker'])
            
        else:
            await interaction.response.send_message(
                "**ERREUR** · Ce type de travail n'est pas encore implémenté.",
                ephemeral=True
            )
        
async def setup(bot):
    await bot.add_cog(Jobs(bot))
