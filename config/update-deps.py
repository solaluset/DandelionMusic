# bump dependencies in pyproject.toml that dependabot doesn't for some reason
import json
import tomllib
from pathlib import Path
from typing import Callable
from urllib.request import urlopen
from packaging.requirements import Requirement
from packaging.version import Version

ROOT_DIR = Path(__file__).parent.parent
FILES = [
    ROOT_DIR / "requirements.txt",
    ROOT_DIR / "config" / "pyproject.toml",
    ROOT_DIR / "config" / "db-requirements.txt",
    ROOT_DIR / "config" / "build-requirements.txt",
]


def get_current_version(requirement) -> Version | None:
    if len(requirement.specifier) != 1:
        return None
    specifier = next(iter(requirement.specifier))
    if specifier.operator != "==":
        return None
    return Version(specifier.version)


def fetch_latest_version(requirement) -> Version:
    return Version(
        json.load(urlopen(f"https://pypi.org/pypi/{requirement.name}/json"))[
            "info"
        ]["version"]
    )


def update_file(name: str, parser: Callable[[str], list[str]]) -> None:
    with open(name, "r") as file:
        content = file.read()
    requirements = parser(content)
    for req_str in requirements:
        req = Requirement(req_str)
        version = get_current_version(req)
        if version is not None:
            new_version = fetch_latest_version(req)
            if new_version > version:
                new_req_str = req_str.replace(str(version), str(new_version))
                content = content.replace(req_str, new_req_str)
    with open(name, "w") as file:
        file.write(content)


def toml_parser(content: str) -> list[str]:
    return tomllib.loads(content)["build-system"]["requires"]


def txt_parser(content: str) -> list[str]:
    return [
        line
        for line in map(str.strip, content.splitlines())
        if line and not line.startswith(("#", "./", "-r "))
    ]


if __name__ == "__main__":
    for file in FILES:
        if file.suffix == ".toml":
            parser = toml_parser
        elif file.suffix == ".txt":
            parser = txt_parser
        else:
            raise ValueError(f"unknown file format: {file.suffix!r}")
        update_file(file, parser)
