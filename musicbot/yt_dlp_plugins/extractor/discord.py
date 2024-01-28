import re

from yt_dlp import DownloadError
from yt_dlp.extractor.common import InfoExtractor

from config import config


class DiscordAttachmentsIE(InfoExtractor):
    _VALID_URL = (
        r"^https?://(?:canary\.)?discord\.com"
        r"/channels/(?P<guild_id>\d+)/(?P<channel_id>\d+)/(?P<message_id>\d+)"
    )

    def _real_extract(self, url):
        from musicbot.__main__ import bot
        from musicbot.loader import _loop

        if bot.http.token is None:
            _loop.run_until_complete(bot.http.static_login(config.BOT_TOKEN))

        match = re.match(self._VALID_URL, url)
        try:
            resp = _loop.run_until_complete(
                bot.http.get_message(
                    int(match.group("channel_id")),
                    int(match.group("message_id")),
                )
            )
        except Exception as e:
            raise DownloadError(str(e)) from e
        uploader = resp["author"]["username"]
        entries = [
            {
                "id": a["id"],
                "url": a["url"],
                "title": a["filename"],
                "uploader": uploader,
            }
            for a in resp["attachments"]
        ]
        return {"_type": "playlist", "entries": entries}
