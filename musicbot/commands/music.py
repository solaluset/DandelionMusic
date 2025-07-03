import json
from typing import Iterable, List, Union

from discord import Attachment, AutocompleteContext, Embed
from discord.ui import View
from discord.ext import commands, bridge
from discord.ext.bridge import BridgeOption
from discord.ext.pages import Paginator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from config import config
from musicbot import linkutils, utils, loader
from musicbot.song import Song
from musicbot.bot import MusicBot, Context
from musicbot.utils import dj_check, chunks
from musicbot.audiocontroller import PLAYLIST, AudioController, MusicButton
from musicbot.loader import SongError, search_youtube
from musicbot.playlist import PlaylistError, LoopMode
from musicbot.settings import SavedPlaylist
from musicbot.linkutils import get_site_type, url_regex


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
        aliases=["p", "yt"],
    )
    async def _play(
        self, ctx: AudioContext, *, track: str = None, file: Attachment = None
    ):
        if track is None:
            if ctx.message:
                if ctx.message.attachments:
                    track = ctx.message.jump_url
                elif (
                    ctx.message.reference
                    and ctx.message.reference.resolved
                    and ctx.message.reference.resolved.attachments
                ):
                    track = ctx.message.reference.resolved.jump_url
            elif file:
                track = file.url
        if track is None:
            await ctx.send(config.PLAY_ARGS_MISSING)
            return

        await ctx.defer()
        await self._play_song(ctx, track)

    async def _play_song(
        self, ctx: AudioContext, track: Union[str, Iterable[str]]
    ):
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

        if song is PLAYLIST:
            await ctx.send(config.SONGINFO_PLAYLIST_QUEUED)
        else:
            if len(ctx.audiocontroller.playlist) != 1:
                await ctx.send(
                    embed=song.format_output(config.SONGINFO_QUEUE_ADDED)
                )
            elif not ctx.bot.settings[ctx.guild].announce_songs:
                # auto-announce is disabled, announce here
                await ctx.send(
                    embed=song.format_output(config.SONGINFO_NOW_PLAYING)
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
                ),
                disable_on_timeout=True,
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
        mode: BridgeOption(
            str, choices=tuple(m.value for m in LoopMode)
        ) = None,
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
        aliases=["q"],
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
        src_pos: BridgeOption(int, min_value=2),
        dest_pos: BridgeOption(int, min_value=2) = None,
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
        self,
        ctx: AudioContext,
        queue_number: BridgeOption(int, min_value=2) = None,
    ):
        if queue_number is None:
            queue_number = len(ctx.audiocontroller.playlist)
        try:
            song = ctx.audiocontroller.playlist.remove(queue_number - 1)
            ctx.audiocontroller.preload_queue()
            title = song.title or song.webpage_url
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
        await ctx.send(embed=song.format_output(config.SONGINFO_SONGINFO))

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
        value: BridgeOption(int, min_value=0, max_value=100) = None,
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

    async def _playlist_autocomplete(
        self, ctx: AutocompleteContext
    ) -> List[str]:
        async with ctx.bot.DbSession() as session:
            return (
                await session.execute(
                    select(SavedPlaylist.name)
                    .where(
                        SavedPlaylist.guild_id == str(ctx.interaction.guild.id)
                    )
                    .where(SavedPlaylist.name.startswith(ctx.value))
                )
            ).scalars()

    @bridge.bridge_group(
        name="playlist",
        aliases=["pl"],
        invoke_without_command=True,
    )
    async def _playlist(self, ctx: AudioContext):
        await ctx.send("Use subcommands to manage playlists.")

    @_playlist.command(
        name="save",
        aliases=["s"],
        description=config.HELP_SAVE_PLAYLIST_LONG,
        help=config.HELP_SAVE_PLAYLIST_SHORT,
    )
    @commands.check(dj_check)
    async def _playlist_save(self, ctx: AudioContext, name: str):
        if not config.ENABLE_PLAYLISTS:
            await ctx.send(config.PLAYLISTS_ARE_DISABLED)
            return

        await ctx.defer()
        songs = [
            {"url": song.webpage_url, "title": song.title}
            for song in ctx.audiocontroller.playlist.playque
        ]
        if not songs:
            await ctx.send(config.QUEUE_EMPTY)
            return
        async with ctx.bot.DbSession() as session:
            session.add(
                SavedPlaylist(
                    guild_id=str(ctx.guild.id),
                    name=name,
                    songs_json=json.dumps(songs),
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await ctx.send(config.PLAYLIST_ALREADY_EXISTS)
                return
        await ctx.send(config.PLAYLIST_SAVED_MESSAGE)

    @_playlist.command(
        name="load",
        aliases=["l"],
        description=config.HELP_LOAD_PLAYLIST_LONG,
        help=config.HELP_LOAD_PLAYLIST_SHORT,
    )
    async def _playlist_load(
        self,
        ctx: AudioContext,
        name: BridgeOption(str, autocomplete=_playlist_autocomplete),
    ):
        await ctx.defer()
        async with ctx.bot.DbSession() as session:
            playlist = (
                await session.execute(
                    select(SavedPlaylist)
                    .where(SavedPlaylist.guild_id == str(ctx.guild.id))
                    .where(SavedPlaylist.name == name)
                )
            ).scalar_one_or_none()
        if playlist is None:
            await ctx.send(config.PLAYLIST_NOT_FOUND)
            return
        for song_data in json.loads(playlist.songs_json):
            ctx.audiocontroller.playlist.add(
                Song(
                    get_site_type(song_data["url"]),
                    song_data["url"],
                    title=song_data["title"],
                    playlist=playlist,
                )
            )
        if not ctx.audiocontroller.is_active():
            await ctx.audiocontroller.play_song(
                ctx.audiocontroller.playlist[0]
            )
        else:
            ctx.audiocontroller.preload_queue()
        await ctx.send(config.SONGINFO_PLAYLIST_QUEUED)

    @_playlist.command(
        name="remove",
        aliases=["r"],
        description=config.HELP_REMOVE_PLAYLIST_LONG,
        help=config.HELP_REMOVE_PLAYLIST_SHORT,
    )
    @commands.check(dj_check)
    async def _playlist_remove(
        self,
        ctx: AudioContext,
        name: BridgeOption(str, autocomplete=_playlist_autocomplete),
    ):
        await ctx.defer()
        async with ctx.bot.DbSession() as session:
            result = await session.execute(
                delete(SavedPlaylist)
                .where(SavedPlaylist.guild_id == str(ctx.guild.id))
                .where(SavedPlaylist.name == name)
            )
            await session.commit()
        if result.rowcount == 0:
            await ctx.send(config.PLAYLIST_NOT_FOUND)
            return
        await ctx.send(config.PLAYLIST_REMOVED)

    @_playlist.command(
        name="list",
        aliases=["li"],
        description=config.HELP_LIST_PLAYLISTS_LONG,
        help=config.HELP_LIST_PLAYLISTS_SHORT,
    )
    async def _playlist_list(self, ctx: AudioContext):
        async with ctx.bot.DbSession() as session:
            playlists = (
                (
                    await session.execute(
                        select(SavedPlaylist.name).where(
                            SavedPlaylist.guild_id == str(ctx.guild.id)
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not playlists:
            await ctx.send("No playlists.")
            return

        playlist_names = "\n".join(f"- {name}" for name in playlists)
        await ctx.send(f"**Playlists:**\n{playlist_names}")

    @_playlist.command(
        name="show",
        aliases=["sw"],
        description=config.HELP_PLAYLIST_SHOW_LONG,
        help=config.HELP_PLAYLIST_SHOW_SHORT,
    )
    @commands.check(dj_check)
    async def _playlist_show(
        self,
        ctx: AudioContext,
        playlist: BridgeOption(str, autocomplete=_playlist_autocomplete),
    ):
        await ctx.defer()

        async with ctx.bot.DbSession() as session:
            playlist = (
                await session.execute(
                    select(SavedPlaylist)
                    .where(SavedPlaylist.guild_id == str(ctx.guild.id))
                    .where(SavedPlaylist.name == playlist)
                )
            ).scalar_one_or_none()
        if playlist is None:
            await ctx.send(config.PLAYLIST_NOT_FOUND)
            return
        pages = []
        i = 1
        for part in chunks(json.loads(playlist.songs_json), 25):
            embed = Embed(title=playlist.name)
            for song in part:
                url = song["url"]
                title = song["title"] or url_regex.fullmatch(url).group("bare")
                embed.add_field(
                    name=str(i), value=f"[{title}]({url})", inline=False
                )
                i += 1
            pages.append(embed)
        await Paginator(pages).send(ctx)

    @_playlist.command(
        name="add_song",
        aliases=["as"],
        description=config.HELP_ADD_TO_PLAYLIST_LONG,
        help=config.HELP_ADD_TO_PLAYLIST_SHORT,
    )
    @commands.check(dj_check)
    async def _playlist_add_song(
        self,
        ctx: AudioContext,
        playlist: BridgeOption(str, autocomplete=_playlist_autocomplete),
        track: str,
    ):
        await ctx.defer()
        song = await loader.load_song(track)
        if song is None:
            await ctx.send(config.SONGINFO_ERROR)
            return
        if isinstance(song, Song):
            urls = [song.webpage_url]
        else:
            urls = [s.webpage_url for s in song]

        async with ctx.bot.DbSession() as session:
            playlist = (
                await session.execute(
                    select(SavedPlaylist)
                    .where(SavedPlaylist.guild_id == str(ctx.guild.id))
                    .where(SavedPlaylist.name == playlist)
                )
            ).scalar_one_or_none()
            if playlist is None:
                await ctx.send(config.PLAYLIST_NOT_FOUND)
                return
            playlist.songs_json = json.dumps(
                json.loads(playlist.songs_json) + urls
            )
            await session.commit()
        await ctx.send(config.PLAYLIST_UPDATED)

    @_playlist.command(
        name="remove_song",
        aliases=["rs"],
        description=config.HELP_REMOVE_FROM_PLAYLIST_LONG,
        help=config.HELP_REMOVE_FROM_PLAYLIST_SHORT,
    )
    @commands.check(dj_check)
    async def _playlist_remove_song(
        self,
        ctx: AudioContext,
        playlist: BridgeOption(str, autocomplete=_playlist_autocomplete),
        position: int,
    ):
        await ctx.defer()

        async with ctx.bot.DbSession() as session:
            playlist = (
                await session.execute(
                    select(SavedPlaylist)
                    .where(SavedPlaylist.guild_id == str(ctx.guild.id))
                    .where(SavedPlaylist.name == playlist)
                )
            ).scalar_one_or_none()
            if playlist is None:
                await ctx.send(config.PLAYLIST_NOT_FOUND)
                return
            songs = json.loads(playlist.songs_json)
            if position <= 0 or position > len(songs):
                await ctx.send(
                    f"Invalid position. Playlist has {len(songs)} songs."
                )
                return
            if len(songs) == 1:
                await ctx.send("Can't remove the only song from playlist.")
                return
            del songs[position - 1]
            playlist.songs_json = json.dumps(songs)
            await session.commit()
        await ctx.send(config.PLAYLIST_UPDATED)

    @_playlist.command(
        name="move_song",
        aliases=["ms"],
        description=config.HELP_MOVE_IN_PLAYLIST_LONG,
        help=config.HELP_MOVE_IN_PLAYLIST_SHORT,
    )
    @commands.check(dj_check)
    async def _playlist_move_song(
        self,
        ctx: AudioContext,
        playlist: BridgeOption(str, autocomplete=_playlist_autocomplete),
        source_position: int,
        destination_position: int,
    ):
        await ctx.defer()

        async with ctx.bot.DbSession() as session:
            playlist = (
                await session.execute(
                    select(SavedPlaylist)
                    .where(SavedPlaylist.guild_id == str(ctx.guild.id))
                    .where(SavedPlaylist.name == playlist)
                )
            ).scalar_one_or_none()
            if playlist is None:
                await ctx.send(config.PLAYLIST_NOT_FOUND)
                return
            songs = json.loads(playlist.songs_json)
            if min(source_position, destination_position) <= 0 or max(
                source_position, destination_position
            ) > len(songs):
                await ctx.send(
                    f"Invalid position. Playlist has {len(songs)} songs."
                )
                return
            songs.insert(
                destination_position - 1, songs.pop(source_position - 1)
            )
            playlist.songs_json = json.dumps(songs)
            await session.commit()
        await ctx.send(config.PLAYLIST_UPDATED)


def setup(bot: MusicBot):
    bot.add_cog(Music(bot))
