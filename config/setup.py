"This file is here to install the selected DB package and jsonc"

import os

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from setuptools import setup

from config import Config

DB_REQUIREMENTS_FILE = "db.txt"
DB_REQUIREMENTS_BACKUP = DB_REQUIREMENTS_FILE + ".back"


def main():
    with open(DB_REQUIREMENTS_FILE, "w") as f, open(
        "pyproject.toml", "rb"
    ) as t:
        print(Config().DATABASE_LIBRARY, file=f)
        # reuse requirements already specified in toml
        print(
            *tomllib.load(t)["build-system"]["requires"][3:], sep="\n", file=f
        )

    setup()

    os.remove(DB_REQUIREMENTS_FILE)


os.rename(DB_REQUIREMENTS_FILE, DB_REQUIREMENTS_BACKUP)
try:
    main()
finally:
    os.rename(DB_REQUIREMENTS_BACKUP, DB_REQUIREMENTS_FILE)
