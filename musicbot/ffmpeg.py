import audioop
import inspect
import subprocess
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import reduce
from queue import deque
from traceback import print_exc

import yt_dlp
from discord import AudioSource, VoiceClient
from discord import FFmpegPCMAudio as BasePCMAudio
from discord.opus import Encoder as OpusEncoder

from config import config
from musicbot.song import Song

OriginalArgs = tuple[list[str], dict | None]

downloader_class = yt_dlp.get_external_downloader("ffmpeg")
_downloader_module = inspect.getmodule(downloader_class)
_original_popen = _downloader_module.Popen
try:
    _dummy_process = _original_popen(
        ["ffmpeg", "-version"], stdout=subprocess.PIPE
    )
except (FileNotFoundError, subprocess.CalledProcessError) as e:
    raise RuntimeError("ffmpeg was not found") from e


class MonkeyPopen:
    args_catch_lock = threading.Lock()
    args_catch_result: OriginalArgs | None = None

    def __call__(self, args, *extra, env: dict | None = None, **kwargs):
        if MonkeyPopen.args_catch_lock.locked():
            MonkeyPopen.args_catch_result = (args, env)
            return _dummy_process
        return _original_popen(args, *extra, env=env, **kwargs)


_downloader_module.Popen = MonkeyPopen()


def _get_ffmpeg_args(song: Song) -> OriginalArgs:
    from musicbot.loader import _downloader

    with MonkeyPopen.args_catch_lock:
        try:
            _downloader.download("-", song.data)
            return MonkeyPopen.args_catch_result
        finally:
            MonkeyPopen.args_catch_result = None


class FFmpegPCMAudio(BasePCMAudio):
    def __init__(self, original_args: OriginalArgs):
        self.original_args, self.original_env = original_args
        super().__init__(None, stderr=sys.stderr)

    def _spawn_process(
        self, args: list[str], **subprocess_kwargs
    ) -> subprocess.Popen:
        new_args = self.original_args.copy()
        new_args[1:1] = (
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
        )
        try:
            c_index = new_args.index("-c")
            del new_args[c_index : c_index + 2]
        except ValueError:
            pass
        f_index = new_args.index("-f")
        new_args[f_index : f_index + 2] = (
            ["-af", "loudnorm"]
            + args[args.index("-f") : -1]
            + ["-loglevel", "error"]
        )
        subprocess_kwargs["env"] = self.original_env
        return super()._spawn_process(new_args, **subprocess_kwargs)


@dataclass
class AudioStream:
    source: AudioSource
    after: Callable[[], None] | None = None
    paused: bool = False
    rewindable: bool = False
    read_frames: int = 0

    def read(self) -> bytes:
        self.read_frames += 1
        return self.source.read()


class AudioMixer(AudioSource):
    SILENCE = b"\0" * OpusEncoder.FRAME_SIZE
    FRAMES_PER_SECOND = round(1000 / OpusEncoder.FRAME_LENGTH)
    MAX_REWIND_FRAMES = FRAMES_PER_SECOND * config.MAX_REWIND_SECONDS

    def __init__(self, client: VoiceClient):
        self.client = client
        self.streams: dict[int, AudioStream] = {}
        self.rewinds: defaultdict[int, deque[bytes]] = defaultdict(
            lambda: deque(maxlen=self.MAX_REWIND_FRAMES)
        )
        self._stop_mark: object | None = None

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

            ret = stream.read()
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
        id_: int | None = None,
        after: Callable[[], None] | None = None,
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

        self._stop_mark = None
        if not self.client.is_playing():
            self.client.play(self)

    def get_stream(self, id_: int) -> AudioStream | None:
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
            except Exception:  # noqa: BLE001
                print_exc(file=sys.stderr)

        if not self.streams and self.client.is_playing():
            stop_mark = self._stop_mark = object()

            def stop():
                time.sleep(3)
                if stop_mark is not self._stop_mark:
                    return
                self.client.stop()

            threading.Thread(target=stop, daemon=True).start()

    def fast_forward_stream(self, id_: int, frame_count: int) -> None:
        stream = self.streams.get(id_)
        if not stream:
            return

        stream.paused = True
        for _ in range(frame_count):
            if not stream.paused or not stream.read():
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
