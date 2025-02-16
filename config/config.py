import os
import sys
import ast
import inspect
import warnings
from typing import Optional

import jsonc
from packaging.requirements import Requirement

sys.path.insert(0, os.path.dirname(__file__))
from utils import (  # noqa: E402
    CONFIG_DIRS,
    Formatter,
    get_env_var,
    alchemize_url,
    load_configs,
    join_dicts,
    subtract_dicts,
)

del sys.path[0]


class Config:
    BOT_TOKEN = "YOUR_TOKEN_GOES_HERE"
    SPOTIFY_ID = ""
    SPOTIFY_SECRET = ""

    # set to empty string to disable
    BOT_PREFIX = "d!"
    ENABLE_SLASH_COMMANDS = False
    MENTION_AS_PREFIX = True

    # seconds
    VC_TIMEOUT = 600
    # default template setting for VC timeout
    # true = yes, timeout; false = no timeout
    VC_TIMEOUT_DEFAULT = True
    # allow or disallow editing the vc_timeout guild setting
    ALLOW_VC_TIMEOUT_EDIT = True

    # maximum of 25
    MAX_SONG_PRELOAD = 5
    # how many results to display in d!search
    SEARCH_RESULTS = 5

    MAX_HISTORY_LENGTH = 10
    MAX_TRACKNAME_HISTORY_LENGTH = 15

    # if database is not one of sqlite, postgres or MySQL
    # you need to provide the url in SQL Alchemy-supported format.
    # Must be async-compatible
    # CHANGE ONLY IF YOU KNOW WHAT YOU'RE DOING
    DATABASE_URL = os.getenv("HEROKU_DB") or "sqlite:///settings.db"

    ENABLE_BUTTON_PLUGIN = True

    # replace after '0x' with desired hex code ex. '#ff0188' >> "0xff0188"
    EMBED_COLOR: int = "0x4DD4D0"  # converted to int in __init__

    SUPPORTED_EXTENSIONS = (
        ".webm",
        ".mp4",
        ".mp3",
        ".avi",
        ".wav",
        ".m4v",
        ".ogg",
        ".mov",
    )

    COOKIE_PATH = "config/cookies/cookies.txt"

    GLOBAL_DISABLE_AUTOJOIN_VC = False

    # whether to tell users the bot is disconnecting
    ANNOUNCE_DISCONNECT = True

    ENABLE_PLAYLISTS = True

    # Proxy, use proper scheme in Config.
        # https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#network-options
        # e.g. "socks5://user:pass@127.0.0.1:1080" or "http://127.0.0.1:8118" (privoxy on local machine)
    PROXY_STRING = ""

    def __init__(self):
        current_cfg = self.load()

        # prefix to display
        current_cfg["prefix"] = (
            self.BOT_PREFIX
            if self.BOT_PREFIX
            else ("/" if self.ENABLE_SLASH_COMMANDS else "@bot ")
        )

        self.DATABASE = alchemize_url(self.DATABASE_URL)
        self.DATABASE_LIBRARY = self.DATABASE.partition("+")[2].partition(":")[
            0
        ]
        db_req = Requirement(self.DATABASE_LIBRARY)
        self.DATABASE = self.DATABASE.replace(
            self.DATABASE_LIBRARY, db_req.name, 1
        )
        self.DATABASE_LIBRARY_NAME = db_req.name
        if not db_req.specifier:
            with open(
                os.path.join(os.path.dirname(__file__), "db-requirements.txt")
            ) as f:
                for line in f:
                    req = Requirement(line)
                    if req.name == db_req.name:
                        self.DATABASE_LIBRARY = str(req)
                        break

        self.EMBED_COLOR = int(self.EMBED_COLOR, 16)
        for dir_ in CONFIG_DIRS[::-1]:
            path = os.path.join(dir_, self.COOKIE_PATH)
            if os.path.isfile(path):
                self.COOKIE_PATH = path
                break

        data = join_dicts(
            load_configs(
                "en.json",
                lambda d: {
                    k: (
                        Formatter(v).format(current_cfg)
                        if isinstance(v, str)
                        else v
                    )
                    for k, v in d.items()
                },
            )
        )

        self.messages = {}
        self.dicts = {}
        for k, v in data.items():
            if isinstance(v, str):
                self.messages[k] = v
            elif isinstance(v, dict):
                self.dicts[k] = v

    def load(self) -> dict:
        loaded_cfgs = load_configs(
            "config.json",
            lambda d: {
                k: tuple(v) if isinstance(v, list) else v for k, v in d.items()
            },
        )

        current_cfg = self.as_dict()
        loaded_joined = join_dicts(loaded_cfgs)
        # recognise deprecated cfg key with a typo
        if "VC_TIMOUT_DEFAULT" in loaded_joined:
            # in config, silently replace
            current_cfg["VC_TIMEOUT_DEFAULT"] = loaded_joined.pop(
                "VC_TIMOUT_DEFAULT"
            )
        if "VC_TIMOUT_DEFAULT" in os.environ:
            # in env, we can't fix it easily
            raise RuntimeError(
                "Please rename VC_TIMOUT_DEFAULT"
                " to VC_TIMEOUT_DEFAULT in your environment"
            )
        missing = subtract_dicts(current_cfg, loaded_joined)
        self.unknown_vars = subtract_dicts(loaded_joined, current_cfg)

        if missing:
            missing.update(loaded_cfgs[-1])
            self.to_save = missing
        else:
            self.to_save = None

        current_cfg.update(loaded_joined)

        for key, default in current_cfg.items():
            current_cfg[key] = get_env_var(key, default)

        for key, alias in (
            ("SPOTIFY_ID", "SPOTIPY_CLIENT_ID"),
            ("SPOTIFY_SECRET", "SPOTIPY_CLIENT_SECRET"),
        ):
            if not current_cfg[key]:
                current_cfg[key] = get_env_var(alias, current_cfg[key])

        # Embeds are limited to 25 fields
        current_cfg["MAX_SONG_PRELOAD"] = min(
            current_cfg["MAX_SONG_PRELOAD"], 25
        )

        self.update(current_cfg)
        return current_cfg

    def __getattr__(self, key: str) -> str:
        try:
            return self.messages[key]
        except KeyError as e:
            raise AttributeError(f"No text for {key!r} defined") from e

    def get_dict(self, name: str) -> dict:
        return self.dicts[name]

    def save(self):
        if not self.to_save:
            return
        comments = self.get_comments()
        if comments:
            # sort according to definition order
            self.to_save = {
                k: self.to_save[k] for k in comments if k in self.to_save
            }
        with open("config.json", "w") as f:
            jsonc.dump(
                self.to_save,
                f,
                indent=2,
                trailing_comma=True,
                comments=comments,
            )
            f.write("\n")
        self.to_save = None

    def warn_unknown_vars(self):
        for name in self.unknown_vars:
            warnings.warn(f"Unknown variable in config: {name}")

    def update(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)

    @classmethod
    def as_dict(cls) -> dict:
        return {
            k: v
            for k, v in inspect.getmembers(cls)
            if not k.startswith("__") and not inspect.isroutine(v)
        }

    @classmethod
    def get_comments(cls) -> Optional[dict]:
        try:
            src = inspect.getsource(cls)
        except OSError:
            fallback = os.path.join(
                getattr(sys, "_MEIPASS", ""), "config_comments.json"
            )
            if os.path.isfile(fallback):
                with open(fallback) as f:
                    return jsonc.load(f)
            return None
        result = {}
        body = ast.parse(src).body[0].body
        src = src.splitlines()
        for node in body:
            if isinstance(node, ast.Assign):
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            else:
                target = None
            if target is not None:
                comment = ""
                for i in range(node.lineno - 2, -1, -1):
                    line = src[i].strip()
                    if line and not line.startswith("#"):
                        break
                    comment = line[1:].strip() + "\n" + comment
                result[target.id] = comment
        return result
