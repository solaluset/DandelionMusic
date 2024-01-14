import re
import sys
import asyncio
from enum import Enum, auto
from typing import Optional, Union, List

import spotipy
from bs4 import BeautifulSoup
from aiohttp import ClientSession
from spotipy.oauth2 import SpotifyClientCredentials
from yt_dlp.extractor import gen_extractor_classes

from config import config
from musicbot import loader


try:
    sp_api = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=config.SPOTIFY_ID, client_secret=config.SPOTIFY_SECRET
        )
    )
    api = True
except Exception:
    api = False

EXTRACTORS = gen_extractor_classes()
YT_IE = next(ie for ie in EXTRACTORS if ie.IE_NAME == "youtube")
url_regex = re.compile(
    r"""http[s]?://(?:
        [a-zA-Z]
        |[0-9]
        |[$-_@.&+]
        |[!*\(\),]
        |(?:%[0-9a-fA-F][0-9a-fA-F])
    )+""",
    re.VERBOSE,
)
spotify_regex = re.compile(
    r"^https?://open\.spotify\.com/([^/]+/)?"
    r"(?P<type>track|playlist|album)/(?P<code>[^?]+)"
)

headers = {
    "User-Agent": " ".join(
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "AppleWebKit/537.36 (KHTML, like Gecko)",
            "Chrome/113.0.5672.126",
            "Safari/537.36",
        )
    )
}

_session = None


async def init():
    global _session
    _session = ClientSession(headers=headers)


async def stop():
    await _session.close()
    # according to aiohttp docs, we need to wait a little after closing session
    await asyncio.sleep(0.5)


async def get_soup(url: str) -> BeautifulSoup:
    async with _session.get(url) as response:
        page = await response.text()

    return BeautifulSoup(page, "html.parser")


async def fetch_spotify(url: str) -> Union[dict, List[str]]:
    """Searches YouTube for Spotify song or loads Spotify playlist"""
    match = spotify_regex.match(url)
    url_type = match.group("type")
    if url_type != "track":
        return await get_spotify_playlist(url, url_type, match.group("code"))

    soup = await get_soup(url)

    title = soup.find("title").string
    title = re.sub(
        r"(.*) - song( and lyrics)? by (.*) \| Spotify", r"\1 \3", title
    )
    return loader.search_youtube(title)


async def get_spotify_playlist(
    url: str, list_type: str, code: str
) -> List[str]:
    """Returns list of Spotify links"""

    if api:
        try:
            if list_type == "album":
                results = sp_api.album_tracks(code)
            elif list_type == "playlist":
                results = sp_api.playlist_items(code)

            if results:  # XXX: Needed?
                tracks = results["items"]
                while results["next"]:
                    results = sp_api.next(results)
                    tracks.extend(results["items"])
                links = []
                for track in tracks:
                    try:
                        links.append(
                            track.get("track", track)["external_urls"][
                                "spotify"
                            ]
                        )
                    except KeyError:
                        pass
                return links
        except Exception:
            if config.SPOTIFY_ID != "" or config.SPOTIFY_SECRET != "":
                print(
                    "ERROR: Check spotify CLIENT_ID and SECRET",
                    file=sys.stderr,
                )

    soup = await get_soup(url)
    results = soup.find_all(attrs={"name": "music:song", "content": True})

    return [item["content"] for item in results]


def get_urls(content: str) -> List[str]:
    return url_regex.findall(content)


class SiteTypes(Enum):
    SPOTIFY = auto()
    YT_DLP = auto()
    CUSTOM = auto()
    UNKNOWN = auto()


class Origins(Enum):
    Default = "Default"
    Playlist = "Playlist"


def identify_url(url: Optional[str]) -> SiteTypes:
    if url is None or not url_regex.fullmatch(url):
        return SiteTypes.UNKNOWN

    if spotify_regex.match(url):
        return SiteTypes.SPOTIFY

    for ie in EXTRACTORS:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return SiteTypes.YT_DLP

    if url.lower().endswith(
        config.SUPPORTED_EXTENSIONS
    ) and url_regex.fullmatch(url):
        return SiteTypes.CUSTOM

    # If no match
    return SiteTypes.UNKNOWN
