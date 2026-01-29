import sys
import inspect
import threading
import subprocess
from typing import Optional, List
from concurrent.futures import Future

import yt_dlp
import discord

downloader_class = yt_dlp.get_external_downloader("ffmpeg")
_downloader_module = inspect.getmodule(downloader_class)
_original_popen = _downloader_module.Popen
_dummy_process = _original_popen(
    ["ffmpeg", "-version"], stdout=subprocess.PIPE
)


class MonkeyPopen:
    args_catch_lock = threading.Lock()
    args_catch_future: Optional[Future] = None

    def __call__(self, args, *extra, **kwargs):
        if self.args_catch_lock.locked():
            self.args_catch_future.set_result(args)
            return _dummy_process
        return _original_popen(args, *extra, **kwargs)


_downloader_module.Popen = MonkeyPopen()


class FFmpegPCMAudio(discord.FFmpegPCMAudio):
    def __init__(self, original_cmd: List[str]):
        self.original_cmd = original_cmd
        super().__init__(None, stderr=sys.stderr)

    def _spawn_process(
        self, args: List[str], **subprocess_kwargs
    ) -> subprocess.Popen:
        new_args = self.original_cmd.copy()
        new_args[1:1] = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5".split()
        )
        try:
            c_index = new_args.index("-c")
            del new_args[c_index : c_index + 2]
        except ValueError:
            pass
        f_index = new_args.index("-f")
        new_args[f_index + 1 : f_index + 2] = (
            args[args.index("-f") + 1 : -1] + "-loglevel error".split()
        )
        return super()._spawn_process(new_args, **subprocess_kwargs)
