import datetime
from typing import Optional, Union

import discord
from config import config
from musicbot.linkutils import Origins, SiteTypes


class Song:
    def __init__(
        self,
        origin: Origins,
        host: SiteTypes,
        webpage_url: str,
        url: Optional[str] = None,
        title: Optional[str] = None,
        uploader: Optional[str] = None,
        duration: Optional[int] = None,
        thumbnail: Optional[str] = None,
    ):
        self.host = host
        self.origin = origin
        self.webpage_url = webpage_url
        self.url = url
        self.title = title
        self.uploader = uploader
        self.duration = duration
        self.thumbnail = thumbnail

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
            value=self.uploader,
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
        for k, v in data.items():
            if hasattr(self, k) and v:
                setattr(self, k, v)
