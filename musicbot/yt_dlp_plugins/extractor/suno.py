import re

from yt_dlp import DownloadError
from yt_dlp.extractor.common import InfoExtractor


class SunoAIIE(InfoExtractor):
    _VALID_URL = r"^https?://app\.suno\.ai/song/(?P<code>\w+)"

    def _real_extract(self, url):
        from musicbot.loader import _loop
        from musicbot.linkutils import get_soup

        match = re.match(self._VALID_URL, url)
        try:
            soup = _loop.run_until_complete(get_soup(url))
            return {
                "id": match.group("code"),
                "url": soup.find(property="og:audio")["content"],
                "title": re.sub(r" \| Suno$", "", soup.find("title").string),
                "thumbnail": soup.find(property="og:image")["content"],
            }
        except Exception as e:
            raise DownloadError(str(e)) from e
