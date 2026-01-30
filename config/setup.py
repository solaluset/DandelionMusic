"This file is here to install the selected DB package and jsonc"

import os

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from setuptools import setup

from config import Config


def main():
    with open("db.txt", "w") as f, open("pyproject.toml", "rb") as t:
        print(Config().DATABASE_LIBRARY, file=f)
        # reuse requirements already specified in toml
        print(
            *tomllib.load(t)["build-system"]["requires"][3:], sep="\n", file=f
        )

    setup()

    os.remove("db.txt")


main()
