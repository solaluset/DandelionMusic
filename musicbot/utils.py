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
from musicbot.songinfo import Song
from musicbot.linkutils import url_regex

# avoiding circular import
if TYPE_CHECKING:
    from musicbot.bot import Context, MusicBot


OLD_FFMPEG_CONF = """
ffmpeg version 5.1.git Copyright (c) 2000-2022 the FFmpeg developers
built with gcc 12.1.0 (Rev2, Built by MSYS2 project)
configuration: --disable-programs --enable-ffmpeg --disable-doc\
 --enable-w32threads --enable-openssl --extra-ldflags=-static\
 --pkg-config='pkg-config --static --with-path=/usr/local/lib/pkgconfig'
libavutil      57. 33.101 / 57. 33.101
libavcodec     59. 42.102 / 59. 42.102
libavformat    59. 30.100 / 59. 30.100
libavdevice    59.  8.101 / 59.  8.101
libavfilter     8. 46.103 /  8. 46.103
libswscale      6.  8.103 /  6.  8.103
libswresample   4.  8.100 /  4.  8.100
""".strip()
FFMPEG_ZIP_URL = (
    "https://github.com/Krutyi-4el/FFmpeg"
    "/releases/latest/download/ffmpeg.zip"
)
NEWEST_FFMPEG_TIMESTAMP = 1704887962


def extract_ffmpeg_timestamp(version: str) -> int:
    version = version.split()
    if len(version) > 2:
        timestamp = version[2].partition("-K4_")[2]
        try:
            return int(timestamp)
        except ValueError:
            pass
    return None


def check_dependencies():
    if pycord_version != "2.5.6":
        raise ImportError(
            "you have wrong version of Pycord."
            " Please install the version specified in requirements.txt"
        )

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    ffmpeg_output = None
    try:
        ffmpeg_output = check_output(
            ("ffmpeg", "-version"), text=True, creationflags=flags
        ).strip()
    except (FileNotFoundError, CalledProcessError) as e:
        if sys.platform == "win32":
            print("Downloading FFmpeg...")
            download_ffmpeg()
        else:
            raise RuntimeError("ffmpeg was not found") from e
    if sys.platform == "win32" and ffmpeg_output:
        ffmpeg_timestamp = extract_ffmpeg_timestamp(ffmpeg_output)
        if ffmpeg_output == OLD_FFMPEG_CONF or (
            ffmpeg_timestamp and ffmpeg_timestamp < NEWEST_FFMPEG_TIMESTAMP
        ):
            print("Updating FFmpeg...")
            download_ffmpeg()

    try:
        opus.Encoder.get_opus_version()
    except opus.OpusNotLoaded as e:
        raise RuntimeError("opus was not found") from e


def download_ffmpeg():
    from io import BytesIO
    from ssl import SSLContext
    from zipfile import ZipFile
    from urllib.request import urlopen

    stream = urlopen(
        FFMPEG_ZIP_URL,
        context=SSLContext(),
    )
    total_size = int(stream.getheader("content-length") or 0)
    file = BytesIO()
    if total_size:
        BLOCK_SIZE = 1024 * 1024

        data = stream.read(BLOCK_SIZE)
        received_size = BLOCK_SIZE
        percentage = 0
        print("0%", end="")
        while data:
            file.write(data)
            data = stream.read(BLOCK_SIZE)
            received_size += len(data)
            new_percentage = int(received_size / total_size * 100)
            if new_percentage != percentage:
                print("\r", new_percentage, "%", sep="", end="")
                percentage = new_percentage
    else:
        file.write(stream.read())
    zipf = ZipFile(file)
    filename = [
        name for name in zipf.namelist() if name.endswith("ffmpeg.exe")
    ][0]
    with open("ffmpeg.exe", "wb") as f:
        f.write(zipf.read(filename))
    print("\nSuccess!")


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
    vc_rule = sett.user_must_be_in_vc

    if cm_channel is not None:
        if int(cm_channel) != ctx.channel.id:
            raise CheckError(config.WRONG_CHANNEL_MESSAGE)

    if not ctx.guild.voice_client:
        return await ctx.bot.audio_controllers[ctx.guild].uconnect(ctx)

    if vc_rule:
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
                song.info.title
                or url_regex.fullmatch(song.info.webpage_url).group("bare"),
                song.info.webpage_url,
            ),
            inline=False,
        )

    return embed


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
