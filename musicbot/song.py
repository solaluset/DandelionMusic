from __future__ import annotations
import datetime
from urllib.parse import urlparse, parse_qs
from typing import TYPE_CHECKING, Optional, Union

import discord

from config import config
from musicbot.linkutils import SiteTypes
from musicbot.timeparse import timeparse

if TYPE_CHECKING:
    from musicbot.settings import SavedPlaylist


class Song:
    def __init__(
        self,
        host: SiteTypes,
        webpage_url: str,
        data: Optional[dict] = None,
        title: Optional[str] = None,
        uploader: Optional[str] = None,
        duration: Optional[int] = None,
        thumbnail: Optional[str] = None,
        playlist: Optional[SavedPlaylist] = None,
    ):
        self.host = host
        self.webpage_url = webpage_url
        self.data = data
        self.title = title
        self.uploader = uploader
        self.duration = duration
        self.thumbnail = thumbnail
        self.playlist = playlist

        start = end = None
        params = parse_qs(urlparse(webpage_url).query)
        if params.get("start"):
            start = timeparse(params["start"][0])
        if params.get("end"):
            end = timeparse(params["end"][0])

        self._start = start
        self._end = end

    def format_output(self, playtype: str) -> discord.Embed:
        embed = discord.Embed(
            title=playtype,
            description="[{}]({})".format(self.title, self.webpage_url),
            color=config.EMBED_COLOR,
        )

        if self.thumbnail is not None:
            embed.set_thumbnail(url=self.thumbnail)

        embed.add_field(
            name=config.SONGINFO_UPLOADER,
            value=self.uploader or config.SONGINFO_UNKNOWN,
            inline=False,
        )

        duration = self.duration
        if self.data and (
            self.data.get("section_start") or self.data.get("section_end")
        ):
            end = self.data.get("section_end", duration)
            if end:
                duration = end - self.data.get("section_start", 0)

        embed.add_field(
            name=config.SONGINFO_DURATION,
            value=(
                str(datetime.timedelta(seconds=duration))
                if duration is not None
                else config.SONGINFO_UNKNOWN
            ),
            inline=False,
        )

        return embed

    def update(self, data: Union[dict, "Song"]):
        if isinstance(data, Song):
            data = data.__dict__
        else:
            start_time = data.get("start_time", self._start)
            if start_time:
                data["section_start"] = start_time
            end_time = data.get("end_time", self._end)
            if end_time:
                data["section_end"] = end_time

            self.data = data

        thumbnails = data.get("thumbnails")
        if thumbnails:
            # last thumbnail has the best resolution
            data["thumbnail"] = thumbnails[-1]["url"]

        from musicbot.settings import SavedPlaylist

        if "playlist" in data and not isinstance(
            data["playlist"], SavedPlaylist
        ):
            del data["playlist"]
        for k, v in data.items():
            if hasattr(self, k) and v:
                setattr(self, k, v)
