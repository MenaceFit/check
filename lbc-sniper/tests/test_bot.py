import json

import discord
import pytest

from lbcsniper.bot import AdView, SniperBot
from lbcsniper.lbc.parse import normalize_ad
from lbcsniper.models import SearchConfig
from lbcsniper.notifier import build_embed


class FakeChannel(discord.abc.Messageable):
    def __init__(self):
        self.sent = []

    async def _get_channel(self):
        return self

    async def send(self, **kwargs):
        self.sent.append(kwargs)


async def test_bot_commands_and_send(settings, api_response, monkeypatch):
    from tests.test_engine_web import close, make_engine

    engine = await make_engine(settings)
    bot = SniperBot(engine)
    group = bot.tree.get_command("lbc")
    assert {c.name for c in group.commands} == {"status", "ajouter", "pause", "reprendre", "tester", "toutpause"}

    ch = FakeChannel()
    monkeypatch.setattr(bot, "get_channel", lambda _id: ch)
    ad = normalize_ad(api_response["ads"][0])
    embed = build_embed(ad, SearchConfig(), 4)
    await bot.send_ad("123", "@everyone", embed, ad.url)
    msg = ch.sent[0]
    assert msg["content"] == "@everyone"
    assert isinstance(msg["embed"], discord.Embed) and msg["embed"].title.startswith("PC Gamer")
    assert isinstance(msg["view"], AdView) and msg["view"].children[0].url == ad.url
    await close(engine)
