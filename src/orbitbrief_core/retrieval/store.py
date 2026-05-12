"""DuckDB + ``vss`` storage helper for the four retrieval indices.

Single DuckDB file holds four tables (``vec_evidence``, ``vec_packet``,
``vec_claim``, ``vec_example``). Each table has a *fixed-dim* float
column matching the embedder's output; vss requires a constant
dimension at table-creation time.

We deliberately keep **only IDs and minimal metadata** in these
tables — no text bodies. Re-hydration goes back to the
:class:`EvidenceRuntime` (Phase 1). That's the bounded-IO
contract from the Phase-2 spec.

HNSW index quirks (DuckDB ``vss`` 0.x today):

* ``SET hnsw_enable_experimental_persistence = true`` is required
  before creating the index if the table lives in a file (vs
  ``:memory:``). We set it on every connect to keep call sites
  simple — DuckDB ignores it for in-memory connections.
* HNSW WITH-options must be quoted strings:
  ``WITH (metric = 'cosine')``.
* HNSW indexes only accelerate ``ORDER BY array_cosine_distance(...)
  LIMIT k`` queries; full-scan kNN works without the index but is
  O(N).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import duckdb

from orbitbrief_core.retrieval.base import (
    INDEX_KIND_CLAIM,
    INDEX_KIND_EVIDENCE,
    INDEX_KIND_EXAMPLE,
    INDEX_KIND_PACKET,
    IndexKind,
)


# Map each retrieval kind to its physical table.
TABLE_FOR_KIND: dict[IndexKind, str] = {
    INDEX_KIND_EVIDENCE: "vec_evidence",
    INDEX_KIND_PACKET: "vec_packet",
    INDEX_KIND_CLAIM: "vec_claim",
    INDEX_KIND_EXAMPLE: "vec_example",
}


@dataclass(frozen=True)
class RetrievalStoreConfig:
    """Per-store config that callers must agree on across indices.

    ``dim`` must match the embedder output exactly. If you change
    embedders mid-life of a store, you have to drop and rebuild —
    HNSW indexes pin the column type to ``FLOAT[dim]``.
    """

    dim: int
    distance_metric: str = "cosine"  # vss supports: cosine, l2sq, ip


class RetrievalStore:
    """Owns the DuckDB connection + schema for all four indices."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        config: RetrievalStoreConfig,
        db_path: Path | None,
    ) -> None:
        self._conn = conn
        self._config = config
        self._db_path = db_path
        self._init_extensions()
        self._init_schema()

    # ───── lifecycle ─────

    @classmethod
    def connect(
        cls,
        config: RetrievalStoreConfig,
        db_path: Path | str | None = None,
    ) -> "RetrievalStore":
        if db_path is None:
            conn = duckdb.connect(":memory:")
            return cls(conn, config=config, db_path=None)
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(path))
        return cls(conn, config=config, db_path=path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RetrievalStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def config(self) -> RetrievalStoreConfig:
        return self._config

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Escape hatch — prefer the typed methods."""
        return self._conn

    # ───── schema / extensions ─────

    def _init_extensions(self) -> None:
        self._conn.execute("INSTALL vss")
        self._conn.execute("LOAD vss")
        # Required for persisted HNSW; safe no-op for in-memory.
        self._conn.execute("SET hnsw_enable_experimental_persistence = true")

    def _init_schema(self) -> None:
        dim = self._config.dim
        for table in TABLE_FOR_KIND.values():
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    project_id  VARCHAR     NOT NULL,
                    compile_id  VARCHAR     NOT NULL,
                    ref_id      VARCHAR     NOT NULL,
                    metadata    VARCHAR     NOT NULL,  -- json
                    vec         FLOAT[{dim}] NOT NULL,
                    PRIMARY KEY (project_id, compile_id, ref_id)
                )
                """
            )
            # Plain non-vector indexes for the project/compile filter
            # (so we don't full-scan the table when restricting the
            # search to one envelope).
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_pc "
                f"ON {table} (project_id, compile_id)"
            )

    def ensure_hnsw(self, kind: IndexKind) -> None:
        """Build the HNSW index for ``kind`` if it doesn't already exist.

        We don't auto-create HNSW at connect time because for tiny
        stores (<1K rows) HNSW build cost outweighs scan cost.
        Callers ask for it explicitly after bulk-loading.
        """
        table = TABLE_FOR_KIND[kind]
        metric = self._config.distance_metric
        # DuckDB doesn't support IF NOT EXISTS for HNSW — guard.
        existing = self._conn.execute(
            "SELECT count(*) FROM duckdb_indexes() WHERE index_name=?",
            [f"hnsw_{table}"],
        ).fetchone()
        if existing and existing[0]:
            return
        self._conn.execute(
            f"CREATE INDEX hnsw_{table} ON {table} "
            f"USING HNSW (vec) WITH (metric = '{metric}')"
        )

    # ───── ingest ─────

    def upsert(
        self,
        kind: IndexKind,
        *,
        project_id: str,
        compile_id: str,
        rows: Sequence[tuple[str, dict, list[float]]],
    ) -> int:
        """Bulk-upsert ``(ref_id, metadata, vec)`` tuples for one envelope.

        Replaces existing rows for ``(project_id, compile_id, ref_id)``
        — handy for re-running indexers on the same compile.
        Returns row count written.
        """
        if not rows:
            return 0
        table = TABLE_FOR_KIND[kind]
        # DELETE then INSERT (DuckDB has no UPSERT pre-1.0; we pin
        # >=1.0 so technically we could ON CONFLICT, but that makes
        # the SQL harder to read for negligible perf gain on the
        # small batches we expect per compile).
        ref_ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in ref_ids)
        self._conn.execute(
            f"DELETE FROM {table} WHERE project_id=? AND compile_id=? "
            f"AND ref_id IN ({placeholders})",
            [project_id, compile_id, *ref_ids],
        )
        import json

        payload = [
            (project_id, compile_id, ref_id, json.dumps(meta), vec)
            for ref_id, meta, vec in rows
        ]
        self._conn.executemany(
            f"INSERT INTO {table} (project_id, compile_id, ref_id, metadata, vec) "
            f"VALUES (?, ?, ?, ?, ?)",
            payload,
        )
        return len(payload)

    def delete_for_envelope(
        self, kind: IndexKind, *, project_id: str, compile_id: str
    ) -> int:
        table = TABLE_FOR_KIND[kind]
        n = self._conn.execute(
            f"SELECT count(*) FROM {table} WHERE project_id=? AND compile_id=?",
            [project_id, compile_id],
        ).fetchone()[0]
        self._conn.execute(
            f"DELETE FROM {table} WHERE project_id=? AND compile_id=?",
            [project_id, compile_id],
        )
        return int(n)

    # ───── reads ─────

    def count(
        self, kind: IndexKind, *, project_id: str, compile_id: str
    ) -> int:
        table = TABLE_FOR_KIND[kind]
        row = self._conn.execute(
            f"SELECT count(*) FROM {table} WHERE project_id=? AND compile_id=?",
            [project_id, compile_id],
        ).fetchone()
        return int(row[0]) if row else 0

    def iter_ref_ids(
        self, kind: IndexKind, *, project_id: str, compile_id: str
    ) -> Iterable[str]:
        table = TABLE_FOR_KIND[kind]
        for (rid,) in self._conn.execute(
            f"SELECT ref_id FROM {table} WHERE project_id=? AND compile_id=? ORDER BY ref_id",
            [project_id, compile_id],
        ).fetchall():
            yield str(rid)

    def search(
        self,
        kind: IndexKind,
        *,
        project_id: str,
        compile_id: str,
        query_vec: list[float],
        top_k: int,
    ) -> list[tuple[str, float, dict]]:
        """kNN search returning ``[(ref_id, score, metadata), ...]`` desc by score.

        ``score = 1 - cosine_distance`` so 1.0 is exact match, 0.0
        is orthogonal. Bounded above at 1.0 (HNSW occasionally
        returns -ε due to FP noise; we clamp).
        """
        if len(query_vec) != self._config.dim:
            raise ValueError(
                f"query_vec dim {len(query_vec)} != store dim {self._config.dim}"
            )
        table = TABLE_FOR_KIND[kind]
        # Build a SQL literal of the query vector. DuckDB supports
        # bound parameters for FLOAT[] but only via the array
        # constructor; building inline avoids the extra cast.
        vec_literal = "[" + ", ".join(repr(float(x)) for x in query_vec) + f"]::FLOAT[{self._config.dim}]"
        sql = (
            f"SELECT ref_id, "
            f"  1.0 - array_cosine_distance(vec, {vec_literal}) AS score, "
            f"  metadata "
            f"FROM {table} "
            f"WHERE project_id=? AND compile_id=? "
            f"ORDER BY array_cosine_distance(vec, {vec_literal}) "
            f"LIMIT ?"
        )
        import json

        out: list[tuple[str, float, dict]] = []
        for ref_id, score, meta in self._conn.execute(
            sql, [project_id, compile_id, int(top_k)]
        ).fetchall():
            s = float(score)
            if s > 1.0:
                s = 1.0
            elif s < 0.0:
                s = 0.0
            out.append((str(ref_id), s, json.loads(meta) if meta else {}))
        return out
