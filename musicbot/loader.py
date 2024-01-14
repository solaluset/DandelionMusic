import sys
import atexit
import asyncio
import threading
from urllib.request import urlparse
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context as mp_context
from typing import List, Optional, Union

from yt_dlp import YoutubeDL, DownloadError

from config import config
from musicbot.songinfo import Song
from musicbot.utils import OutputWrapper
from musicbot.linkutils import (
    YT_IE,
    Origins,
    SiteTypes,
    fetch_spotify,
    identify_url,
    url_regex,
    init as init_session,
    stop as stop_session,
)


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
_loop.run_until_complete(init_session())
atexit.register(lambda: _loop.run_until_complete(stop_session()))
_executor = ProcessPoolExecutor(1, _context)
_downloader = YoutubeDL(
    {
        "format": "bestaudio/best",
        "extract_flat": True,
        "noplaylist": True,
        # default_search shouldn't be needed as long as
        # we don't pass plain text to the downloader.
        # still leaving it just in case
        "default_search": "auto",
        "cookiefile": config.COOKIE_PATH,
        "quiet": True,
    }
)
_preloading = {}
_search_lock = threading.Lock()


class SongError(Exception):
    pass


def _noop():
    pass


def init():
    # wake it up to spawn the process immediately
    _executor.submit(_noop).result()


def extract_info(url: str) -> Optional[dict]:
    # TODO: different locks for different sites?
    with _search_lock:
        try:
            return _downloader.extract_info(url, False)
        except DownloadError:
            return None


def search_youtube(title: str) -> Optional[dict]:
    """Searches youtube for the video title
    Returns the first results video link"""

    r = extract_info("ytsearch:" + title)

    if not r:
        return None

    return r["entries"][0]


async def load_song(track: str) -> Union[Optional[Song], List[Song]]:
    return await _run_sync(_load_song, track)


def _load_song(track: str) -> Union[Optional[Song], List[Song]]:
    host = identify_url(track)

    if host == SiteTypes.UNKNOWN:
        if url_regex.fullmatch(track):
            return None

        data = search_youtube(track)
        host = SiteTypes.YT_DLP

    elif host == SiteTypes.SPOTIFY:
        data = _loop.run_until_complete(fetch_spotify(track))

    elif host == SiteTypes.YT_DLP:
        data = extract_info(track)

    elif host == SiteTypes.CUSTOM:
        data = {
            "url": track,
            "webpage_url": track,
            "title": track.rpartition("/")[2],
            "uploader": config.SONGINFO_UNKNOWN,
        }

    if not data:
        return None

    if isinstance(data, dict):
        if "entries" in data:
            # assuming a playlist
            data = [entry["url"] for entry in data["entries"]]
        elif YT_IE.suitable(data["url"]):
            # the URL wasn't extracted, do it now
            data = extract_info(data["url"])
            if not data:
                return None

    if isinstance(data, list):
        return [
            Song(
                Origins.Playlist,
                host,
                webpage_url=entry,
            )
            for entry in data
        ]

    song = Song(Origins.Default, host, webpage_url=track)
    song.update(data)

    return song


def _preload(song: Song) -> Optional[Song]:
    loaded = _load_song(song.info.webpage_url)
    if loaded:
        return loaded
    return None


def _parse_expire(url: str) -> Optional[int]:
    expire = (
        ("&" + urlparse(url).query).partition("&expire=")[2].partition("&")[0]
    )
    try:
        return int(expire)
    except ValueError:
        return None


async def preload(song: Song) -> bool:
    if song.info.webpage_url is None:
        return True

    if song.base_url is not None:
        expire = _parse_expire(song.base_url)
        if expire is None or expire == _parse_expire(song.info.webpage_url):
            return True
        if datetime.now(timezone.utc) < datetime.fromtimestamp(
            expire, timezone.utc
        ):
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
