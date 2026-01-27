import sys
import asyncio
from functools import wraps
from itertools import islice
from inspect import isawaitable
from traceback import print_exc
from concurrent.futures import Future
from typing import TYPE_CHECKING, Coroutine, Literal, Optional, Union

import discord
from config import config

from musicbot import loader, utils
from musicbot.song import Song
from musicbot.ffmpeg import MonkeyPopen
from musicbot.playlist import Playlist, LoopMode, LoopState, PauseState
from musicbot.utils import CheckError, StrEnum, asset, play_check

# avoiding circular import
if TYPE_CHECKING:
    from musicbot.bot import MusicBot


VC_CONNECT_TIMEOUT = 10

PLAYLIST = object()
EMPTY_PLAYLIST = object()
_not_provided = object()


class VoiceAsset(StrEnum):
    HELLO = "hello.mp3"
    GOODBYE = "goodbye.mp3"
    WAIT = "wait.mp3"


class MusicButton(discord.ui.Button):
    def __init__(self, callback, check=play_check, **kwargs):
        super().__init__(**kwargs)
        self._callback = callback
        self._check = check

    async def callback(self, inter):
        ctx = await inter.client.get_application_context(inter)
        try:
            await self._check(ctx)
        except CheckError as e:
            await ctx.send(e, ephemeral=True)
            return
        await inter.response.defer()
        res = self._callback(ctx)
        if isawaitable(res):
            await res


class AudioController(object):
    """Controls the playback of audio and the sequential playing of the songs.

    Attributes:
        bot: The instance of the bot that will be playing the music.
        playlist: A Playlist object that stores the history and queue of songs.
        current_song: A Song object that stores details of the current song.
        guild: The guild in which the Audiocontroller operates.
    """

    def __init__(self, bot: "MusicBot", guild: discord.Guild):
        self.bot = bot
        self.playlist = Playlist()
        self._next_song = None
        self.guild = guild

        sett = bot.settings[guild]
        self._volume: int = sett.default_volume

        self.timer = utils.Timer(self.timeout_handler)

        self.command_channel: Optional[discord.abc.Messageable] = None

        self.last_message = None
        self.last_view = None

        # according to Python documentation, we need
        # to keep strong references to all tasks
        self._tasks = set()

        self.message_lock = asyncio.Lock()

        self.current_voice_asset: Optional[VoiceAsset] = None
        self.voice_asset_future: Optional[asyncio.Future] = None
        self._waiting = False

    @property
    def current_song(self) -> Optional[Song]:
        if self.is_active():
            return self.playlist[0]
        return None

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int):
        self._volume = value
        try:
            self.guild.voice_client.source.volume = float(value) / 100.0
        except AttributeError:
            pass
        except Exception:
            print("Unknown error when setting volume:", file=sys.stderr)
            print_exc(file=sys.stderr)

    def volume_up(self):
        self.volume = min(self.volume + 10, 100)

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
            await channel.connect(reconnect=True, timeout=VC_CONNECT_TIMEOUT)
        # to avoid ClientException: Not connected to voice
        await asyncio.sleep(1)

    def make_view(self):
        if not self.is_active():
            self.last_view = None
            return None

        is_empty = len(self.playlist) == 0

        self.last_view = discord.ui.View(
            MusicButton(
                lambda _: self.prev_song(),
                custom_id="prev",
                disabled=not self.playlist.has_prev(),
                emoji="⏮️",
            ),
            MusicButton(
                lambda _: self.pause(),
                custom_id="pause",
                emoji="⏸️" if self.guild.voice_client.is_playing() else "▶️",
            ),
            MusicButton(
                lambda _: self.next_song(forced=True),
                custom_id="next",
                disabled=not self.playlist.has_next(),
                emoji="⏭️",
            ),
            MusicButton(
                lambda _: self.loop(),
                custom_id="loop",
                disabled=is_empty,
                emoji="🔁",
                label="Loop: " + self.playlist.loop,
            ),
            MusicButton(
                self.current_song_callback,
                custom_id="current_song",
                row=1,
                disabled=self.current_song is None,
                emoji="💿",
            ),
            MusicButton(
                lambda _: self.shuffle(),
                custom_id="shuffle",
                row=1,
                disabled=is_empty,
                emoji="🔀",
            ),
            MusicButton(
                self.queue_callback,
                custom_id="queue",
                row=1,
                disabled=is_empty,
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
                disabled=self.volume == 10,
                emoji="🔉",
            ),
            MusicButton(
                lambda _: self.volume_up(),
                custom_id="volume_up",
                row=2,
                disabled=self.volume == 100,
                emoji="🔊",
            ),
            timeout=None,
        )

        return self.last_view

    async def current_song_callback(self, ctx):
        await ctx.send(
            embed=self.current_song.format_output(config.SONGINFO_SONGINFO),
        )

    async def queue_callback(self, ctx):
        await ctx.send(
            embed=self.playlist.queue_embed(),
        )

    async def update_view(self, view=_not_provided):
        msg = self.last_message
        if not msg:
            return
        old_view = self.last_view
        if view is None:
            self.last_message = None
        elif view is _not_provided:
            view = self.make_view()
        if view is old_view:
            return
        elif (
            old_view
            and view
            and old_view.to_components() == view.to_components()
        ):
            return
        try:
            await msg.edit(view=view)
        except discord.HTTPException as e:
            if e.code == 50027:  # Invalid Webhook Token
                try:
                    self.last_message = await msg.channel.fetch_message(msg.id)
                    await self.update_view(view)
                except discord.NotFound:
                    self.last_message = None
            else:
                print("Failed to update view:", file=sys.stderr)
                print_exc(file=sys.stderr)

    def is_active(self) -> bool:
        if self.voice_asset_future is not None:
            return False
        client = self.guild.voice_client
        return client is not None and (
            client.is_playing() or client.is_paused()
        )

    def track_history(self):
        history_string = config.INFO_HISTORY_TITLE
        for trackname in self.playlist.trackname_history:
            history_string += "\n" + trackname
        return history_string

    def pause(self):
        if self.voice_asset_future is not None:
            return PauseState.NOTHING_TO_PAUSE
        client = self.guild.voice_client
        if client:
            if client.is_playing():
                client.pause()
                self.add_task(self.timer.start(True))
                return PauseState.PAUSED
            elif client.is_paused():
                client.resume()
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

    @staticmethod
    def needs_waiting(func):
        @wraps(func)
        async def wrapped(self, *args, **kwargs):
            self.announce_waiting()
            try:
                return await func(self, *args, **kwargs)
            finally:
                self.stop_waiting()

        return wrapped

    def next_song(self, error=None, *, forced=False):
        """Invoked after a song is finished
        Plays the next song if there is one"""

        if self.is_active():
            self._next_song = self.playlist.next(forced)
            self.guild.voice_client.stop()
            return

        if self.current_song:
            self.playlist.add_name(self.current_song.title)

        if self._next_song:
            next_song = self._next_song
            self._next_song = None
        else:
            next_song = self.playlist.next(forced)

        if next_song is None:
            if not self.timer.triggered and self.guild.voice_client:
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

    @needs_waiting
    async def play_song(self, song: Song):
        """Plays a song object"""

        if not await loader.preload(song, self.bot):
            self.next_song(forced=True)
            return

        if song.data is None:
            print(
                "Something is wrong."
                " Refusing to play a song without direct url.",
                file=sys.stderr,
            )
            self.next_song(forced=True)
            return

        self.stop_waiting()
        if (
            self.voice_asset_future
            and self.current_voice_asset == VoiceAsset.HELLO
        ):
            await self.voice_asset_future
        try:
            print(song.data)
            with MonkeyPopen.args_catch_lock:
                MonkeyPopen.args_catch_future = Future()
                loader.downloader.download("-", song.data)
                print(MonkeyPopen.args_catch_future.result())
                MonkeyPopen.args_catch_future = None
            # self.guild.voice_client.play(
            #     discord.PCMVolumeTransformer(
            #         discord.FFmpegPCMAudio(
            #             song.data["url"],
            #             before_options="-reconnect 1 -reconnect_streamed 1"
            #             " -reconnect_delay_max 5",
            #             options="-loglevel error",
            #             stderr=sys.stderr,
            #         ),
            #         float(self.volume) / 100.0,
            #     ),
            #     after=self.next_song,
            # )
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
    async def process_song(
        self, track: str
    ) -> Union[Optional[Song], Literal[PLAYLIST], Literal[EMPTY_PLAYLIST]]:
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

        if self.current_song is None:
            print("Playing {}".format(track))
            await self.play_song(self.playlist[0])
        else:
            self.preload_queue()

        return loaded_song

    def add_task(self, coro: Coroutine):
        task = self.bot.loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.remove)

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

        self.guild.voice_client.stop()

    def prev_song(self) -> bool:
        """Loads the last song from the history into the queue and starts it"""

        prev_song = self.playlist.prev()
        if not prev_song:
            return False

        if not self.is_active():
            self.add_task(self.play_song(prev_song))
        else:
            self._next_song = prev_song
            self.guild.voice_client.stop()
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
        self.voice_asset_future = self.guild.voice_client.play(
            discord.FFmpegPCMAudio(asset(voice_asset)),
            wait_finish=True,
        )
        self.voice_asset_future.add_done_callback(
            self._clear_voice_asset_future
        )
        return self.voice_asset_future

    def _clear_voice_asset_future(self, _):
        self.voice_asset_future = None
        self.current_voice_asset = None

    def announce_waiting(self):
        if not config.ANNOUNCE_WAITING or self.is_active() or self._waiting:
            return

        self._waiting = True

        def continue_waiting(_):
            if self._waiting:
                self._waiting = False
                self.announce_waiting()

        if self.voice_asset_future is not None:
            self.voice_asset_future.add_done_callback(continue_waiting)
            return

        future = self.play_asset(VoiceAsset.WAIT)
        future.add_done_callback(continue_waiting)

    def stop_waiting(self):
        if not self._waiting:
            return False
        self._waiting = False
        if self.guild.voice_client:
            self.guild.voice_client.stop()
        return True

    async def uconnect(self, ctx, move=False):
        author_vc = ctx.author.voice
        bot_vc = self.guild.voice_client

        if not author_vc:
            raise CheckError(config.USER_NOT_IN_VC_MESSAGE)

        if bot_vc is None or bot_vc.channel != author_vc.channel and move:
            await ctx.defer()
            await self.register_voice_channel(author_vc.channel)
            if config.ANNOUNCE_CONNECT:
                self.play_asset(VoiceAsset.HELLO)
        else:
            raise CheckError(config.ALREADY_CONNECTED_MESSAGE)
        return True

    async def udisconnect(self):
        self.stop_player()
        await self.update_view(None)
        if self.guild.voice_client is None:
            return False
        if config.ANNOUNCE_DISCONNECT:
            try:
                await self.play_asset(VoiceAsset.GOODBYE)
            except Exception:
                print_exc(file=sys.stderr)
            else:
                # let it finish
                await asyncio.sleep(1)
        await self.guild.voice_client.disconnect(force=True)
        self.timer.cancel()
        return True
