import re
from hashlib import sha256

from yt_dlp import DownloadError
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import traverse_obj

from config import config


class DiscordMessageIE(InfoExtractor):
    _VALID_URL = (
        r"^https?://(?:canary\.)?discord\.com"
        r"/channels/(?P<guild_id>\d+)/(?P<channel_id>\d+)/(?P<message_id>\d+)"
    )

    def _extract_tracks(self, msg_data: dict) -> list[dict]:
        from musicbot.linkutils import SiteTypes, get_urls, identify_url

        msg_author = traverse_obj(msg_data, ("author", "username"))
        tracks = []

        for i, url in enumerate(get_urls(msg_data.get("content", ""))):
            if identify_url(url) == SiteTypes.UNKNOWN:
                continue
            tracks.append(
                {
                    "id": sha256(url.encode()).hexdigest(),
                    "_type": "url",
                    "url": url,
                }
            )

        for a in msg_data.get("attachments", []):
            tracks.append(
                {
                    "id": a["id"],
                    "url": a["url"],
                    "title": a["filename"],
                    "uploader": msg_author,
                }
            )

        if tracks:
            # found link or attachment, stop here
            return tracks

        for snapshot in msg_data.get("message_snapshots", []):
            tracks.extend(self._extract_tracks(snapshot["message"]))

        if tracks:
            # found link/attachment in snapshot (forwarded message)
            return tracks

        if ref_msg := msg_data.get("referenced_message"):
            tracks.extend(self._extract_tracks(ref_msg))

        return tracks

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

        return {"_type": "playlist", "entries": self._extract_tracks(resp)}
