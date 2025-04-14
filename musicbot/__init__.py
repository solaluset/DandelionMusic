__all__ = ("loader",)

import os
import sys

# to load yt-dlp plugin
sys.path.append(os.path.dirname(__file__))

# avoid circular import error
from . import loader  # noqa: E402
