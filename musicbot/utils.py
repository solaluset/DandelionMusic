from __future__ import annotations
import os
import sys
import _thread
import asyncio
import subprocess
from enum import Enum
from subprocess import CalledProcessError, check_output
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    Iterable,
    Optional,
    Union,
    List,
)

from aioconsole import ainput
from discord import (
    __version__ as pycord_version,
    opus,
    utils,
    Emoji,
    Embed,
)
from discord.ext.commands import CommandError

from config import config
from musicbot.song import Song
from musicbot.linkutils import url_regex

# avoiding circular import
if TYPE_CHECKING:
    from musicbot.bot import Context, MusicBot


def check_dependencies():
    if pycord_version != "2.7.2-SL":
        raise ImportError(
            "you have wrong version of Pycord."
            " Please install the version specified in requirements.txt"
        )

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        check_output(("ffmpeg", "-version"), text=True, creationflags=flags)
    except (FileNotFoundError, CalledProcessError) as e:
        raise RuntimeError("ffmpeg was not found") from e

    try:
        opus.Encoder.get_opus_version()
    except opus.OpusNotLoaded as e:
        raise RuntimeError("opus was not found") from e


ASSETS_PATH = os.path.join(
    getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(sys.argv[0] or "dummy")),
    ),
    "assets",
)


def asset(name: str) -> str:
    return os.path.join(ASSETS_PATH, name)


class CheckError(CommandError):
    pass


async def dj_check(ctx: Context):
    "Check if the user has DJ permissions"
    if ctx.channel.permissions_for(ctx.author).administrator:
        return True

    sett = ctx.bot.settings[ctx.guild]
    if sett.dj_role:
        if int(sett.dj_role) not in [r.id for r in ctx.author.roles]:
            raise CheckError(config.NOT_A_DJ)
        return True

    raise CheckError(config.USER_MISSING_PERMISSIONS)


async def voice_check(ctx: Context):
    "Check if the user can use the bot now"
    bot_vc = ctx.guild.voice_client
    if not bot_vc:
        # the bot is free
        return True

    author_voice = ctx.author.voice
    if author_voice:
        if author_voice.channel == bot_vc.channel:
            return True

        if all(m.bot for m in bot_vc.channel.members):
            # current channel doesn't have any user in it
            return await ctx.bot.audio_controllers[ctx.guild].uconnect(
                ctx, move=True
            )

    try:
        if await dj_check(ctx):
            # DJs and admins can always run commands
            return True
    except CheckError:
        pass

    raise CheckError(config.USER_NOT_IN_VC_MESSAGE)


async def play_check(ctx: Context):
    "Prepare for music commands"

    sett = ctx.bot.settings[ctx.guild]

    cm_channel = sett.command_channel

    if cm_channel is not None:
        if int(cm_channel) != ctx.channel.id:
            raise CheckError(config.WRONG_CHANNEL_MESSAGE)

    if sett.dj_only:
        await dj_check(ctx)

    if not ctx.guild.voice_client:
        return await ctx.bot.audio_controllers[ctx.guild].uconnect(ctx)

    if sett.user_must_be_in_vc:
        return await voice_check(ctx)

    return True


def get_emoji(bot: MusicBot, string: str) -> Optional[Union[str, Emoji]]:
    if string.isdecimal():
        return utils.get(bot.emojis, id=int(string))
    return string


def songs_embed(title: str, songs: Iterable[Song]) -> Embed:
    embed = Embed(
        title=title,
        color=config.EMBED_COLOR,
    )

    for counter, song in enumerate(songs, start=1):
        embed.add_field(
            name=f"{counter}.",
            value="[{}]({})".format(
                song.title
                or url_regex.fullmatch(song.webpage_url).group("bare"),
                song.webpage_url,
            ),
            inline=False,
        )

    return embed


def chunks(lst: list, n: int) -> List[list]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# StrEnum doesn't exist in Python < 3.11
class StrEnum(str, Enum):
    def __str__(self):
        return self._value_


class Timer:
    def __init__(self, callback: Callable[[], Awaitable]):
        self._callback = callback
        self._task = None
        self.triggered = False

    async def _job(self):
        await asyncio.sleep(config.VC_TIMEOUT)
        self.triggered = True
        await self._callback()
        self.triggered = False
        self._task = None

    # we need event loop here
    async def start(self, restart=False):
        if self._task:
            if restart:
                self._task.cancel()
            else:
                return
        self._task = asyncio.create_task(self._job())

    def cancel(self):
        if self._task:
            self._task.cancel()
            self._task = None


class OutputWrapper:
    log_file = None

    def __init__(self, stream):
        self.using_log_file = False
        self.stream = stream

    def write(self, text, /):
        try:
            ret = self.stream.write(text)
            if not self.using_log_file:
                self.flush()
        except Exception:
            self.using_log_file = True
            self.stream = self.get_log_file()
            ret = self.stream.write(text)
        return ret

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            self.using_log_file = True
            self.stream = self.get_log_file()

    def __getattr__(self, key):
        return getattr(self.stream, key)

    @classmethod
    def get_log_file(cls):
        if cls.log_file:
            return cls.log_file
        cls.log_file = open("log.txt", "w", encoding="utf-8")
        return cls.log_file


async def read_shutdown():
    try:
        line = await ainput()
    except EOFError:
        return
    if line == "shutdown":
        _thread.interrupt_main()
