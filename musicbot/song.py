from __future__ import annotations
import datetime
from typing import TYPE_CHECKING, Optional, Union

import discord

from config import config
from musicbot.linkutils import SiteTypes

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

        embed.add_field(
            name=config.SONGINFO_DURATION,
            value=(
                str(datetime.timedelta(seconds=self.duration))
                if self.duration is not None
                else config.SONGINFO_UNKNOWN
            ),
            inline=False,
        )

        return embed

    def update(self, data: Union[dict, "Song"]):
        if isinstance(data, Song):
            data = data.__dict__

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
