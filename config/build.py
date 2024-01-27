import os
import sys
import glob
import json
import runpy

from config import config

with open("config/config_comments.json", "w") as f:
    json.dump(config.get_comments(), f)

yt_dlp_plugins = glob.glob("musicbot/yt_dlp_plugins/**/*.py", recursive=True)

sys.argv.extend(
    [
        "--onefile",
        # discord kindly provides us with opus dlls
        "--collect-binaries=discord",
        # make sure every file from musicbot folder is included
        *[
            "--hidden-import="
            + os.path.splitext(file)[0].replace(os.path.sep, ".")
            for file in glob.glob("musicbot/**/*.py", recursive=True)
            if file not in yt_dlp_plugins
        ],
        "--hidden-import=" + config.DATABASE_LIBRARY,
        *[
            "--add-data=" + file + os.pathsep + "."
            for file in glob.glob("config/*.json")
        ],
        *[
            "--add-data=" + file + os.pathsep + "assets"
            for file in glob.glob("assets/*.mp3")
        ],
        *[
            "--add-data=" + file + os.pathsep + os.path.dirname(file)
            for file in yt_dlp_plugins
        ],
        "-p=config",
        "-n=DandelionMusic",
        "-i=assets/note.ico",
        "run.py",
    ]
)

print("Running as:", *sys.argv)
runpy.run_module("PyInstaller", run_name="__main__")
