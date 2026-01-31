import random
from typing import Optional
from collections import deque

from discord import Embed

from config import config
from musicbot.song import Song
from musicbot.utils import StrEnum, songs_embed

LoopMode = StrEnum("LoopMode", config.get_dict("LoopMode"))
LoopState = StrEnum("LoopState", config.get_dict("LoopState"))
PauseState = StrEnum("PauseState", config.get_dict("PauseState"))


class Playlist:
    """Stores the youtube links of songs to be played and already played
    Offers basic operation on the queues"""

    def __init__(self):
        # Stores the links os the songs in queue and the ones already played
        self.playque: deque[Song] = deque()
        self.playhistory: deque[Song] = deque()

        # A seperate history that remembers
        # the names of the tracks that were played
        self.trackname_history: deque[str] = deque()

        self.loop = LoopMode.OFF

    def __len__(self):
        return len(self.playque)

    def __bool__(self) -> bool:
        return bool(self.playque)

    def __getitem__(self, key: int) -> Song:
        return self.playque[key]

    def add_name(self, trackname: str):
        self.trackname_history.append(trackname)
        if len(self.trackname_history) > config.MAX_TRACKNAME_HISTORY_LENGTH:
            self.trackname_history.popleft()

    def add(self, track: Song):
        self.playque.append(track)

    def has_next(self) -> bool:
        return len(self.playque) >= (2 if self.loop != LoopMode.ALL else 1)

    def has_prev(self) -> bool:
        return (
            len(
                self.playhistory if self.loop != LoopMode.ALL else self.playque
            )
            != 0
        )

    def next(self, ignore_single_loop=False) -> Optional[Song]:
        if len(self.playque) == 0:
            return None

        if self.loop == LoopMode.OFF or (
            ignore_single_loop and self.loop == LoopMode.SINGLE
        ):
            self.playhistory.append(self.playque.popleft())
            if len(self.playhistory) > config.MAX_HISTORY_LENGTH:
                self.playhistory.popleft()
            if len(self.playque) != 0:
                return self.playque[0]
            else:
                return None

        if self.loop == LoopMode.ALL:
            self.playque.rotate(-1)

        return self.playque[0]

    def prev(self) -> Optional[Song]:
        if self.loop != LoopMode.ALL:
            if len(self.playhistory) != 0:
                song = self.playhistory.pop()
                self.playque.appendleft(song)
                return song
            else:
                return None

        if len(self.playque) == 0:
            return None

        self.playque.rotate()

        return self.playque[0]

    def shuffle(self):
        first = self.playque.popleft()
        random.shuffle(self.playque)
        self.playque.appendleft(first)

    def clear(self):
        if self.playque:
            first = self.playque.popleft()
            self.playque.clear()
            self.playque.appendleft(first)

    def empty(self):
        self.playque.clear()
        self.playhistory.clear()

    def queue_embed(self) -> Embed:
        return songs_embed(
            config.QUEUE_TITLE.format(tracks_number=len(self.playque)),
            list(self.playque)[: config.MAX_SONG_PRELOAD],
        )
