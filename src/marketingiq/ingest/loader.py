"""Load source files into staging, with one audit row per file in core.load_batches.

Each file loads in a single transaction: the batch row, the valid rows (via COPY) and the
rejected rows commit together or not at all. A file that already loaded successfully (same
organization, staging table and SHA-256) is skipped, so re-running a load is harmless.
Staging keeps every batch; each file is treated as a full snapshot of its source, and the
core step reads the latest successful batch per table.
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psycopg
from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from marketingiq.ingest.parsing import FileError, ParsedFile, parse_file
from marketingiq.ingest.sources import SOURCES, Source
from marketingiq.models import LoadBatch, Organization, RejectedRow

# Problems that fail one file but shouldn't stop the rest of a dataset from loading.
_FILE_FAILURES = (FileError, csv.Error, UnicodeDecodeError, SQLAlchemyError, psycopg.Error)


@dataclass(frozen=True)
class LoadResult:
    entity: str
    status: str  # loaded | skipped | failed | missing
    batch_id: int | None = None
    rows_read: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    rows_duplicate: int = 0
    error: str | None = None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_file(
    engine: Engine,
    org_id: int,
    source: Source,
    path: Path,
    *,
    generator_seed: int | None = None,
) -> LoadResult:
    digest = file_sha256(path)
    with engine.connect() as conn:
        existing = conn.execute(
            select(LoadBatch.id).where(
                LoadBatch.org_id == org_id,
                LoadBatch.entity == source.entity,
                LoadBatch.file_sha256 == digest,
                LoadBatch.status == "succeeded",
            )
        ).scalar()
    if existing is not None:
        return LoadResult(source.entity, "skipped", existing)

    batch = {
        "org_id": org_id,
        "source_system": source.source_system,
        "entity": source.entity,
        "source_file": source.path,
        "file_sha256": digest,
        "generator_seed": generator_seed,
    }
    try:
        parsed = parse_file(source, path)
        with engine.begin() as conn:
            batch_id = conn.execute(
                insert(LoadBatch).values(**batch, status="running").returning(LoadBatch.id)
            ).scalar_one()
            _copy_rows(conn, source, batch_id, parsed)
            _store_rejections(conn, batch_id, parsed)
            conn.execute(
                update(LoadBatch)
                .where(LoadBatch.id == batch_id)
                .values(
                    status="succeeded",
                    rows_read=parsed.read,
                    rows_loaded=len(parsed.rows),
                    rows_rejected=len(parsed.rejected),
                    rows_duplicate=parsed.duplicates,
                    finished_at=func.now(),
                )
            )
    except _FILE_FAILURES as exc:
        error = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:500]
        with engine.begin() as conn:
            batch_id = conn.execute(
                insert(LoadBatch)
                .values(**batch, status="failed", error=error, finished_at=func.now())
                .returning(LoadBatch.id)
            ).scalar_one()
        return LoadResult(source.entity, "failed", batch_id, error=error)

    return LoadResult(
        source.entity,
        "loaded",
        batch_id,
        rows_read=parsed.read,
        rows_loaded=len(parsed.rows),
        rows_rejected=len(parsed.rejected),
        rows_duplicate=parsed.duplicates,
    )


def _copy_rows(conn: Connection, source: Source, batch_id: int, parsed: ParsedFile) -> None:
    """Bulk-insert valid rows with PostgreSQL COPY, inside the caller's transaction."""
    fields = list(source.row_model.model_fields)
    columns = ", ".join(["load_batch_id", "source_row", *fields])
    statement = f"COPY staging.{source.entity} ({columns}) FROM STDIN"
    with conn.connection.dbapi_connection.cursor() as cursor, cursor.copy(statement) as copy:
        for number, row in parsed.rows:
            copy.write_row((batch_id, number, *(getattr(row, name) for name in fields)))


def _store_rejections(conn: Connection, batch_id: int, parsed: ParsedFile) -> None:
    if parsed.rejected:
        conn.execute(
            insert(RejectedRow),
            [
                {
                    "load_batch_id": batch_id,
                    "row_number": rejection.row_number,
                    "raw": rejection.raw,
                    "errors": rejection.errors,
                }
                for rejection in parsed.rejected
            ],
        )


def ensure_organization(
    engine: Engine,
    *,
    slug: str,
    name: str,
    reporting_tz: str,
    currency: str,
    is_synthetic: bool,
    data_as_of: date | None,
) -> int:
    """Create the organization, or update it if the slug already exists; returns its id."""
    values = {
        "name": name,
        "reporting_tz": reporting_tz,
        "currency": currency,
        "is_synthetic": is_synthetic,
        "data_as_of": data_as_of,
    }
    statement = (
        pg_insert(Organization)
        .values(slug=slug, **values)
        .on_conflict_do_update(index_elements=[Organization.slug], set_=values)
        .returning(Organization.id)
    )
    with engine.begin() as conn:
        return conn.execute(statement).scalar_one()


def find_organization(engine: Engine, slug: str) -> int | None:
    with engine.connect() as conn:
        return conn.execute(select(Organization.id).where(Organization.slug == slug)).scalar()


def load_dataset(engine: Engine, folder: Path, *, org_slug: str | None = None) -> list[LoadResult]:
    """Load every known source file found in a dataset folder.

    A generated dataset carries manifest.json, which describes its organization. Any other
    folder needs `org_slug` naming an organization that already exists. Files under truth/
    are never read: they aren't in SOURCES.
    """
    manifest_path = folder / "manifest.json"
    seed = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        organization = manifest["organization"]
        if org_slug and org_slug != organization["slug"]:
            raise ValueError(
                f"--org {org_slug} doesn't match the manifest's {organization['slug']}"
            )
        org_id = ensure_organization(
            engine,
            slug=organization["slug"],
            name=organization["name"],
            reporting_tz=manifest["reporting_tz"],
            currency=manifest["currency"],
            is_synthetic=bool(manifest.get("synthetic", False)),
            data_as_of=date.fromisoformat(manifest["window"]["data_as_of"]),
        )
        seed = manifest.get("seed")
    elif org_slug:
        found = find_organization(engine, org_slug)
        if found is None:
            raise LookupError(f"no organization with slug {org_slug!r}")
        org_id = found
    else:
        raise ValueError(f"{folder} has no manifest.json; name the organization with --org")

    results = []
    for source in SOURCES:
        path = folder / source.path
        if path.exists():
            results.append(load_file(engine, org_id, source, path, generator_seed=seed))
        else:
            results.append(LoadResult(source.entity, "missing"))
    return results
