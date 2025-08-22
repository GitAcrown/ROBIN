import io
import logging
import textwrap
import traceback
from contextlib import redirect_stdout
from typing import Any, Optional
from datetime import datetime

import discord
from discord import app_commands, ui
from discord.ext import commands

from common.cooldowns import get_all_cooldowns, Cooldown

logger = logging.getLogger(f'ROBIN.{__name__.split(".")[-1]}')

ICONS = {
    'cooldown': '<:cooldown:1408437162663346258>'
}

# UI -------------------------------------------

class CooldownsView(ui.LayoutView):
    """Vue pour afficher tous les cooldowns d'un utilisateur."""
    def __init__(self, cooldowns: list[Cooldown], user: discord.User):
        super().__init__(timeout=300)
        self.cooldowns = cooldowns
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
        """Configure la mise en page des cooldowns."""
        container = ui.Container()
        
        # En-tête avec emoji uniquement dans le titre
        header = ui.TextDisplay(f"## {ICONS['cooldown']} Cooldowns actifs · {self.user.mention}")
        container.add_item(header)
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
    
        displayed_cooldowns = self.cooldowns[:15]
        
        if not displayed_cooldowns:
            no_cooldowns = ui.TextDisplay("Aucun cooldown actif.")
            container.add_item(no_cooldowns)
        else:
            for i, cooldown in enumerate(displayed_cooldowns):
                try:
                    # Calculer les temps
                    progress_percent = cooldown.progress() * 100
                    
                    # Titre avec nom du cooldown
                    cd_title = ui.TextDisplay(f"### {cooldown.cooldown_name}")
                    
                    # Informations détaillées (sans le temps restant puisqu'il est dans le bouton)
                    info_text = f"**Progression** · {progress_percent:.1f}%"
                    
                    # Ajouter les métadonnées si disponibles
                    if cooldown.metadata:
                        info_text += f"\n**Détails** · {cooldown.metadata}"
                    
                    # Timestamp de création
                    created_time = datetime.fromtimestamp(cooldown.created_at).strftime('%d/%m/%y à %H:%M')
                    info_text += f"\n-# Lancée le {created_time}"
                    
                    cd_info = ui.TextDisplay(info_text)
                    
                    # Bouton avec temps restant formaté (désactivé)
                    time_button = ui.Button(
                        label=cooldown.format_remaining_time(), 
                        style=discord.ButtonStyle.secondary, 
                        disabled=True
                    )
                    
                    # Créer la section
                    cd_section = ui.Section(cd_title, cd_info, accessory=time_button)
                    container.add_item(cd_section)
                    
                    # Ajouter un séparateur entre les cooldowns (sauf pour le dernier)
                    if i < len(displayed_cooldowns) - 1:
                        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
                        
                except Exception:
                    # En cas d'erreur, section simple avec bouton d'erreur
                    error_button = ui.Button(
                        label="Erreur", 
                        style=discord.ButtonStyle.danger, 
                        disabled=True
                    )
                    error_section = ui.Section(
                        ui.TextDisplay("### Erreur de lecture"),
                        ui.TextDisplay("Impossible de lire ce cooldown"),
                        accessory=error_button
                    )
                    container.add_item(error_section)
                    
                    # Séparateur après erreur aussi
                    if i < len(displayed_cooldowns) - 1:
                        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        
        # Footer avec nombre total
        if len(self.cooldowns) > 15:
            container.add_item(ui.Separator())
            footer_text = f"*Affichage de 15 cooldowns sur {len(self.cooldowns)} au total*"
            footer = ui.TextDisplay(footer_text)
            container.add_item(footer)
        
        self.add_item(container)

class Core(commands.Cog):
    """Module central du bot, contenant des commandes de base."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        self._last_result: Optional[Any] = None

    # Gestion des commandes et modules ------------------------------

    @commands.command(name="load", hidden=True)
    @commands.is_owner()
    async def load(self, ctx, *, cog: str):
        """Charge un module"""
        cog_path = f'cogs.{cog}.{cog}'
        try:
            await self.bot.load_extension(cog_path)
        except Exception as exc:
            await ctx.send(f"**`ERREUR :`** {type(exc).__name__} - {exc}")
        else:
            await ctx.send("**`SUCCÈS`**")

    @commands.command(name="unload", hidden=True)
    @commands.is_owner()
    async def unload(self, ctx, *, cog: str):
        """Décharge un module"""
        cog_path = f'cogs.{cog}.{cog}'
        try:
            await self.bot.unload_extension(cog_path)
        except Exception as exc:
            await ctx.send(f"**`ERREUR :`** {type(exc).__name__} - {exc}")
        else:
            await ctx.send("**`SUCCÈS`**")

    @commands.command(name="reload", hidden=True)
    @commands.is_owner()
    async def reload(self, ctx, *, cog: str):
        """Recharge un module"""
        cog_path = f'cogs.{cog}.{cog}'
        try:
            await self.bot.reload_extension(cog_path)
        except Exception as exc:
            await ctx.send(f"**`ERREUR :`** {type(exc).__name__} - {exc}")
        else:
            await ctx.send("**`SUCCÈS`**")
            
    @commands.command(name="reloadall", hidden=True)
    @commands.is_owner()
    async def reloadall(self, ctx):
        """Recharge tous les modules"""
        for ext_name, _ext in self.bot.extensions.items():
            try:
                await self.bot.reload_extension(ext_name)
            except Exception as exc:
                await ctx.send(f"**`ERREUR :`** {type(exc).__name__} - {exc}")
        await ctx.send("**`SUCCÈS`**")

    @commands.command(name="extensions", hidden=True)
    @commands.is_owner()
    async def extensions(self, ctx):
        for ext_name, _ext in self.bot.extensions.items():
            await ctx.send(ext_name)

    @commands.command(name="cogs", hidden=True)
    @commands.is_owner()
    async def cogs(self, ctx):
        for cog_name, _cog in self.bot.cogs.items():
            await ctx.send(cog_name)
            
    # Commandes d'évaluation de code ------------------------------
            
    def cleanup_code(self, content: str) -> str:
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        return content.strip('` \n')
            
    @commands.command(name='eval', hidden=True)
    @commands.is_owner()
    async def eval_code(self, ctx: commands.Context, *, body: str):
        """Evalue du code"""

        env = {
            'bot': self.bot,
            'ctx': ctx,
            'channel': ctx.channel,
            'author': ctx.author,
            'guild': ctx.guild,
            'message': ctx.message,
            '_': self._last_result,
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(f'```py\n{e.__class__.__name__}: {e}\n```')

        func = env['func']
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await ctx.send(f'```py\n{value}{traceback.format_exc()}\n```')
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction('\u2705')
            except:
                pass

            if ret is None:
                if value:
                    await ctx.send(f'```py\n{value}\n```')
            else:
                self._last_result = ret
                await ctx.send(f'```py\n{value}{ret}\n```')
                
    # Commandes globales ------------------------------
                
    @app_commands.command(name="ping")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Renvoie le ping du bot"""
        await interaction.response.send_message(f"Pong ! (`{round(self.bot.latency * 1000)}ms`)")
        
    @app_commands.command(name="cooldowns")
    async def cooldowns(self, interaction: discord.Interaction) -> None:
        """Affiche tous vos cooldowns actifs"""
        cooldowns = get_all_cooldowns(interaction.user)
        
        view = CooldownsView(cooldowns, interaction.user)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=discord.AllowedMentions.none()
        )
        
        
async def setup(bot):
    await bot.add_cog(Core(bot))
