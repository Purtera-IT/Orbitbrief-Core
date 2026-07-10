"""DuckDB-backed storage for the Evidence Runtime.

One DuckDB connection per :class:`EvidenceStore`. Tables are normalized
*per envelope row* (atom / entity / edge / packet / document / quality)
with first-class indexed columns for fast queries, plus a single
``manifests`` table that holds the **original envelope bytes** so the
runtime round-trips losslessly:

    envelope_dict → store → ``to_envelope_dict()`` → identical dict

Why store the original bytes instead of reconstructing from the rows?
Pydantic re-serialization can reorder optional fields and lose unknown
extras. Phase-1 contract demands lossless round-trip, so we keep the
canonical form in ``manifests.envelope_blob`` and use the row tables
purely for indexed access.

Indexes follow the spec:
* ``atoms (project_id, compile_id, artifact_id)`` — lookups per artifact
* ``atoms (project_id, compile_id, atom_type)`` — type filters
* ``atoms_entity_keys (project_id, compile_id, entity_key)`` — atom
  search by entity (atoms can have multiple keys → side table)
* ``packets (project_id, compile_id, family, anchor_key)`` — the
  spec's primary lookup
* ``edges (project_id, compile_id, edge_type, from_atom_id)`` and
  ``(…, to_atom_id)`` — graph walks and contradiction lookups

Public surface:
    EvidenceStore.connect(path: Path | None = None) → in-memory by default
    .ingest_envelope(envelope_dict)                  → write all rows
    .fetch_envelope_dict(project_id, compile_id)     → original bytes
    .iter_*(project_id, compile_id, …)               → typed row dicts
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import duckdb


SCHEMA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS manifests (
        project_id      VARCHAR NOT NULL,
        compile_id      VARCHAR NOT NULL,
        schema_version  VARCHAR NOT NULL,
        generated_at    VARCHAR NOT NULL,
        envelope_blob   VARCHAR NOT NULL,
        PRIMARY KEY (project_id, compile_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS atoms (
        project_id      VARCHAR NOT NULL,
        compile_id      VARCHAR NOT NULL,
        atom_id         VARCHAR NOT NULL,
        artifact_id     VARCHAR NOT NULL,
        atom_type       VARCHAR NOT NULL,
        authority_class VARCHAR NOT NULL,
        confidence      DOUBLE  NOT NULL,
        text            VARCHAR NOT NULL,
        section_path    VARCHAR NOT NULL,  -- json list
        locator         VARCHAR NOT NULL,  -- json object
        verified        VARCHAR NOT NULL,
        data            VARCHAR NOT NULL,  -- full envelope-row dict
        PRIMARY KEY (project_id, compile_id, atom_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS atom_entity_keys (
        project_id  VARCHAR NOT NULL,
        compile_id  VARCHAR NOT NULL,
        atom_id     VARCHAR NOT NULL,
        entity_key  VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        project_id      VARCHAR NOT NULL,
        compile_id      VARCHAR NOT NULL,
        entity_id       VARCHAR NOT NULL,
        entity_type     VARCHAR NOT NULL,
        canonical_key   VARCHAR NOT NULL,
        canonical_name  VARCHAR NOT NULL,
        review_status   VARCHAR NOT NULL,
        confidence      DOUBLE  NOT NULL,
        data            VARCHAR NOT NULL,  -- full envelope-row dict
        PRIMARY KEY (project_id, compile_id, entity_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS edges (
        project_id      VARCHAR NOT NULL,
        compile_id      VARCHAR NOT NULL,
        edge_id         VARCHAR NOT NULL,
        edge_type       VARCHAR NOT NULL,
        from_atom_id    VARCHAR NOT NULL,
        to_atom_id      VARCHAR NOT NULL,
        reason          VARCHAR NOT NULL,
        confidence      DOUBLE  NOT NULL,
        cross_artifact  BOOLEAN NOT NULL,
        data            VARCHAR NOT NULL,
        PRIMARY KEY (project_id, compile_id, edge_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS packets (
        project_id      VARCHAR NOT NULL,
        compile_id      VARCHAR NOT NULL,
        packet_id       VARCHAR NOT NULL,
        family          VARCHAR NOT NULL,
        anchor_type     VARCHAR NOT NULL,
        anchor_key      VARCHAR NOT NULL,
        status          VARCHAR NOT NULL,
        confidence      DOUBLE  NOT NULL,
        reason          VARCHAR NOT NULL,
        data            VARCHAR NOT NULL,
        PRIMARY KEY (project_id, compile_id, packet_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        project_id      VARCHAR NOT NULL,
        compile_id      VARCHAR NOT NULL,
        artifact_id     VARCHAR NOT NULL,
        artifact_type   VARCHAR NOT NULL,
        filename        VARCHAR NOT NULL,
        sha256          VARCHAR NOT NULL,
        size_bytes      BIGINT  NOT NULL,
        parser_name     VARCHAR NOT NULL,
        parser_version  VARCHAR NOT NULL,
        data            VARCHAR NOT NULL,
        PRIMARY KEY (project_id, compile_id, artifact_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quality (
        project_id  VARCHAR NOT NULL,
        compile_id  VARCHAR NOT NULL,
        metric      VARCHAR NOT NULL,
        value       VARCHAR NOT NULL,  -- json-encoded
        PRIMARY KEY (project_id, compile_id, metric)
    )
    """,
    # Indexes per the Phase-1 spec. DuckDB silently no-ops IF NOT
    # EXISTS for indexes, so re-running connect() is safe.
    "CREATE INDEX IF NOT EXISTS ix_atoms_artifact ON atoms (project_id, compile_id, artifact_id)",
    "CREATE INDEX IF NOT EXISTS ix_atoms_type ON atoms (project_id, compile_id, atom_type)",
    "CREATE INDEX IF NOT EXISTS ix_aek_key ON atom_entity_keys (project_id, compile_id, entity_key)",
    "CREATE INDEX IF NOT EXISTS ix_entities_key ON entities (project_id, compile_id, canonical_key)",
    "CREATE INDEX IF NOT EXISTS ix_edges_from ON edges (project_id, compile_id, edge_type, from_atom_id)",
    "CREATE INDEX IF NOT EXISTS ix_edges_to ON edges (project_id, compile_id, edge_type, to_atom_id)",
    "CREATE INDEX IF NOT EXISTS ix_packets_family ON packets (project_id, compile_id, family, anchor_key)",
)


# Canonical JSON serialization used both at ingest (stored in
# ``envelope_blob``) and at re-emit (``to_envelope_text``). Two passes
# over the same dict produce byte-identical bytes — that's the
# Phase-1 round-trip guarantee.
JSON_INDENT = 2


def canonical_json(payload: dict[str, Any] | list[Any]) -> str:
    """Bytes-stable JSON encoding shared by ingest and re-emit.

    * ``indent=2`` and ``ensure_ascii=False`` for human-diffable output.
    * ``sort_keys=False`` because Python dicts preserve insertion order
      and we want to round-trip the producer's intended order.
    """
    return json.dumps(payload, indent=JSON_INDENT, ensure_ascii=False, sort_keys=False)


# ────────────────────────────── store ──────────────────────────────────


@dataclass(frozen=True)
class EnvelopeKey:
    """Composite primary key shared by every row table."""

    project_id: str
    compile_id: str


class EvidenceStore:
    """Thin DuckDB wrapper. Connection-owned schema + ingest + read paths.

    Use :meth:`connect` (factory) so we can swap in-memory and on-disk
    paths uniformly. Closing is via :meth:`close` or context-manager.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection, *, db_path: Path | None) -> None:
        self._conn = conn
        self._db_path = db_path
        self._init_schema()

    # ───── connection lifecycle ─────

    @classmethod
    def connect(cls, db_path: Path | str | None = None) -> "EvidenceStore":
        """Open a DuckDB connection.

        ``None`` → ephemeral in-memory store (great for tests + CLI
        smoke). A path → persistent file; the file is created on
        first use and reused on subsequent opens.
        """
        if db_path is None:
            conn = duckdb.connect(":memory:")
            return cls(conn, db_path=None)
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(path))
        return cls(conn, db_path=path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EvidenceStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Escape hatch for advanced queries — prefer the typed methods."""
        return self._conn

    def _init_schema(self) -> None:
        for ddl in SCHEMA_DDL:
            self._conn.execute(ddl)

    # ───── ingest ─────

    def ingest_envelope(self, envelope: dict[str, Any]) -> EnvelopeKey:
        """Insert one envelope's rows into the store.

        The envelope is stored verbatim in ``manifests.envelope_blob``
        so :meth:`fetch_envelope_dict` can re-emit byte-identical
        bytes. Per-row tables exist only for indexed access.

        Re-ingesting the same (project_id, compile_id) replaces the
        prior rows; this is the contract for re-running compiles
        during dev. CI-deterministic loads should use distinct
        compile_ids per run.
        """
        project_id = str(envelope["project_id"])
        compile_id = str(envelope["compile_id"])
        key = EnvelopeKey(project_id=project_id, compile_id=compile_id)

        self._delete_for_key(key)

        envelope_blob = canonical_json(envelope)
        self._conn.execute(
            """
            INSERT INTO manifests
              (project_id, compile_id, schema_version, generated_at, envelope_blob)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                project_id,
                compile_id,
                str(envelope.get("schema_version", "")),
                str(envelope.get("generated_at", "")),
                envelope_blob,
            ],
        )
        self._ingest_documents(key, envelope.get("documents") or [])
        self._ingest_atoms(key, envelope.get("atoms") or [])
        self._ingest_entities(key, envelope.get("entities") or [])
        self._ingest_edges(key, envelope.get("edges") or [])
        self._ingest_packets(key, envelope.get("packets") or [])
        self._ingest_quality(key, envelope.get("summary") or {})

        return key

    def _delete_for_key(self, key: EnvelopeKey) -> None:
        for table in (
            "manifests",
            "atoms",
            "atom_entity_keys",
            "entities",
            "edges",
            "packets",
            "documents",
            "quality",
        ):
            self._conn.execute(
                f"DELETE FROM {table} WHERE project_id = ? AND compile_id = ?",
                [key.project_id, key.compile_id],
            )

    def _ingest_documents(self, key: EnvelopeKey, docs: list[dict[str, Any]]) -> None:
        rows = []
        for d in docs:
            rows.append(
                (
                    key.project_id,
                    key.compile_id,
                    str(d["artifact_id"]),
                    str(d.get("artifact_type", "")),
                    str(d.get("filename", "")),
                    str(d.get("sha256", "")),
                    int(d.get("size_bytes", 0)),
                    str(d.get("parser_name", "")),
                    str(d.get("parser_version", "")),
                    canonical_json(d),
                )
            )
        if rows:
            self._conn.executemany(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )

    def _ingest_atoms(self, key: EnvelopeKey, atoms: list[dict[str, Any]]) -> None:
        atom_rows = []
        key_rows = []
        seen_atom_ids: set[str] = set()
        for a in atoms:
            atom_id = str(a["id"])
            # Parser envelopes occasionally emit duplicate atom ids; DuckDB
            # PK on (project_id, compile_id, atom_id) hard-fails the compile.
            if atom_id in seen_atom_ids:
                continue
            seen_atom_ids.add(atom_id)
            atom_rows.append(
                (
                    key.project_id,
                    key.compile_id,
                    atom_id,
                    str(a["artifact_id"]),
                    str(a["atom_type"]),
                    str(a["authority_class"]),
                    float(a.get("confidence", 0.0)),
                    str(a.get("text", "")),
                    canonical_json(a.get("section_path") or []),
                    canonical_json(a.get("locator") or {}),
                    str(a.get("verified", "unverified")),
                    canonical_json(a),
                )
            )
            # Compact envelope rows don't ship entity_keys (they're
            # only in the indexes block). We mine them from the
            # ``indexes.atoms_by_entity_key`` map at the runtime
            # level instead — ingest path leaves this empty.
        if atom_rows:
            self._conn.executemany(
                "INSERT INTO atoms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                atom_rows,
            )
        if key_rows:  # pragma: no cover — populated via _ingest_entity_key_index
            self._conn.executemany(
                "INSERT INTO atom_entity_keys VALUES (?, ?, ?, ?)", key_rows
            )

    def ingest_atom_entity_keys_index(
        self,
        key: EnvelopeKey,
        atoms_by_entity_key: dict[str, list[str]],
    ) -> None:
        """Populate the entity_key side table from the envelope's pre-built index.

        Called from the runtime layer after :meth:`ingest_envelope`
        because the source data lives under ``envelope.indexes`` —
        keeping it out of :meth:`_ingest_atoms` keeps the ingest
        method's responsibilities clean.
        """
        rows = [
            (key.project_id, key.compile_id, atom_id, entity_key)
            for entity_key, atom_ids in (atoms_by_entity_key or {}).items()
            for atom_id in atom_ids
        ]
        if rows:
            self._conn.executemany(
                "INSERT INTO atom_entity_keys VALUES (?, ?, ?, ?)", rows
            )

    def _ingest_entities(self, key: EnvelopeKey, entities: list[dict[str, Any]]) -> None:
        rows = []
        for e in entities:
            rows.append(
                (
                    key.project_id,
                    key.compile_id,
                    str(e["id"]),
                    str(e["entity_type"]),
                    str(e["canonical_key"]),
                    str(e["canonical_name"]),
                    str(e.get("review_status", "")),
                    float(e.get("confidence", 0.0)),
                    canonical_json(e),
                )
            )
        if rows:
            self._conn.executemany(
                "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )

    def _ingest_edges(self, key: EnvelopeKey, edges: list[dict[str, Any]]) -> None:
        rows = []
        for e in edges:
            rows.append(
                (
                    key.project_id,
                    key.compile_id,
                    str(e["id"]),
                    str(e["edge_type"]),
                    str(e["from_atom_id"]),
                    str(e["to_atom_id"]),
                    str(e.get("reason", "")),
                    float(e.get("confidence", 0.0)),
                    bool(e.get("cross_artifact", False)),
                    canonical_json(e),
                )
            )
        if rows:
            self._conn.executemany(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )

    def _ingest_packets(self, key: EnvelopeKey, packets: list[dict[str, Any]]) -> None:
        rows = []
        for p in packets:
            rows.append(
                (
                    key.project_id,
                    key.compile_id,
                    str(p["id"]),
                    str(p["family"]),
                    str(p["anchor_type"]),
                    str(p["anchor_key"]),
                    str(p["status"]),
                    float(p.get("confidence", 0.0)),
                    str(p.get("reason", "")),
                    canonical_json(p),
                )
            )
        if rows:
            self._conn.executemany(
                "INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )

    def _ingest_quality(self, key: EnvelopeKey, summary: dict[str, Any]) -> None:
        """Persist envelope ``summary`` rollups under the quality table."""
        rows = [
            (key.project_id, key.compile_id, metric, canonical_json(value))
            for metric, value in (summary or {}).items()
        ]
        if rows:
            self._conn.executemany(
                "INSERT INTO quality VALUES (?, ?, ?, ?)", rows
            )

    # ───── reads ─────

    def fetch_envelope_text(self, key: EnvelopeKey) -> str | None:
        row = self._conn.execute(
            "SELECT envelope_blob FROM manifests WHERE project_id=? AND compile_id=?",
            [key.project_id, key.compile_id],
        ).fetchone()
        return None if row is None else str(row[0])

    def fetch_envelope_dict(self, key: EnvelopeKey) -> dict[str, Any] | None:
        text = self.fetch_envelope_text(key)
        return None if text is None else json.loads(text)

    def fetch_atom(self, key: EnvelopeKey, atom_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT data FROM atoms WHERE project_id=? AND compile_id=? AND atom_id=?",
            [key.project_id, key.compile_id, atom_id],
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def fetch_entity(self, key: EnvelopeKey, entity_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT data FROM entities WHERE project_id=? AND compile_id=? AND entity_id=?",
            [key.project_id, key.compile_id, entity_id],
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def iter_packets(
        self,
        key: EnvelopeKey,
        *,
        family: str | None = None,
        anchor_key: str | None = None,
        status: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream packets matching optional filters in ``(family, anchor_key)`` order."""
        where = ["project_id=?", "compile_id=?"]
        params: list[Any] = [key.project_id, key.compile_id]
        if family is not None:
            where.append("family=?")
            params.append(family)
        if anchor_key is not None:
            where.append("anchor_key=?")
            params.append(anchor_key)
        if status is not None:
            where.append("status=?")
            params.append(status)
        sql = (
            "SELECT data FROM packets WHERE "
            + " AND ".join(where)
            + " ORDER BY family, anchor_key, packet_id"
        )
        for (blob,) in self._conn.execute(sql, params).fetchall():
            yield json.loads(blob)

    def iter_edges(
        self,
        key: EnvelopeKey,
        *,
        edge_type: str | None = None,
        from_atom_id: str | None = None,
        to_atom_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        where = ["project_id=?", "compile_id=?"]
        params: list[Any] = [key.project_id, key.compile_id]
        if edge_type is not None:
            where.append("edge_type=?")
            params.append(edge_type)
        if from_atom_id is not None:
            where.append("from_atom_id=?")
            params.append(from_atom_id)
        if to_atom_id is not None:
            where.append("to_atom_id=?")
            params.append(to_atom_id)
        sql = (
            "SELECT data FROM edges WHERE "
            + " AND ".join(where)
            + " ORDER BY edge_type, from_atom_id, to_atom_id, edge_id"
        )
        for (blob,) in self._conn.execute(sql, params).fetchall():
            yield json.loads(blob)

    def iter_atoms_for_entity_key(
        self, key: EnvelopeKey, entity_key: str
    ) -> Iterator[dict[str, Any]]:
        sql = """
        SELECT a.data FROM atoms a
        JOIN atom_entity_keys k
          ON k.project_id=a.project_id AND k.compile_id=a.compile_id AND k.atom_id=a.atom_id
        WHERE k.project_id=? AND k.compile_id=? AND k.entity_key=?
        ORDER BY a.atom_id
        """
        for (blob,) in self._conn.execute(
            sql, [key.project_id, key.compile_id, entity_key]
        ).fetchall():
            yield json.loads(blob)

    def list_envelopes(self) -> list[EnvelopeKey]:
        """Return every (project_id, compile_id) currently stored, deterministic order."""
        rows = self._conn.execute(
            "SELECT project_id, compile_id FROM manifests "
            "ORDER BY project_id, compile_id"
        ).fetchall()
        return [EnvelopeKey(project_id=p, compile_id=c) for p, c in rows]
