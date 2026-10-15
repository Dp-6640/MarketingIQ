"""Read one source file and sort its rows into valid, rejected and duplicate. No database."""

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from marketingiq.ingest.rows import ERROR_CODES, SourceRow, describe_errors
from marketingiq.ingest.sources import Source


class FileError(Exception):
    """The file as a whole can't be loaded (for example, a required column is missing)."""


@dataclass
class Rejection:
    row_number: int  # 1-based data row, header excluded
    raw: dict[str, str]
    errors: list[dict[str, Any]]


@dataclass
class ParsedFile:
    rows: list[tuple[int, SourceRow]] = field(default_factory=list)  # (row_number, row)
    rejected: list[Rejection] = field(default_factory=list)
    duplicates: int = 0  # rows identical to an earlier row; skipped, not errors
    read: int = 0


def parse_file(source: Source, path: Path) -> ParsedFile:
    # utf-8-sig tolerates the byte-order mark that Excel adds when saving CSVs.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = source.required_columns() - set(reader.fieldnames or [])
        if missing:
            raise FileError(f"{source.path}: missing required columns {sorted(missing)}")

        parsed = ParsedFile()
        first_seen: dict[tuple[Any, ...], tuple[int, dict[str, str]]] = {}
        for number, record in enumerate(reader, start=1):
            parsed.read += 1
            if None in record:  # DictReader files surplus values under the None key
                raw = {k: v for k, v in record.items() if k is not None}
                parsed.rejected.append(Rejection(number, raw, [_problem("malformed_row")]))
                continue
            # Empty cells count as missing, so required fields report missing_required.
            values = {key: value for key, value in record.items() if value not in ("", None)}
            try:
                row = source.row_model.model_validate(values)
            except ValidationError as exc:
                parsed.rejected.append(Rejection(number, dict(record), describe_errors(exc)))
                continue

            key = tuple(getattr(row, name) for name in source.key)
            if key in first_seen:
                first_number, first_record = first_seen[key]
                if first_record == record:
                    parsed.duplicates += 1
                else:
                    problem = _problem("conflicting_duplicate", f"same key as row {first_number}")
                    parsed.rejected.append(Rejection(number, dict(record), [problem]))
                continue
            first_seen[key] = (number, record)
            parsed.rows.append((number, row))
    return parsed


def _problem(code: str, message: str | None = None) -> dict[str, Any]:
    return {"field": None, "code": code, "message": message or ERROR_CODES[code]}
