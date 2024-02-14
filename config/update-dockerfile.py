import os

from config import config


dockerfile = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "Dockerfile"
)

variables = config.as_dict()
environ = []
# sort by definition order
for k in config.get_comments():
    value = variables[k]
    if not isinstance(value, str):
        value = repr(value)
    if " " in value:
        value = f'"{value}"'
    environ.append(f"ENV {k}={value}\n")

with open(dockerfile) as f:
    lines = f.readlines()

start = lines.index("# config env vars\n") + 1
end = lines.index("\n", start)
lines[start:end] = environ

with open(dockerfile, "w") as f:
    f.writelines(lines)
