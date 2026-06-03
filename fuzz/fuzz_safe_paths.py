from __future__ import annotations

import string
import sys

import atheris

from reconforge.utils.safe_paths import is_safe_download_key

MAX_TEXT_BYTES = 512


def _decode(data: bytes) -> str:
    return data[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")


def _has_windows_drive_prefix(value: str) -> bool:
    return len(value) >= 2 and value[0] in string.ascii_letters and value[1] == ":"


def TestOneInput(data: bytes) -> None:
    value = _decode(data)
    result = is_safe_download_key(value)

    if not result:
        return

    assert value
    assert value == value.strip()
    assert "\\" not in value
    assert ".." not in value
    assert "//" not in value
    assert not value.startswith("/")
    assert not _has_windows_drive_prefix(value)
    assert all(part and part != "." for part in value.split("/"))


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
