from discord import Option, Attachment
from discord.ui import View
from discord.ext import commands, bridge

from config import config
from musicbot import linkutils, utils
from musicbot.songinfo import Song
from musicbot.bot import MusicBot, Context
from musicbot.audiocontroller import AudioController, MusicButton
from musicbot.loader import SongError, search_youtube
from musicbot.playlist import PlaylistError, LoopMode


class AudioContext(Context):
    audiocontroller: AudioController


class SongButton(MusicButton):
    def __init__(self, cog: "Music", num: int, song: str):
        async def play(ctx):
            view = self.view
            view.stop()
            view.disable_all_items()
            async with ctx.channel.typing():
                await view.message.edit(view=view)
                await cog._play_song(ctx, song)

        super().__init__(play, cog.cog_check, emoji=f"{num}⃣")


@commands.check
def active_only(ctx: AudioContext):
    if not ctx.audiocontroller.is_active():
        raise utils.CheckError(config.QUEUE_EMPTY)
    return True


class Music(commands.Cog):
    """A collection of the commands related to music playback.

    Attributes:
        bot: The instance of the bot that is executing the commands.
    """

    def __init__(self, bot: MusicBot):
        self.bot = bot

    async def cog_check(self, ctx: AudioContext):
        ctx.audiocontroller = ctx.bot.audio_controllers[ctx.guild]
        return await utils.play_check(ctx)

    async def cog_before_invoke(self, ctx: AudioContext):
        ctx.audiocontroller.command_channel = ctx

    @bridge.bridge_command(
        name="play",
        description=config.HELP_YT_LONG,
        help=config.HELP_YT_SHORT,
        aliases=["p", "yt", "pl"],
    )
    async def _play(
        self, ctx: AudioContext, *, track: str = None, file: Attachment = None
    ):
        if ctx.message and ctx.message.attachments:
            file = ctx.message.attachments[0]
        if file is not None:
            track = file.url
        elif track is None:
            await ctx.send(config.PLAY_ARGS_MISSING)
            return

        await ctx.defer()
        await self._play_song(ctx, track)

    async def _play_song(self, ctx: AudioContext, track: str):
        # reset timer
        await ctx.audiocontroller.timer.start(True)

        try:
            song = await ctx.audiocontroller.process_song(track)
        except SongError as e:
            await ctx.send(e)
            return
        if song is None:
            await ctx.send(config.SONGINFO_UNSUPPORTED)
            return

        if song.origin == linkutils.Origins.Playlist:
            await ctx.send(config.SONGINFO_PLAYLIST_QUEUED)
        else:
            if len(ctx.audiocontroller.playlist) != 1:
                await ctx.send(
                    embed=song.info.format_output(config.SONGINFO_QUEUE_ADDED)
                )
            elif not ctx.bot.settings[ctx.guild].announce_songs:
                # auto-announce is disabled, announce here
                await ctx.send(
                    embed=song.info.format_output(config.SONGINFO_NOW_PLAYING)
                )

    @bridge.bridge_command(
        name="search",
        description=config.HELP_SEARCH_LONG,
        help=config.HELP_SEARCH_SHORT,
        aliases=["sc"],
    )
    async def _search(self, ctx: AudioContext, *, query: str):
        await ctx.defer()
        results = await search_youtube(query, config.SEARCH_RESULTS)
        songs = []
        for data in results:
            song = Song(
                linkutils.Origins.Default,
                linkutils.SiteTypes.YT_DLP,
                webpage_url=data["url"],
            )
            song.update(data)
            songs.append(song)

        await ctx.send(
            embed=utils.songs_embed(config.SEARCH_EMBED_TITLE, songs),
            view=View(
                *(
                    SongButton(self, i, data["url"])
                    for i, data in enumerate(results, start=1)
                )
            ),
        )

    @bridge.bridge_command(
        name="loop",
        description=config.HELP_LOOP_LONG,
        help=config.HELP_LOOP_SHORT,
        aliases=["l"],
    )
    @active_only
    async def _loop(
        self,
        ctx: AudioContext,
        mode: Option(str, choices=tuple(m.value for m in LoopMode)) = None,
    ):
        result = ctx.audiocontroller.loop(mode)
        await ctx.send(result.value)

    @bridge.bridge_command(
        name="shuffle",
        description=config.HELP_SHUFFLE_LONG,
        help=config.HELP_SHUFFLE_SHORT,
        aliases=["sh"],
    )
    @active_only
    async def _shuffle(self, ctx: AudioContext):
        ctx.audiocontroller.shuffle()
        await ctx.send("Shuffled queue :twisted_rightwards_arrows:")

    @bridge.bridge_command(
        name="pause",
        description=config.HELP_PAUSE_LONG,
        help=config.HELP_PAUSE_SHORT,
        aliases=["resume"],
    )
    async def _pause(self, ctx: AudioContext):
        result = ctx.audiocontroller.pause()
        await ctx.send(result.value)

    @bridge.bridge_command(
        name="queue",
        description=config.HELP_QUEUE_LONG,
        help=config.HELP_QUEUE_SHORT,
        aliases=["playlist", "q"],
    )
    @active_only
    async def _queue(self, ctx: AudioContext):
        playlist = ctx.audiocontroller.playlist
        await ctx.send(embed=playlist.queue_embed())

    @bridge.bridge_command(
        name="stop",
        description=config.HELP_STOP_LONG,
        help=config.HELP_STOP_SHORT,
        aliases=["st"],
    )
    async def _stop(self, ctx: AudioContext):
        ctx.audiocontroller.stop_player()
        await ctx.send("Stopped all sessions :octagonal_sign:")

    @bridge.bridge_command(
        name="move",
        description=config.HELP_MOVE_LONG,
        help=config.HELP_MOVE_SHORT,
        aliases=["mv"],
    )
    @active_only
    async def _move(
        self,
        ctx: AudioContext,
        src_pos: Option(int, min_value=2),
        dest_pos: Option(int, min_value=2) = None,
    ):
        if dest_pos is None:
            dest_pos = len(ctx.audiocontroller.playlist)

        try:
            ctx.audiocontroller.playlist.move(src_pos - 1, dest_pos - 1)
            ctx.audiocontroller.preload_queue()
            await ctx.send("Moved ↔️")
        except PlaylistError as e:
            await ctx.send(e)

    @bridge.bridge_command(
        name="remove",
        description=config.HELP_REMOVE_LONG,
        help=config.HELP_REMOVE_SHORT,
        aliases=["rm"],
    )
    @active_only
    async def _remove(
        self, ctx: AudioContext, queue_number: Option(int, min_value=2) = None
    ):
        if queue_number is None:
            queue_number = len(ctx.audiocontroller.playlist)
        try:
            song = ctx.audiocontroller.playlist.remove(queue_number - 1)
            ctx.audiocontroller.preload_queue()
            title = song.info.title or song.info.webpage_url
            await ctx.send(f"Removed #{queue_number}: {title}")
        except PlaylistError as e:
            await ctx.send(e)

    @bridge.bridge_command(
        name="skip",
        description=config.HELP_SKIP_LONG,
        help=config.HELP_SKIP_SHORT,
        aliases=["s", "next"],
    )
    @active_only
    async def _skip(self, ctx: AudioContext):
        ctx.audiocontroller.next_song(forced=True)
        await ctx.send("Skipped current song :fast_forward:")

    @bridge.bridge_command(
        name="clear",
        description=config.HELP_CLEAR_LONG,
        help=config.HELP_CLEAR_SHORT,
        aliases=["cl"],
    )
    async def _clear(self, ctx: AudioContext):
        ctx.audiocontroller.playlist.clear()
        await ctx.send("Cleared queue :no_entry_sign:")

    @bridge.bridge_command(
        name="prev",
        description=config.HELP_PREV_LONG,
        help=config.HELP_PREV_SHORT,
        aliases=["back"],
    )
    async def _prev(self, ctx: AudioContext):
        if ctx.audiocontroller.prev_song():
            await ctx.send("Playing previous song :track_previous:")
        else:
            await ctx.send("No previous track.")

    @bridge.bridge_command(
        name="songinfo",
        description=config.HELP_SONGINFO_LONG,
        help=config.HELP_SONGINFO_SHORT,
        aliases=["np"],
    )
    @active_only
    async def _songinfo(self, ctx: AudioContext):
        song = ctx.audiocontroller.current_song
        await ctx.send(embed=song.info.format_output(config.SONGINFO_SONGINFO))

    @bridge.bridge_command(
        name="history",
        description=config.HELP_HISTORY_LONG,
        help=config.HELP_HISTORY_SHORT,
    )
    async def _history(self, ctx: AudioContext):
        await ctx.send(ctx.audiocontroller.track_history())

    @bridge.bridge_command(
        name="volume",
        aliases=["vol"],
        description=config.HELP_VOL_LONG,
        help=config.HELP_VOL_SHORT,
    )
    async def _volume(
        self,
        ctx: AudioContext,
        value: Option(int, min_value=0, max_value=100) = None,
    ):
        if value is None:
            await ctx.send(
                "Current volume: {}% :speaker:".format(
                    ctx.audiocontroller.volume
                )
            )
            return

        if value > 100 or value < 0:
            await ctx.send("Error: Volume must be a number 1-100")
            return

        if ctx.audiocontroller.volume >= value:
            await ctx.send("Volume set to {}% :sound:".format(str(value)))
        else:
            await ctx.send("Volume set to {}% :loud_sound:".format(str(value)))
        ctx.audiocontroller.volume = value


def setup(bot: MusicBot):
    bot.add_cog(Music(bot))
