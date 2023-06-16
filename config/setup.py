"This file is here to automatically install the selected DB package"
import os
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from setuptools import setup

# imitate running in root directory
cfg_dir = Path(__file__).parent
sys.path.insert(0, str(cfg_dir.parent))
for i, path in enumerate(sys.path):
    if Path(path).absolute() == cfg_dir:
        sys.path[i] = str(cfg_dir.parent)


def main():
    from config import config

    with open("db.txt", "w") as f, open("pyproject.toml", "rb") as t:
        print(config.DATABASE_LIBRARY, file=f)
        # reuse jsonc already specified in toml
        print(tomllib.load(t)["build-system"]["requires"][-1], file=f)

    setup()

    os.remove("db.txt")


main()
