import inspect
import threading
from typing import Optional
from concurrent.futures import Future

import yt_dlp

downloader_class = yt_dlp.get_external_downloader("ffmpeg")
_downloader_module = inspect.getmodule(downloader_class)
_original_popen = _downloader_module.Popen
_dummy_process = _original_popen(["ffmpeg", "-version"])


class MonkeyPopen:
    args_catch_lock = threading.Lock()
    args_catch_future: Optional[Future] = None

    def __call__(self, args, *extra, **kwargs):
        if self.args_catch_lock.locked():
            self.args_catch_future.set_result(args)
            return _dummy_process
        return _original_popen(args, *extra, **kwargs)


_downloader_module.Popen = MonkeyPopen()
