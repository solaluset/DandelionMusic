import os
import json
import inspect

from config.utils import get_env_var, alchemize_url


class Config:
    BOT_TOKEN = "YOUR_TOKEN_GOES_HERE"
    SPOTIFY_ID = ""
    SPOTIFY_SECRET = ""

    BOT_PREFIX = "d!"  # set to empty string to disable
    ENABLE_SLASH_COMMANDS = False

    VC_TIMEOUT = 600  # seconds
    # default template setting for VC timeout
    # true = yes, timeout; false = no timeout
    VC_TIMOUT_DEFAULT = True

    MAX_SONG_PRELOAD = 5  # maximum of 25
    MAX_HISTORY_LENGTH = 10
    MAX_TRACKNAME_HISTORY_LENGTH = 15

    # if database is not one of sqlite, postgres or MySQL
    # you need to provide the url in SQL Alchemy-supported format.
    # Must be async-compatible
    # CHANGE ONLY IF YOU KNOW WHAT YOU'RE DOING
    DATABASE_URL = os.getenv("HEROKU_DB") or "sqlite:///settings.db"

    MENTION_AS_PREFIX = True

    ENABLE_BUTTON_PLUGIN = True

    # replace after '0x' with desired hex code ex. '#ff0188' >> 0xff0188
    EMBED_COLOR = 0x4DD4D0

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

    # allow or disallow editing the vc_timeout guild setting
    ALLOW_VC_TIMEOUT_EDIT = True

    def __init__(self):
        if os.path.isfile("config.json"):
            with open("config.json") as f:
                loaded_cfg = json.load(
                    f,
                    object_hook=lambda d: {
                        k: tuple(v) if isinstance(v, list) else v
                        for k, v in d.items()
                    },
                )
        else:
            loaded_cfg = {}

        current_cfg = self.as_dict()
        current_cfg.update(loaded_cfg)

        if loaded_cfg.keys() != current_cfg.keys() and not os.getenv(
            "DANDELION_INSTALLING"
        ):
            with open("config.json", "w") as f:
                json.dump(current_cfg, f, indent=2)

        for key, default in current_cfg.items():
            setattr(self, key, get_env_var(key, default))

        self.actual_prefix = (  # for internal use
            self.BOT_PREFIX
            if self.BOT_PREFIX
            else ("/" if self.ENABLE_SLASH_COMMANDS else "@bot ")
        )
        current_cfg["prefix"] = self.actual_prefix

        # ignore empty DB URL in env
        if not self.DATABASE_URL:
            self.DATABASE_URL = current_cfg["DATABASE_URL"]
        self.DATABASE = alchemize_url(self.DATABASE_URL)
        self.DATABASE_LIBRARY = self.DATABASE.partition("+")[2].partition(":")[
            0
        ]

        with open(os.path.join(os.path.dirname(__file__), "en.json")) as f:
            self.messages = {
                k: v.format(**current_cfg) for k, v in json.load(f).items()
            }

    def __getattr__(self, key: str) -> str:
        try:
            return self.messages[key]
        except KeyError as e:
            raise AttributeError(f"No text for {key!r} defined") from e

    @classmethod
    def update(cls, data: dict):
        for k, v in data.items():
            setattr(cls, k, v)

    @classmethod
    def as_dict(cls) -> dict:
        return {
            k: v
            for k, v in inspect.getmembers(cls)
            if not k.startswith("__") and not inspect.isroutine(v)
        }
