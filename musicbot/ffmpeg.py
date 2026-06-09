import sys
import time
import inspect
import threading
import subprocess
from queue import deque
from functools import reduce
from traceback import print_exc
from dataclasses import dataclass
from collections import defaultdict
from typing import Callable, Dict, Optional, List, Tuple, Iterable
from concurrent.futures import Future

import yt_dlp
import audioop
from discord import AudioSource, FFmpegPCMAudio as BasePCMAudio, VoiceClient
from discord.opus import Encoder as OpusEncoder

from config import config
from musicbot.song import Song

OriginalArgs = Tuple[List[str], Optional[dict]]

downloader_class = yt_dlp.get_external_downloader("ffmpeg")
_downloader_module = inspect.getmodule(downloader_class)
_original_popen = _downloader_module.Popen
_dummy_process = _original_popen(
    ["ffmpeg", "-version"], stdout=subprocess.PIPE
)


class MonkeyPopen:
    args_catch_lock = threading.Lock()
    args_catch_future: Optional[Future] = None

    def __call__(self, args, *extra, env: Optional[dict] = None, **kwargs):
        if self.args_catch_lock.locked():
            self.args_catch_future.set_result((args, env))
            return _dummy_process
        return _original_popen(args, *extra, env=env, **kwargs)


_downloader_module.Popen = MonkeyPopen()


def _get_ffmpeg_args(song: Song) -> OriginalArgs:
    from musicbot.loader import _downloader

    with MonkeyPopen.args_catch_lock:
        try:
            MonkeyPopen.args_catch_future = Future()
            _downloader.download("-", song.data)
            return MonkeyPopen.args_catch_future.result()
        finally:
            MonkeyPopen.args_catch_future = None


class FFmpegPCMAudio(BasePCMAudio):
    def __init__(self, original_args: OriginalArgs):
        self.original_args, self.original_env = original_args
        super().__init__(None, stderr=sys.stderr)

    def _spawn_process(
        self, args: List[str], **subprocess_kwargs
    ) -> subprocess.Popen:
        new_args = self.original_args.copy()
        new_args[1:1] = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5".split()
        )
        try:
            c_index = new_args.index("-c")
            del new_args[c_index : c_index + 2]
        except ValueError:
            pass
        f_index = new_args.index("-f")
        new_args[f_index : f_index + 2] = (
            "-af loudnorm".split()
            + args[args.index("-f") : -1]
            + "-loglevel error".split()
        )
        subprocess_kwargs["env"] = self.original_env
        return super()._spawn_process(new_args, **subprocess_kwargs)


@dataclass
class AudioStream:
    source: AudioSource
    after: Optional[Callable[[], None]] = None
    paused: bool = False
    rewindable: bool = False


class AudioMixer(AudioSource):
    SILENCE = b"\0" * OpusEncoder.FRAME_SIZE
    FRAMES_PER_SECOND = round(1000 / OpusEncoder.FRAME_LENGTH)
    MAX_REWIND_FRAMES = FRAMES_PER_SECOND * config.MAX_REWIND_SECONDS

    def __init__(self, client: VoiceClient):
        self.client = client
        self.streams: Dict[int, AudioStream] = {}
        self.rewinds: defaultdict[int, deque[bytes]] = defaultdict(
            lambda: deque(maxlen=self.MAX_REWIND_FRAMES)
        )
        self._stop_future = Future()
        self._stop_future.cancel()

    def read(self) -> bytes:
        return reduce(
            lambda a, b: audioop.add(a, b, 2),
            self._read_streams(),
            self.SILENCE,
        )

    def _read_streams(self) -> Iterable[AudioStream]:
        for id_ in tuple(self.streams):
            stream = self.streams[id_]
            if stream.paused:
                continue

            ret = stream.source.read()
            if not ret:
                self._stop_stream_once(id_)
                continue

            if stream.rewindable:
                self.rewinds[id_].append(ret)

            yield ret

    def cleanup(self) -> None:
        for id_ in tuple(self.streams):
            self.stop_stream(id_)

    def add_stream(
        self,
        source: AudioSource,
        *,
        id_: Optional[int] = None,
        after: Optional[Callable[[], None]] = None,
        rewindable: bool = False,
    ) -> None:
        if source.is_opus():
            raise ValueError("source must not be Opus-encoded")

        if id_ is None:
            id_ = max(self.streams, default=0) + 1
        elif id_ in self.streams:
            raise ValueError(f"stream with id {id_} already exists")
        self.streams[id_] = AudioStream(
            source, after=after, rewindable=rewindable
        )

        self._stop_future.cancel()
        if not self.client.is_playing():
            self.client.play(self)

    def get_stream(self, id_: int) -> Optional[AudioStream]:
        return self.streams.get(id_)

    def stop_stream(self, id_: int) -> None:
        stream = self.streams.get(id_)
        if stream and isinstance(stream.source, AudioRewind):
            # stop the rewind
            self._stop_stream_once(id_)
        # stop actual stream
        self._stop_stream_once(id_)

    def _stop_stream_once(self, id_: int) -> None:
        stream = self.streams.pop(id_, None)
        if stream and stream.after:
            try:
                stream.after()
            except Exception:
                print_exc(file=sys.stderr)

        if not self.streams and self.client.is_playing():
            self._stop_future.cancel()

            def stop():
                time.sleep(1)
                if not future.set_running_or_notify_cancel():
                    return
                self.client.stop()
                future.set_result(None)

            future = self._stop_future = Future()
            threading.Thread(target=stop, daemon=True).start()

    def fast_forward_stream(self, id_: int, frame_count: int) -> None:
        stream = self.streams.get(id_)
        if not stream:
            return

        stream.paused = True
        for _ in range(frame_count):
            if not stream.paused or not stream.source.read():
                break
        stream.paused = False

    def rewind_stream(self, id_: int, frame_count: int) -> int:
        current_stream = self.streams.get(id_)
        if current_stream and isinstance(current_stream.source, AudioRewind):
            # this stream is already a rewind, unwrap
            self._stop_stream_once(id_)

        current_stream = self.streams.pop(id_, None)

        def restore():
            if current_stream:
                self.streams[id_] = current_stream

        frames = tuple(self.rewinds[id_])[-frame_count:]
        self.add_stream(
            AudioRewind(frames),
            id_=id_,
            after=restore,
        )

        return len(frames)


class AudioRewind(AudioSource):
    def __init__(self, frames: Iterable[bytes]):
        self.frames = iter(frames)

    def read(self) -> bytes:
        try:
            return next(self.frames)
        except StopIteration:
            return b""
