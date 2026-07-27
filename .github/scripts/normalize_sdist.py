"""Normalize one ReconForge sdist without extracting it to the filesystem."""

from __future__ import annotations

import argparse
import copy
import gzip
import os
import re
import shutil
import tarfile
from pathlib import Path, PurePosixPath

SDIST_RE = re.compile(r"^reconforge_erp-([0-9]+\.[0-9]+\.[0-9]+)\.tar\.gz$")
MAX_GZIP_MTIME = (1 << 32) - 1


class SdistNormalizationError(ValueError):
    """Raised when an sdist cannot be normalized safely."""


def _safe_members(archive: tarfile.TarFile, *, root_name: str) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if not members:
        raise SdistNormalizationError("sdist archive is empty")
    prefix = f"{root_name}/"
    names: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        inside_root = member.name == root_name or member.name.startswith(prefix)
        if path.is_absolute() or ".." in path.parts or not inside_root:
            raise SdistNormalizationError("sdist contains an unsafe or unexpected path")
        if member.issym() or member.islnk():
            raise SdistNormalizationError("sdist links are not permitted in the normalized release contract")
        if not (member.isfile() or member.isdir()):
            raise SdistNormalizationError("sdist contains an unsupported archive member type")
        if member.name in names:
            raise SdistNormalizationError("sdist contains duplicate archive member names")
        names.add(member.name)
    metadata = [member for member in members if member.name == f"{prefix}PKG-INFO" and member.isfile()]
    if len(metadata) != 1:
        raise SdistNormalizationError("sdist must contain exactly one root PKG-INFO file")
    return sorted(members, key=lambda member: member.name)


def normalize_sdist(path: Path, *, source_date_epoch: int) -> None:
    """Rewrite safe members in canonical order with fixed owner and time metadata."""
    if source_date_epoch < 0 or source_date_epoch > MAX_GZIP_MTIME:
        raise SdistNormalizationError("SOURCE_DATE_EPOCH is outside the gzip timestamp range")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise SdistNormalizationError("sdist must be a regular non-symlink file")
    match = SDIST_RE.fullmatch(resolved.name)
    if match is None:
        raise SdistNormalizationError("sdist filename does not match the ReconForge release contract")
    root_name = f"reconforge_erp-{match.group(1)}"

    temporary_tar = resolved.with_name(f".{resolved.name}.normalized.tar.tmp")
    temporary_gzip = resolved.with_name(f".{resolved.name}.normalized.gz.tmp")
    try:
        with tarfile.open(resolved, "r:gz") as source:
            members = _safe_members(source, root_name=root_name)
            with tarfile.open(temporary_tar, "w", format=tarfile.PAX_FORMAT) as target:
                for member in members:
                    normalized = copy.copy(member)
                    normalized.mtime = source_date_epoch
                    normalized.uid = 0
                    normalized.gid = 0
                    normalized.uname = ""
                    normalized.gname = ""
                    normalized.pax_headers = {
                        key: value
                        for key, value in member.pax_headers.items()
                        if key not in {"atime", "ctime", "mtime"}
                    }
                    content = source.extractfile(member) if member.isfile() else None
                    target.addfile(normalized, content)

        with (
            temporary_tar.open("rb") as source_tar,
            temporary_gzip.open("wb") as output,
            gzip.GzipFile(fileobj=output, filename="", mode="wb", mtime=source_date_epoch) as compressed,
        ):
            shutil.copyfileobj(source_tar, compressed, length=1024 * 1024)
        os.replace(temporary_gzip, resolved)
    except (OSError, tarfile.TarError) as exc:
        raise SdistNormalizationError(f"unable to normalize sdist: {exc}") from exc
    finally:
        temporary_tar.unlink(missing_ok=True)
        temporary_gzip.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        normalize_sdist(args.path, source_date_epoch=args.source_date_epoch)
    except (OSError, SdistNormalizationError) as exc:
        raise SystemExit(f"sdist normalization rejected: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
