import os
import sys

from yt_dlp.plugins import load_all_plugins

__all__ = ("loader",)

# load yt-dlp plugins
sys.path.append(os.path.dirname(__file__))
load_all_plugins()

# avoid circular import error
from . import loader  # noqa: E402
