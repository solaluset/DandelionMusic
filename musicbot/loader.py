import sys
import asyncio
import threading
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context as mp_context
from typing import List, Tuple, Optional, Union

import yt_dlp

from config import config
from musicbot import linkutils
from musicbot.songinfo import Song
from musicbot.utils import OutputWrapper


sys.stdout = OutputWrapper(sys.stdout)
sys.stderr = OutputWrapper(sys.stderr)

_context = mp_context("spawn")


class LoaderProcess(_context.Process):
    def run(self):
        try:
            super().run()
        # suppress noisy errors that happen on Ctrl+C
        except (KeyboardInterrupt, InterruptedError):
            pass


_context.Process = LoaderProcess

_loop = asyncio.new_event_loop()
_executor = ProcessPoolExecutor(1, _context)
_cached_downloaders: List[Tuple[dict, yt_dlp.YoutubeDL]] = []
_preloading = {}
_search_lock = threading.Lock()


class SongError(Exception):
    pass


def _noop():
    pass


def init():
    # wake it up to spawn the process immediately
    _executor.submit(_noop).result()


def extract_info(url: str, options: dict) -> dict:
    downloader = None
    for o, d in _cached_downloaders:
        if o == options:
            downloader = d
            break
    else:
        # we need to copy options because
        # downloader modifies the given dict
        downloader = yt_dlp.YoutubeDL(options.copy())
        _cached_downloaders.append((options, downloader))
    with _search_lock:
        return downloader.extract_info(url, False)


def fetch_song_info(song: Song) -> bool:
    try:
        info = extract_info(
            song.info.webpage_url,
            {
                "format": "bestaudio",
                "title": True,
                "cookiefile": config.COOKIE_PATH,
                "quiet": True,
            },
        )
    except Exception as e:
        if isinstance(e, yt_dlp.DownloadError) and e.exc_info[1].expected:
            return False
        info = extract_info(
            song.info.webpage_url,
            {
                "title": True,
                "cookiefile": config.COOKIE_PATH,
                "quiet": True,
            },
        )
    song.update(info)
    return True


def search_youtube(title: str) -> Optional[dict]:
    """Searches youtube for the video title
    Returns the first results video link"""

    options = {
        "format": "bestaudio/best",
        "default_search": "auto",
        "noplaylist": True,
        "cookiefile": config.COOKIE_PATH,
        "quiet": True,
    }

    r = extract_info("ytsearch:" + title, options)

    if not r:
        return None

    return r["entries"][0]


async def load_song(track: str) -> Union[Optional[Song], List[Song]]:
    return await _run_sync(_load_song, track)


def _load_song(track: str) -> Union[Optional[Song], List[Song]]:
    host = linkutils.identify_url(track)
    is_playlist = linkutils.identify_playlist(track)

    if is_playlist != linkutils.Playlist_Types.Unknown:
        return load_playlist(is_playlist, track)

    data = None

    if host == linkutils.Sites.Unknown:
        if linkutils.get_urls(track):
            return None

        data = search_youtube(track)

    elif host == linkutils.Sites.Spotify:
        title = _loop.run_until_complete(linkutils.convert_spotify(track))
        data = search_youtube(title)

    elif host == linkutils.Sites.YouTube:
        track = track.split("&list=")[0]

    elif host == linkutils.Sites.Custom:
        data = {
            "url": track,
            "webpage_url": track,
            "title": track.rpartition("/")[2],
            "uploader": config.SONGINFO_UNKNOWN,
        }

    song = Song(linkutils.Origins.Default, host, webpage_url=track)
    if data:
        song.update(data)
    else:
        if not fetch_song_info(song):
            raise SongError(config.SONGINFO_ERROR)

    return song


def load_playlist(
    playlist_type: linkutils.Playlist_Types, url: str
) -> List[Song]:
    if playlist_type == linkutils.Playlist_Types.YouTube_Playlist:
        options = {
            "format": "bestaudio/best",
            "extract_flat": True,
            "cookiefile": config.COOKIE_PATH,
            "quiet": True,
        }

        r = extract_info(url, options)

        return [
            Song(
                linkutils.Origins.Playlist,
                linkutils.Sites.YouTube,
                webpage_url=f"https://www.youtube.com/watch?v={entry['id']}",
            )
            for entry in r["entries"]
        ]

    if playlist_type == linkutils.Playlist_Types.Spotify_Playlist:
        links = _loop.run_until_complete(linkutils.get_spotify_playlist(url))
        return [
            Song(
                linkutils.Origins.Playlist,
                linkutils.Sites.Spotify,
                webpage_url=link,
            )
            for link in links
        ]

    if playlist_type == linkutils.Playlist_Types.BandCamp_Playlist:
        options = {
            "format": "bestaudio/best",
            "extract_flat": True,
            "quiet": True,
        }
        r = extract_info(url, options)
        return [
            Song(
                linkutils.Origins.Playlist,
                linkutils.Sites.Bandcamp,
                webpage_url=entry["url"],
            )
            for entry in r["entries"]
        ]


def _preload(song: Song) -> Optional[Song]:
    if song.host == linkutils.Sites.Spotify:
        title = _loop.run_until_complete(
            linkutils.convert_spotify(song.info.webpage_url)
        )
        data = search_youtube(title)
        if data:
            song.update(data)
            return song
        else:
            return None

    elif fetch_song_info(song):
        return song
    return None


async def preload(song: Song) -> bool:
    if song.info.title is not None or song.info.webpage_url is None:
        return True
    future = _preloading.get(song)
    if future:
        return await future
    _preloading[song] = asyncio.Future()

    preloaded = await _run_sync(_preload, song)
    success = preloaded is not None
    if success:
        song.update(preloaded)

    _preloading.pop(song).set_result(success)
    return success


async def _run_sync(f, *args):
    return await asyncio.get_running_loop().run_in_executor(
        _executor, f, *args
    )
