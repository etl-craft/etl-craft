"""Declared reference files, read with the stewardship reader and cast by the warehouse."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import Dialect, exp
from sqlglot.errors import SqlglotError

from etl_craft.config import ConnectorConfig
from etl_craft.config.project import project_file
from etl_craft.config.targets import active_catalog
from etl_craft.core.enums import YesNo
from etl_craft.core.enums_uploads import UploadFormat
from etl_craft.core.errors import MetadataError
from etl_craft.core.text import is_safe_identifier
from etl_craft.core.upload_reader import UploadReader
from etl_craft.core.uploads import UploadFile
from etl_craft.dialects.warehouse.seeds import cast_value
from etl_craft.engine.repository.normalization import ObjectIdentity, object_identity
from etl_craft.handlers.sql.tables import ENGINE_COLUMNS
from etl_craft.warehouse.connection import warehouse_dialect


@dataclass(frozen=True)
class Seed:
    """One validated folder and its ordered, declared business columns."""

    directory: Path
    identity: ObjectIdentity
    columns: tuple[tuple[str, str], ...]
    keys: tuple[str, ...]
    sha256: str

    @property
    def target(self) -> str:
        """The resolved table name shared with merge writers."""
        return ".".join(part for part in self.identity if part is not None)

    def rows(self) -> list[tuple[object, ...]]:
        """Align declared fields with the header, filling omitted non-key fields with NULL."""
        path = self.directory / "data.csv"
        rows = list(reader(path).rows())
        header = tuple(str(value).lower() for value in rows[0]) if rows else ()
        declared = {name.lower() for name, _ in self.columns}
        if not header or len(set(header)) != len(header) or set(header) - declared:
            raise MetadataError(
                f"{self.target}: {path}, row 1, header={header!r}; expected unique declared "
                "columns; declare each header column in columns.csv or remove it from data.csv"
            )
        if missing := set(self.keys) - set(header):
            raise MetadataError(
                f"{self.target}: {path}, row 1, missing key columns {sorted(missing)!r}; "
                "KEY_FLAG=Y columns cannot be omitted; include them in data.csv's header and rows"
            )
        result = []
        for number, row in enumerate(rows[1:], 2):
            if len(row) != len(header):
                raise MetadataError(
                    f"{path}, row {number}, column count: value={len(row)}; expected "
                    f"{len(header)}; correct this data.csv row"
                )
            values = dict(zip(header, row, strict=True))
            result.append(tuple(values.get(name.lower()) for name, _ in self.columns))
        return result


def reader(path: Path) -> UploadReader:
    """Use the same pipe-delimited quoting and encoding as CSV stewardship uploads."""
    return UploadReader(
        UploadFile(0, "seed", path.name, path.stat().st_size, "", stored_name=path.name, path=path),
        UploadFormat.CSV,
    )


def discover(config: ConnectorConfig) -> tuple[Seed, ...]:
    """Refuse malformed seed folders before any replacement can start."""
    root = config.project_dir / "seeds"
    if not root.exists():
        return ()
    tables = sorted({path.parent for path in root.rglob("*.csv")})
    result = []
    for directory in tables:
        parts = directory.relative_to(root).parts
        if len(parts) != 3 or any(not is_safe_identifier(part) for part in parts):
            raise MetadataError(
                f"{directory}, row 0, column path: value={parts!r}; expected "
                "seeds/<catalog>/<schema>/<table>; move the seed files to that folder"
            )
        dialect = warehouse_dialect(config)
        identity = object_identity(".".join(parts), None, dialect.sqlglot_dialect)
        catalog = object_identity(f"{active_catalog(config)}.s.t", None, dialect.sqlglot_dialect)[0]
        if identity[0] != catalog:
            raise MetadataError(
                f"{directory}, row 0, column catalog: value={parts[0]!r}; expected "
                f"{catalog!r}; move the seed into the deployment's warehouse catalog folder"
            )
        for name in ("columns.csv", "data.csv"):
            if not (directory / name).is_file():
                raise MetadataError(
                    f"{directory / name}, row 0, column file: value=missing; expected "
                    f"a readable {name}; add it to the seed folder"
                )
            project_file(
                root,
                (directory / name).relative_to(config.project_dir).as_posix(),
                setting="seed",
                suffix=".csv",
            )
        columns, keys = _columns(directory / "columns.csv", dialect.sqlglot_dialect)
        digest = hashlib.sha256()
        for name in ("columns.csv", "data.csv"):
            content = (directory / name).read_bytes()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        seed = Seed(directory, identity, columns, keys, digest.hexdigest())
        seed.rows()
        result.append(seed)
    if len({seed.identity for seed in result}) != len(result):
        raise MetadataError(
            "seeds: duplicate warehouse table identity; "
            "expected one folder per table; rename the duplicate"
        )
    return tuple(result)


def _columns(
    path: Path, dialect: str | None
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    rows = list(reader(path).rows())
    if not rows or rows[0] != ("COLUMN_NAME", "DATA_TYPE", "KEY_FLAG"):
        raise MetadataError(
            f"{path}, row 1, column header: value={rows[0] if rows else None!r}; expected "
            "COLUMN_NAME|DATA_TYPE|KEY_FLAG; correct columns.csv's header"
        )
    columns, keys = [], []
    for number, row in enumerate(rows[1:], 2):
        if len(row) != 3:
            raise MetadataError(
                f"{path}, row {number}, column count: value={row!r}; "
                f"expected three fields; correct columns.csv"
            )
        name, kind, flag = (str(value) for value in row)
        if not is_safe_identifier(name) or name.lower() in ENGINE_COLUMNS:
            raise MetadataError(
                f"{path}, row {number}, column COLUMN_NAME: value={name!r}; "
                f"expected a business identifier; rename the column"
            )
        try:
            parsed = exp.DataType.build(kind, dialect=dialect)
            if parsed.this == exp.DataType.Type.UNKNOWN:
                raise MetadataError(
                    f"{path}, row {number}, column DATA_TYPE: value={kind!r}; "
                    "expected a known SQL type; correct columns.csv"
                )
            canonical = parsed.sql(dialect=dialect)
        except (SqlglotError, ValueError) as error:
            raise MetadataError(
                f"{path}, row {number}, column DATA_TYPE: value={kind!r}; "
                f"expected a SQL type; correct columns.csv"
            ) from error
        if flag not in (YesNo.YES, YesNo.NO):
            raise MetadataError(
                f"{path}, row {number}, column KEY_FLAG: value={flag!r}; "
                f"expected Y or N; correct columns.csv"
            )
        normalized = (
            Dialect.get_or_raise(dialect).normalize_identifier(exp.to_identifier(name)).name
        )
        columns.append((normalized, canonical))
        if flag == YesNo.YES:
            keys.append(name.lower())
    if not columns or len({name for name, _ in columns}) != len(columns):
        raise MetadataError(
            f"{path}, row 0, column COLUMN_NAME: value={columns!r}; "
            f"expected nonempty unique columns; correct columns.csv"
        )
    return tuple(columns), tuple(keys)


def cast_rows(conn: Connection, seed: Seed) -> list[dict[str, object]]:
    """Let the destination enforce its declared types; locate every bad value precisely."""
    result = []
    for number, row in enumerate(seed.rows(), 2):
        values = {}
        for (name, kind), value in zip(seed.columns, row, strict=True):
            try:
                values[name] = cast_value(conn, kind, value)
            except SQLAlchemyError as error:
                conn.rollback()
                raise MetadataError(
                    f"{seed.directory / 'data.csv'}, row {number}, column {name}: "
                    f"value={value!r}; expected {kind}; correct this seed value and rerun validate"
                ) from error
        result.append(values)
    return result
