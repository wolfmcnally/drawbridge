"""Separate the exact approved Git dependency from a hashed registry export."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CONRIC = b"conric @ git+https://github.com/wolfmcnally/conric.git@ed9286297e92b8c049f70eb15a3b5556ed107ff0"
_DIRECT = re.compile(rb"@|(?:git|hg|svn|bzr)\+|[a-z][a-z0-9+.-]*://|(?:file|ssh):|(?:^|\s)-e(?:\s|$)|--editable", re.I)
_CONRIC_NAME = re.compile(rb"^conric(?=$|[\s\[<>=!~;@])", re.I)


def registry_requirements(content: bytes) -> bytes:
    """Validate before removing exactly one line; retain all other bytes verbatim."""
    lines = content.splitlines(keepends=True)
    selected = []
    for index, line in enumerate(lines):
        body = line.rstrip(b"\r\n")
        stripped = body.strip()
        if not stripped or stripped.startswith(b"#"):
            continue
        if body == CONRIC:
            selected.append(index)
            if index + 1 < len(lines) and lines[index + 1].lstrip().startswith(b"--hash"):
                raise ValueError("Conric must not have a registry hash continuation")
        elif _CONRIC_NAME.search(stripped) or _DIRECT.search(body):
            raise ValueError("Unapproved direct requirement")
    if len(selected) != 1:
        raise ValueError("Expected exactly one approved Conric Git requirement")
    return b"".join(line for index, line in enumerate(lines) if index != selected[0])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must differ")
        result = registry_requirements(args.input.read_bytes())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.output.write_bytes(result)


if __name__ == "__main__":
    main()
