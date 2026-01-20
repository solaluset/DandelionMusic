# bump dependencies in pyproject.toml that dependabot doesn't for some reason
import os
import json
import tomllib
from urllib.request import urlopen
from packaging.requirements import Requirement
from packaging.version import Version, InvalidVersion

cfg_dir = os.path.dirname(__file__)
pyproject_file = os.path.join(cfg_dir, "pyproject.toml")


def get_current_version(requirement):
    try:
        return Version(str(requirement.specifier).partition("==")[2])
    except InvalidVersion:
        return None


def fetch_latest_version(requirement):
    return Version(
        json.load(urlopen(f"https://pypi.org/pypi/{requirement.name}/json"))[
            "info"
        ]["version"]
    )


with open(pyproject_file, "rb") as f:
    pyproject_content = f.read().decode()
    f.seek(0)
    requirements = tomllib.load(f)["build-system"]["requires"]

for req in requirements:
    req_obj = Requirement(req)
    version = get_current_version(req_obj)
    if version is not None:
        new_version = fetch_latest_version(req_obj)
        if new_version > version:
            new_req = req.replace(str(version), str(new_version))
            pyproject_content = pyproject_content.replace(req, new_req)

with open(pyproject_file, "w") as f:
    f.write(pyproject_content)
