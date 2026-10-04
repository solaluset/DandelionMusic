import sys
from traceback import print_exc

import discord
from discord.ext import commands

from config import config
from musicbot import loader
from musicbot.bot import MusicBot
from musicbot.utils import check_dependencies

initial_extensions = [
    "musicbot.commands.music",
    "musicbot.commands.general",
    "musicbot.commands.developer",
]


intents = discord.Intents.default()
intents.voice_states = True
if config.BOT_PREFIX:
    intents.message_content = True
    prefixes = [config.BOT_PREFIX]
else:
    prefixes = []
if config.MENTION_AS_PREFIX:
    prefixes = commands.when_mentioned_or(*prefixes)

if config.ENABLE_BUTTON_PLUGIN:
    initial_extensions.append("musicbot.plugins.button")

bot = MusicBot(
    command_prefix=prefixes,
    case_insensitive=True,
    status=discord.Status.online,
    activity=discord.Game(name=config.STATUS_TEXT),
    intents=intents,
    allowed_mentions=discord.AllowedMentions.none(),
    extensions=initial_extensions,
)


if __name__ == "__main__":
    print("Loading...")

    check_dependencies()
    config.warn_unknown_vars()
    if config.has_missing:
        config.save()

    # start executor before reading from stdin to avoid deadlocks
    loader.init()

    try:
        bot.run(config.BOT_TOKEN, reconnect=True)
    except discord.LoginFailure:
        print_exc(file=sys.stderr)
        print("Set the correct token in config.json", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        if e.args != ("Event loop is closed",):
            raise
