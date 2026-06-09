#!/usr/bin/env python3
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d\.\d$")


def validate_version(version):
    if not VERSION_PATTERN.match(version):
        raise SystemExit(
            "Usage: scripts/bump_version.py MAJOR.MINOR.PATCH\n"
            "CCBot versions use single-digit minor and patch numbers, for example 0.2.9."
        )


def replace(path, pattern, replacement):
    text = path.read_text(encoding="utf-8")
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update {path}")
    path.write_text(next_text, encoding="utf-8")


def main(argv):
    if len(argv) != 2:
        raise SystemExit("Usage: scripts/bump_version.py MAJOR.MINOR.PATCH")

    version = argv[1]
    validate_version(version)
    tag = f"v{version}"

    (ROOT / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    replace(ROOT / "pyproject.toml", r'^version = ".+"$', f'version = "{version}"')
    replace(ROOT / "ccbot_agent" / "__init__.py", r'^__version__ = ".+"$', f'__version__ = "{version}"')
    replace(ROOT / "ccbot_agent" / "main.py", r'^    __version__ = ".+"$', f'    __version__ = "{version}"')
    replace(
        ROOT / "install.sh",
        r'^CCBOT_AGENT_VERSION="\$\{CCBOT_AGENT_VERSION:-v[^}]+\}"$',
        f'CCBOT_AGENT_VERSION="${{CCBOT_AGENT_VERSION:-{tag}}}"',
    )

    print(f"Prepared CCBot Agent {version}.")
    print("Next: update CHANGELOG.md, commit, tag, and push.")


if __name__ == "__main__":
    main(sys.argv)
