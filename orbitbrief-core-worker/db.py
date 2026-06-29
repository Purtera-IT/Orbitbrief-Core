"""Postgres updates for orbitbrief_runs (async worker completion)."""

from __future__ import annotations

import os

import psycopg


def _conn():
    url = str(os.environ.get("DATABASE_URL", "") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for worker run status updates")
    return psycopg.connect(url, connect_timeout=10)


def mark_run_done(run_id: str, deal_id: str, pm_status: str | None) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.orbitbrief_runs
                SET status = 'done',
                    pm_status = %s,
                    finished_at = now(),
                    updated_at = now(),
                    error_message = NULL
                WHERE id = %s::uuid AND deal_id = %s::uuid
                """,
                (pm_status, run_id, deal_id),
            )
        conn.commit()


def mark_run_failed(run_id: str, deal_id: str, error_message: str) -> None:
    msg = (error_message or "Core compile failed")[:4000]
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.orbitbrief_runs
                SET status = 'failed',
                    error_message = %s,
                    finished_at = now(),
                    updated_at = now()
                WHERE id = %s::uuid AND deal_id = %s::uuid
                """,
                (msg, run_id, deal_id),
            )
        conn.commit()
