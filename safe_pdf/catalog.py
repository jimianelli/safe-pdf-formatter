"""Read and write the editable CSV chapter catalog without third-party packages."""

import csv
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .models import Chapter, FOOTERS


_COLUMNS = ("filename", "heading", "region")


def _validate(chapters: Iterable[Chapter]) -> list[Chapter]:
    result = list(chapters)
    seen: dict[str, int] = {}
    for row, chapter in enumerate(result, start=2):
        filename = chapter.filename
        if (
            not isinstance(filename, str)
            or filename != filename.strip()
            or "/" in filename
            or "\\" in filename
            or ":" in filename
            or any(ord(char) < 32 for char in filename)
            or Path(filename).suffix.lower() != ".pdf"
            or not filename[:-4].strip()
        ):
            raise ValueError(f"Catalog row {row}: filename must be a PDF basename, without a folder path.")
        if not isinstance(chapter.heading, str) or not chapter.heading.strip():
            raise ValueError(f"Catalog row {row} ({filename}): heading cannot be empty.")
        if chapter.region not in FOOTERS:
            allowed = ", ".join(FOOTERS)
            raise ValueError(f"Catalog row {row} ({filename}): region must be one of {allowed}.")
        key = filename.casefold()
        if key in seen:
            raise ValueError(
                f"Catalog row {row}: duplicate filename {filename!r} "
                f"(case-insensitive match to row {seen[key]})."
            )
        seen[key] = row
    return result


def read_catalog(path: str | Path) -> list[Chapter]:
    """Read a UTF-8 CSV (with or without a BOM), preserving exact cell text."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or sorted(reader.fieldnames) != sorted(_COLUMNS):
            raise ValueError("Catalog CSV must have exactly these columns: filename,heading,region.")
        chapters = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Catalog CSV line {reader.line_num}: expected three cells.")
            chapters.append(Chapter(**row))
    return _validate(chapters)


def write_catalog(path: str | Path, chapters: Iterable[Chapter]) -> None:
    """Validate completely, then atomically replace the UTF-8 CSV destination."""
    records = _validate(chapters)
    destination = Path(path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(_COLUMNS)
            writer.writerows((chapter.filename, chapter.heading, chapter.region) for chapter in records)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
