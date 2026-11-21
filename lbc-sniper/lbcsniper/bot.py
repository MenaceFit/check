"""Bot Discord : envoi des alertes + commandes slash /lbc."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands

from .lbc.query import config_from_url
from .models import SearchConfig

if TYPE_CHECKING:
    from .engine import Engine

log = logging.getLogger("lbcsniper.bot")


class AdView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Voir l'annonce", url=url, emoji="🔗"))


class SniperBot(discord.Client):
    def __init__(self, engine: "Engine", guild_id: str = ""):
        super().__init__(intents=discord.Intents.default())
        self.engine = engine
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self.ready_event_fired = False
        self._register_commands()

    # ------------------------------------------------------------------ envoi
    async def send_ad(self, channel_id: str, content: str, embed: dict, url: str) -> None:
        channel = self.get_channel(int(channel_id))
        if channel is None:
            channel = await self.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"le salon {channel_id} n'accepte pas de messages")
        kwargs: dict = {}
        if content:
            kwargs["content"] = content
            kwargs["allowed_mentions"] = discord.AllowedMentions(everyone=True, roles=True, users=True)
        if embed:
            kwargs["embed"] = discord.Embed.from_dict(embed)
        if url:
            kwargs["view"] = AdView(url)
        await channel.send(**kwargs)

    def text_channels(self) -> list[dict]:
        out = []
        for guild in self.guilds:
            me = guild.me
            for ch in guild.text_channels:
                perms = ch.permissions_for(me)
                if perms.send_messages and perms.embed_links:
                    out.append({"id": str(ch.id), "name": f"#{ch.name}", "guild": guild.name})
        return out

    # -------------------------------------------------------------- lifecycle
    async def setup_hook(self) -> None:
        if self.guild_id:
            guild = discord.Object(id=int(self.guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Commandes slash synchronisées sur le serveur %s", self.guild_id)
        else:
            await self.tree.sync()
            log.info("Commandes slash synchronisées globalement (peut prendre jusqu'à 1 h)")

    async def on_ready(self) -> None:
        self.ready_event_fired = True
        log.info("Bot connecté en tant que %s", self.user)
        self.engine.bus.log("INFO", f"Bot Discord connecté : {self.user} ({len(self.guilds)} serveur(s))")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Leboncoin 👀"))

    # --------------------------------------------------------------- commands
    def _register_commands(self) -> None:
        group = app_commands.Group(name="lbc", description="LBC Sniper — surveillance Leboncoin")
        engine = self.engine

        async def search_autocomplete(interaction: discord.Interaction, current: str):
            items = await engine.db.list_searches()
            return [
                app_commands.Choice(name=cfg.name[:100], value=str(sid))
                for sid, cfg in items
                if current.lower() in cfg.name.lower()
            ][:25]

        @group.command(name="status", description="État des recherches")
        async def status(interaction: discord.Interaction):
            st = engine.status()
            items = await engine.db.list_searches()
            embed = discord.Embed(title="📊 LBC Sniper — état", color=0xFF6E14)
            embed.description = (
                f"{'⏸️ **En pause**' if st['paused'] else '▶️ **Actif**'} • "
                f"{st['requests_last_minute']}/{st['requests_limit_per_minute']} req/min • "
                f"{st['notifications_sent']} alertes envoyées"
            )
            for sid, cfg in items[:20]:
                w = st["watchers"].get(sid)
                if not cfg.enabled:
                    line = "⚪ désactivée"
                elif w is None:
                    line = "⚪ arrêtée"
                else:
                    icon = {"ok": "🟢", "error": "🔴", "paused": "⏸️", "starting": "🟡"}.get(w["state"], "⚪")
                    line = f"{icon} toutes les {w['interval']} s • {w['new_ads']} nouvelles"
                    if w["last_error"]:
                        line += f"\n⚠️ {w['last_error'][:80]}"
                embed.add_field(name=cfg.name[:256], value=line, inline=False)
            if not items:
                embed.add_field(name="Aucune recherche", value="Créez-en une avec `/lbc ajouter` ou depuis le dashboard.")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @group.command(name="ajouter", description="Surveiller une recherche à partir d'une URL leboncoin.fr")
        @app_commands.describe(
            url="URL copiée depuis leboncoin.fr après avoir appliqué vos filtres",
            nom="Nom de la recherche",
            intervalle="Secondes entre deux vérifications (défaut 30)",
        )
        async def ajouter(interaction: discord.Interaction, url: str, nom: Optional[str] = None, intervalle: Optional[int] = 30):
            if "leboncoin.fr" not in url:
                await interaction.response.send_message("❌ L'URL doit venir de leboncoin.fr", ephemeral=True)
                return
            cfg = config_from_url(url, SearchConfig(name=nom or "Nouvelle recherche"))
            if nom:
                cfg.name = nom
            cfg.discord_channel_id = str(interaction.channel_id)
            cfg.interval_seconds = max(engine.settings.min_interval, intervalle or 30)
            sid = await engine.db.create_search(cfg)
            await engine.reload(sid)
            await interaction.response.send_message(
                f"✅ Recherche **{cfg.name}** créée : les nouvelles annonces arriveront dans ce salon "
                f"(vérification toutes les {cfg.interval_seconds} s).",
                ephemeral=False,
            )

        @group.command(name="pause", description="Mettre une recherche en pause")
        @app_commands.autocomplete(recherche=search_autocomplete)
        async def pause(interaction: discord.Interaction, recherche: str):
            await self._toggle(interaction, recherche, False)

        @group.command(name="reprendre", description="Relancer une recherche")
        @app_commands.autocomplete(recherche=search_autocomplete)
        async def reprendre(interaction: discord.Interaction, recherche: str):
            await self._toggle(interaction, recherche, True)

        @group.command(name="tester", description="Afficher les 5 annonces les plus récentes d'une recherche")
        @app_commands.autocomplete(recherche=search_autocomplete)
        async def tester(interaction: discord.Interaction, recherche: str):
            await interaction.response.defer(ephemeral=True, thinking=True)
            cfg = await engine.db.get_search(int(recherche)) if recherche.isdigit() else None
            if not cfg:
                await interaction.followup.send("❌ Recherche introuvable", ephemeral=True)
                return
            try:
                results = await engine.preview(cfg)
            except Exception as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            if not results:
                await interaction.followup.send("Aucune annonce trouvée.", ephemeral=True)
                return
            lines = []
            for r in results[:5]:
                ad = r["ad"]
                price = f"{ad['price']:.0f} €" if ad.get("price") is not None else "—"
                flag = "✅" if r["accepted"] else f"🚫 {r['reason']}"
                lines.append(f"{flag} [{ad['title'][:70]}]({ad['url']}) — **{price}** — {ad.get('city', '')}")
            await interaction.followup.send("\n".join(lines), ephemeral=True, suppress_embeds=True)

        @group.command(name="toutpause", description="Mettre en pause / relancer toutes les recherches")
        async def toutpause(interaction: discord.Interaction):
            new = not engine.paused
            await engine.db.set_settings({"paused": new})
            await engine.refresh_settings()
            await interaction.response.send_message("⏸️ Tout est en pause." if new else "▶️ Surveillance relancée.", ephemeral=True)

        self.tree.add_command(group)

    async def _toggle(self, interaction: discord.Interaction, recherche: str, enabled: bool) -> None:
        engine = self.engine
        sid = int(recherche) if recherche.isdigit() else None
        cfg = await engine.db.get_search(sid) if sid else None
        if not cfg:
            await interaction.response.send_message("❌ Recherche introuvable", ephemeral=True)
            return
        cfg.enabled = enabled
        await engine.db.update_search(sid, cfg)
        await engine.reload(sid)
        await interaction.response.send_message(
            f"{'▶️' if enabled else '⏸️'} **{cfg.name}** {'relancée' if enabled else 'en pause'}.", ephemeral=True
        )
