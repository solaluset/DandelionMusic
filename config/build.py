import os
import sys
import glob
import json
import runpy

from config import config

with open("config/config_comments.json", "w") as f:
    json.dump(config.get_comments(), f)

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
        ],
        "--hidden-import=" + config.DATABASE_LIBRARY,
        *[
            "--add-data=" + file + os.pathsep + "."
            for file in glob.glob("config/*.json")
        ],
        "-p=config",
        "-n=DandelionMusic",
        "-i=assets/note.ico",
        "run.py",
    ]
)

print("Running as:", *sys.argv)
runpy.run_module("PyInstaller", run_name="__main__")
