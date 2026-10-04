from __future__ import annotations

import asyncio
import sys
from collections import defaultdict, deque
from collections.abc import Coroutine
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from inspect import isawaitable
from itertools import islice
from traceback import print_exc
from typing import TYPE_CHECKING, ClassVar, Literal

import discord

from config import config
from musicbot import loader, utils
from musicbot.context import BasicContext, InteractionContext
from musicbot.ffmpeg import AudioMixer, FFmpegPCMAudio
from musicbot.playlist import LoopMode, LoopState, PauseState, Playlist
from musicbot.song import Song, SongError
from musicbot.utils import (
    CheckError,
    StrEnum,
    View,
    asset,
    channel_check,
    play_check,
)

# avoiding circular import
if TYPE_CHECKING:
    from musicbot.bot import MusicBot


VC_CONNECT_TIMEOUT = 10

PLAYLIST = object()
EMPTY_PLAYLIST = object()
_not_provided = object()


class VoiceAsset(StrEnum):
    # assets were encoded with these parameters:
    # -af loudnorm -b:a 48k -frame_duration 60
    HELLO = "hello.opus"
    GOODBYE = "goodbye.opus"
    WAIT = "wait.opus"


class MusicButton(discord.ui.Button):
    USAGE_HISTORY: ClassVar[defaultdict[int, deque[tuple[int, int, str]]]] = (
        defaultdict(lambda: deque(maxlen=100))
    )

    def __init__(self, callback, check=play_check, **kwargs):
        super().__init__(**kwargs)
        self._callback = callback
        self._check = check

    async def callback(self, inter):
        ctx = InteractionContext(inter)
        try:
            await self._check(ctx)
        except CheckError as e:
            await ctx.send(e, ephemeral=True)
            return
        self.USAGE_HISTORY[ctx.guild.id].appendleft(
            (
                int(datetime.now(UTC).timestamp()),
                ctx.author.id,
                str(self),
            )
        )
        async with ctx.typing():
            res = self._callback(ctx)
            if isawaitable(res):
                await res

    def __str__(self) -> str:
        return " ".join(str(part) for part in (self.emoji, self.label) if part)


class AudioController:
    """Controls the playback of audio and the sequential playing of the songs.

    Attributes:
        bot: The instance of the bot that will be playing the music.
        playlist: A Playlist object that stores the history and queue of songs.
        current_song: A Song object that stores details of the current song.
        guild: The guild in which the Audiocontroller operates.
    """

    def __init__(self, bot: MusicBot, guild: discord.Guild):
        self.bot = bot
        self.playlist = Playlist()
        self._next_song = None
        self.guild = guild
        self.mixer = None

        sett = bot.settings[guild]
        self._volume: int = sett.default_volume

        self.timer = utils.Timer(self.timeout_handler)

        self.command_channel: discord.abc.Messageable | None = None

        self.last_message = None
        self.last_view = None
        self.last_view_data = None

        # according to Python documentation, we need
        # to keep strong references to all tasks
        self._tasks = set()

        self.command_lock = asyncio.Lock()
        self.message_lock = asyncio.Lock()

        self.current_voice_asset: VoiceAsset | None = None
        self.voice_asset_future: asyncio.Future | None = None
        self._waiting = False

    @property
    def current_song(self) -> Song | None:
        if self.playlist:
            return self.playlist[0]
        return None

    def get_current_song_time(self) -> int:
        return (self.current_song.start or 0) + round(
            self.mixer.get_stream(0).read_frames / AudioMixer.FRAMES_PER_SECOND
        )

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int):
        self._volume = value
        try:
            self.mixer.get_stream(0).source.volume = value / 100.0
        except AttributeError:
            pass
        except Exception:  # noqa: BLE001
            print("Unknown error when setting volume:", file=sys.stderr)
            print_exc(file=sys.stderr)

    def volume_up(self):
        self.volume = min(self.volume + 10, 200)

    def volume_down(self):
        self.volume = max(self.volume - 10, 10)

    async def register_voice_channel(self, channel: discord.VoiceChannel):
        perms = channel.permissions_for(self.guild.me)
        if not perms.connect or not perms.speak:
            raise CheckError(config.VOICE_PERMISSIONS_MISSING)

        bot_vc = self.guild.voice_client
        if bot_vc:
            await bot_vc.move_to(channel)
        else:
            bot_vc = await channel.connect(
                reconnect=True, timeout=VC_CONNECT_TIMEOUT
            )
            self.mixer = AudioMixer(bot_vc)

        # to avoid ClientException: Not connected to voice
        await asyncio.sleep(1)

        if config.ANNOUNCE_CONNECT and not self.is_active():
            self.play_asset(VoiceAsset.HELLO)

    def make_view(self):
        if not self.is_active():
            self.last_view = self.last_view_data = None
            return None

        stream = self.mixer.get_stream(0)
        is_playing = stream and not stream.paused

        view_data = {
            "has_prev": self.playlist.has_prev(),
            "has_next": self.playlist.has_next(),
            "pause_emoji": "⏸️" if is_playing else "▶️",
            "is_empty": len(self.playlist) == 0,
            "loop_label": "Loop: " + self.playlist.loop,
            "no_current_song": self.current_song is None,
            "volume": self.volume,
        }

        if view_data == self.last_view_data:
            return self.last_view

        self.last_view_data = view_data
        self.last_view = View(
            MusicButton(
                lambda _: self.prev_song(),
                custom_id="prev",
                disabled=not view_data["has_prev"],
                emoji="⏮️",
            ),
            MusicButton(
                lambda _: self.pause(),
                custom_id="pause",
                emoji=view_data["pause_emoji"],
            ),
            MusicButton(
                lambda _: self.next_song(forced=True),
                custom_id="next",
                disabled=not view_data["has_next"],
                emoji="⏭️",
            ),
            MusicButton(
                lambda _: self.loop(),
                custom_id="loop",
                disabled=view_data["is_empty"],
                emoji="🔁",
                label=view_data["loop_label"],
            ),
            MusicButton(
                self.current_song_callback,
                check=channel_check,
                custom_id="current_song",
                row=1,
                disabled=view_data["no_current_song"],
                emoji="💿",
            ),
            MusicButton(
                lambda _: self.shuffle(),
                custom_id="shuffle",
                row=1,
                disabled=view_data["is_empty"],
                emoji="🔀",
            ),
            MusicButton(
                self.queue_callback,
                check=channel_check,
                custom_id="queue",
                row=1,
                disabled=view_data["is_empty"],
                emoji="📜",
            ),
            MusicButton(
                lambda _: self.stop_player(),
                custom_id="stop",
                row=1,
                emoji="⏹️",
                style=discord.ButtonStyle.red,
            ),
            MusicButton(
                lambda _: self.volume_down(),
                custom_id="volume_down",
                row=2,
                disabled=view_data["volume"] <= 10,
                emoji="🔉",
            ),
            MusicButton(
                lambda _: self.volume_up(),
                custom_id="volume_up",
                row=2,
                disabled=view_data["volume"] >= 200,
                emoji="🔊",
                label=f"{view_data['volume']}%",
            ),
            timeout=None,
        )

        return self.last_view

    async def current_song_callback(self, ctx):
        await ctx.send(
            embed=self.current_song.format_output(
                config.SONGINFO_SONGINFO, self.get_current_song_time()
            ),
        )

    async def queue_callback(self, ctx):
        await ctx.send(
            embed=self.playlist.queue_embed(),
        )

    async def update_view(self, view=_not_provided):
        msg = self.last_message
        if not msg:
            return
        reset_message = False
        if view is None:
            reset_message = True
            self.last_message = None
        elif view is _not_provided:
            old_view = self.last_view
            view = self.make_view()
            if view is old_view:
                return
        try:
            await msg.edit(view=view)
        except discord.NotFound:
            self.last_message = None
        except discord.HTTPException as e:
            if e.code == 50027:  # Invalid Webhook Token
                try:
                    msg = await msg.channel.fetch_message(msg.id)
                    if not reset_message:
                        self.last_message = msg
                    await msg.edit(view=view)
                except discord.NotFound:
                    self.last_message = None
            else:
                print("Failed to update view:", file=sys.stderr)
                print_exc(file=sys.stderr)

    def is_active(self) -> bool:
        return bool(self.mixer and self.mixer.get_stream(0))

    def track_history(self):
        history_string = config.INFO_HISTORY_TITLE
        for trackname in self.playlist.trackname_history:
            history_string += "\n" + trackname
        return history_string

    def pause(self):
        if self.mixer and (stream := self.mixer.get_stream(0)):
            if not stream.paused:
                stream.paused = True
                self.add_task(self.timer.start(True))
                return PauseState.PAUSED
            stream.paused = False
            return PauseState.RESUMED
        return PauseState.NOTHING_TO_PAUSE

    def loop(self, mode=None):
        if mode is None:
            if self.playlist.loop == LoopMode.OFF:
                mode = LoopMode.ALL
            else:
                mode = LoopMode.OFF

        try:
            mode = LoopMode(mode)
        except ValueError:
            return LoopState.INVALID

        self.playlist.loop = mode

        if mode == LoopMode.OFF:
            return LoopState.DISABLED
        return LoopState.ENABLED

    def shuffle(self):
        self.playlist.shuffle()
        self.preload_queue()

    def fast_forward(self, seconds: int) -> None:
        if self.mixer:
            self.add_task(
                self.bot.loop.run_in_executor(
                    None,
                    lambda: self.mixer.fast_forward_stream(
                        0, seconds * self.mixer.FRAMES_PER_SECOND
                    ),
                )
            )

    def rewind(self, seconds: int) -> int:
        if self.mixer:
            return round(
                self.mixer.rewind_stream(
                    0, seconds * self.mixer.FRAMES_PER_SECOND
                )
                / self.mixer.FRAMES_PER_SECOND
            )
        return 0

    @staticmethod
    def needs_waiting(func):
        @wraps(func)
        async def wrapped(self: AudioController, *args, **kwargs):
            self.announce_waiting()
            try:
                return await func(self, *args, **kwargs)
            finally:
                self.stop_waiting()

        return wrapped

    @contextmanager
    def suppress_looping(self):
        original_mode = self.playlist.loop
        self.playlist.loop = LoopMode.OFF
        try:
            yield
        finally:
            self.playlist.loop = original_mode

    def next_song(self, *, forced=False):
        """Invoked after a song is finished
        Plays the next song if there is one"""

        if self.playlist:
            self.playlist.add_name(self.playlist[0].title)

        if self.is_active():
            self._next_song = self.playlist.next(forced)
            self.mixer.stop_stream(0)
            return

        if self._next_song:
            next_song = self._next_song
            self._next_song = None
        else:
            next_song = self.playlist.next(forced)

        if next_song is None:
            if not self.timer.triggered() and self.guild.voice_client:
                self.add_task(
                    self.timer.start(
                        not all(
                            m.bot
                            for m in self.guild.voice_client.channel.members
                        )
                    )
                )
            return

        coro = self.play_song(next_song)
        self.add_task(coro)

    async def play_song(self, song: Song):
        """Plays a song object"""

        async def _announce_waiting_later():
            await asyncio.sleep(1)
            self.announce_waiting()

        waiting_task = self.add_task(_announce_waiting_later())

        try:
            if not await loader.preload(song, self.bot):
                self.next_song(forced=True)
                return

            if song.data is None or "ext" not in song.data:
                print(
                    "Something is wrong."
                    " Refusing to play a song without direct url.",
                    file=sys.stderr,
                )
                self.next_song(forced=True)
                return

            audio = FFmpegPCMAudio(await loader.get_ffmpeg_args(song))
            # FFmpeg needs some time when seeking, ensure it's ready
            await self.bot.loop.run_in_executor(None, audio.read)
            audio._check_process_returncode()
            if error := audio._current_error:
                raise SongError(config.SONGINFO_ERROR) from error
        finally:
            waiting_task.cancel()
            self.stop_waiting()

        if (
            self.voice_asset_future
            and self.current_voice_asset == VoiceAsset.HELLO
        ):
            await self.voice_asset_future

        if not self.guild.voice_client:
            raise loader.SongError(config.NOT_CONNECTED_MESSAGE)

        try:
            self.mixer.add_stream(
                discord.PCMVolumeTransformer(
                    audio,
                    self.volume / 100.0,
                ),
                id_=0,
                after=lambda: self.bot.loop.call_soon_threadsafe(
                    self.next_song
                ),
                rewindable=True,
            )
        except discord.ClientException:
            await self.udisconnect()
            return

        if (
            self.bot.settings[self.guild].announce_songs
            and self.command_channel
        ):
            await self.command_channel.send(
                embed=song.format_output(config.SONGINFO_NOW_PLAYING)
            )

        self.preload_queue()

    @needs_waiting
    async def _process_song(
        self, track: str
    ) -> Song | Literal[PLAYLIST, EMPTY_PLAYLIST] | None:
        """Adds the track to the playlist instance
        Starts playing if it is the first song"""

        loaded_song = await loader.load_song(track)
        if loaded_song is None:
            return None
        elif not loaded_song:
            # empty list
            return EMPTY_PLAYLIST
        elif isinstance(loaded_song, Song):
            self.playlist.add(loaded_song)
        else:
            for song in loaded_song:
                self.playlist.add(song)
            if len(loaded_song) == 1:
                # special-case one-item playlists
                loaded_song = loaded_song[0]
            else:
                loaded_song = PLAYLIST

        if not self.is_active():
            print(f"Playing {track}")
            await self.play_song(self.playlist[0])
        else:
            self.preload_queue()

        return loaded_song

    async def play(self, ctx: BasicContext, track: str):
        # reset timer
        await self.timer.start(True)

        try:
            song = await self._process_song(track)
        except SongError as e:
            await ctx.send(e)
            return
        if song is None:
            await ctx.send(config.SONGINFO_UNSUPPORTED)
            return

        if song is PLAYLIST:
            await ctx.send(config.SONGINFO_PLAYLIST_QUEUED)
        elif song is EMPTY_PLAYLIST:
            await ctx.send(config.SONGINFO_PLAYLIST_EMPTY)
        else:
            if len(self.playlist) != 1:
                await ctx.send(
                    embed=song.format_output(config.SONGINFO_QUEUE_ADDED)
                )
            elif not ctx.bot.settings[ctx.guild].announce_songs:
                # auto-announce is disabled, announce here
                await ctx.send(
                    embed=song.format_output(config.SONGINFO_NOW_PLAYING)
                )

    def add_task(self, coro: Coroutine | asyncio.Future) -> asyncio.Future:
        if asyncio.isfuture(coro):
            task = coro
        else:
            task = self.bot.loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.remove)
        return task

    async def _preload_queue(self):
        rerun_needed = False
        for song in list(
            islice(self.playlist.playque, 1, config.MAX_SONG_PRELOAD)
        ):
            if not await loader.preload(song, self.bot):
                try:
                    self.playlist.playque.remove(song)
                    rerun_needed = True
                except ValueError:
                    # already removed
                    pass
        if rerun_needed:
            self.add_task(self._preload_queue())

    def preload_queue(self):
        "Preloads the first MAX_SONG_PRELOAD songs asynchronously"
        self.add_task(self._preload_queue())

    def stop_player(self):
        """Stops the player and removes all songs from the queue"""
        self.playlist.loop = LoopMode.OFF
        self.playlist.clear()
        self.playlist.next()

        if not self.is_active():
            return

        self.mixer.stop_stream(0)

    def prev_song(self) -> bool:
        """Loads the last song from the history into the queue and starts it"""

        prev_song = self.playlist.prev()
        if not prev_song:
            return False

        if not self.is_active():
            self.add_task(self.play_song(prev_song))
        else:
            self._next_song = prev_song
            self.mixer.stop_stream(0)
        return True

    async def timeout_handler(self):
        if not self.guild.voice_client:
            return

        sett = self.bot.settings[self.guild]

        if sett.vc_timeout and (
            not self.guild.voice_client.is_playing()
            or all(m.bot for m in self.guild.voice_client.channel.members)
        ):
            await self.udisconnect()

    def play_asset(self, voice_asset: VoiceAsset) -> asyncio.Future:
        self.current_voice_asset = voice_asset
        future = self.bot.loop.create_future()

        def set_done():
            if future.cancelled():
                return
            future.set_result(None)

        self.mixer.add_stream(
            discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(asset(voice_asset)),
                self.volume / 100.0,
            ),
            id_=-1,
            after=lambda: self.bot.loop.call_soon_threadsafe(set_done),
        )
        self.voice_asset_future = future
        self.voice_asset_future.add_done_callback(
            self._clear_voice_asset_future
        )
        return self.voice_asset_future

    def _clear_voice_asset_future(self, _):
        self.voice_asset_future = None
        self.current_voice_asset = None

    def announce_waiting(self):
        if not config.ANNOUNCE_WAITING:
            return

        self._waiting = True

        if (
            self.is_active()
            or not self.guild.voice_client
            or not self.guild.voice_client.is_connected()
        ):
            return

        def continue_waiting(_):
            if self._waiting:
                self.announce_waiting()

        if self.voice_asset_future is not None:
            if self.current_voice_asset != VoiceAsset.WAIT:
                self.voice_asset_future.add_done_callback(continue_waiting)
            return

        future = self.play_asset(VoiceAsset.WAIT)
        future.add_done_callback(continue_waiting)

    def stop_waiting(self):
        if not self._waiting:
            return False
        self._waiting = False
        if self.mixer:
            self.mixer.stop_stream(-1)
        return True

    async def uconnect(self, ctx, move=False) -> None:
        author_vc = ctx.author.voice
        bot_vc = self.guild.voice_client

        if not author_vc:
            raise CheckError(config.USER_NOT_IN_VC_MESSAGE)

        if bot_vc is None or bot_vc.channel != author_vc.channel and move:
            await ctx.typing()
            await self.register_voice_channel(author_vc.channel)
        else:
            raise CheckError(config.ALREADY_CONNECTED_MESSAGE)

    async def udisconnect(self):
        self.stop_player()
        self.timer.cancel()
        self._waiting = False
        await self.update_view(None)
        if (client := self.guild.voice_client) is None:
            self.mixer = None
            return False
        if config.ANNOUNCE_DISCONNECT and self.mixer and client.is_connected():
            self.mixer.stop_stream(-1)
            try:
                await self.play_asset(VoiceAsset.GOODBYE)
            except Exception:  # noqa: BLE001
                print_exc(file=sys.stderr)
            else:
                # let it finish
                await asyncio.sleep(1)
        self.mixer = None
        await client.disconnect(force=True)
        return True
