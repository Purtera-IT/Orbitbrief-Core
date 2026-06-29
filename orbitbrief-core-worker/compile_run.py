"""
Orbitbrief-Core compile for a queued orbitbrief_runs row.
Downloads envelope.json, runs compile_brief.py, uploads artifacts to blob run/ + optional latest/.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("orbitbrief-core-worker")

from azure.storage.blob import BlobServiceClient, ContentSettings

ARTIFACT_FILES = (
    ("PM_HANDOFF.json", "application/json"),
    ("PM_HANDOFF.html", "text/html; charset=utf-8"),
    ("91_inspection_report.html", "text/html; charset=utf-8"),
    # SOW_DRAFT.md is owned by SowSmith (rendered by parser-os-worker
    # directly to deals/{id}/orbitbrief/latest/SOW_DRAFT.md).  Removed
    # here so Orbitbrief-Core doesn't overwrite the SowSmith version.
    ("polish_report.json", "application/json"),
    ("pipeline_log.json", "application/json"),
    ("PM_QUESTION_QUEUE.csv", "text/csv; charset=utf-8"),
    # Harvest for the calibration head: one row per brain claim (10 signals +
    # claim text + cited evidence + the rule verdict). _label_claim_verdicts.py
    # reads these across deals to build the calibration-head trainset.
    ("calibration_signals.jsonl", "application/x-ndjson"),
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or default).strip()


def _blob_client() -> BlobServiceClient:
    conn = _env("ORBITBRIEF_ARTIFACTS_CONNECTION_STRING")
    if not conn:
        raise RuntimeError("ORBITBRIEF_ARTIFACTS_CONNECTION_STRING is required")
    return BlobServiceClient.from_connection_string(conn)


def _container() -> str:
    return _env("ORBITBRIEF_ARTIFACTS_CONTAINER", "orbitbrief-artifacts")


def _download_envelope(client: BlobServiceClient, deal_id: str, dest: Path) -> None:
    blob = f"deals/{deal_id}/orbitbrief/latest/envelope.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        client.get_blob_client(_container(), blob).download_blob().readinto(f)


def _upload_file(
    client: BlobServiceClient,
    deal_id: str,
    prefix: str,
    file_name: str,
    local_path: Path,
    content_type: str,
) -> None:
    if not local_path.is_file():
        return
    blob = f"deals/{deal_id}/orbitbrief/{prefix}/{file_name}"
    with open(local_path, "rb") as f:
        client.get_blob_client(_container(), blob).upload_blob(
            f,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )


def _write_calibration_signals(out_dir: Path, envelope_path: Path) -> None:
    """Consolidate ``60_calibrations/<pack>.json`` into one JSONL row per brain
    claim (signals + claim text + cited evidence + rule verdict) — the harvest
    for the calibration head. Best-effort: never fail the compile."""
    try:
        cal_dir = out_dir / "60_calibrations"
        if not cal_dir.is_dir():
            return
        atom_text: dict[str, str] = {}
        try:
            env = json.loads(envelope_path.read_text(encoding="utf-8"))
            for a in env.get("atoms", []) or []:
                if isinstance(a, dict) and a.get("id"):
                    atom_text[a["id"]] = str(a.get("text") or "")[:300]
        except Exception:
            pass
        rows: list[dict] = []
        for jf in sorted(cal_dir.glob("*.json")):
            try:
                rep = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            pack = rep.get("brain") or jf.stem
            for it in rep.get("items", []) or []:
                payload = it.get("payload") or {}
                claim = (
                    payload.get("text") or payload.get("claim") or payload.get("statement")
                    or payload.get("description") or payload.get("body") or ""
                )
                atom_ids = payload.get("supporting_atom_ids") or []
                evidence = [atom_text[a] for a in atom_ids if a in atom_text][:6]
                ref = it.get("ref")
                rows.append({
                    "pack": pack,
                    "section": ref.get("section") if isinstance(ref, dict) else None,
                    "claim": str(claim)[:600],
                    "evidence": evidence,
                    "signals": it.get("signals") or {},
                    "rule_verdict": it.get("verdict"),
                    "calibrated_confidence": it.get("calibrated_confidence"),
                })
        if rows:
            (out_dir / "calibration_signals.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                encoding="utf-8",
            )
    except Exception as exc:  # never block the compile on harvest
        log.warning("calibration_signals harvest skipped: %s", exc)


def _forward_handoff_skip_warnings(stderr: str) -> None:
    """Surface a swallowed PM-handoff render failure to the worker log.

    compile_brief.py's PM-handoff render block catches downstream errors,
    prints "compile_brief: PM handoff render skipped: <traceback>" to stderr,
    and STILL exits 0 — so a failed handoff looks like a successful run and the
    traceback is invisible in Container Apps logs (this hid a narrator
    TypeError for weeks).  When the subprocess exits 0, scan stderr for the
    skip marker and log.warning it plus the trailing traceback lines so the
    failure is visible without changing exit semantics.
    """
    if not stderr or "render skipped" not in stderr:
        return
    lines = stderr.splitlines()
    for i, line in enumerate(lines):
        if "render skipped" not in line:
            continue
        # Forward the marker line plus the traceback that print_exc() emitted
        # right after it (Traceback / indented frames / final exception line),
        # stopping at the next blank line or a non-traceback log line.
        block = [line.rstrip()]
        for follow in lines[i + 1 :]:
            stripped = follow.strip()
            if not stripped:
                break
            if (
                stripped.startswith("Traceback")
                or follow.startswith(" ")
                or stripped.startswith("File ")
                or ": " in stripped  # final "ExcType: message" line
            ):
                block.append(follow.rstrip())
            else:
                break
        log.warning(
            "compile_brief swallowed a PM_HANDOFF render failure (exit 0):\n%s",
            "\n".join(block),
        )


def _run_compile(envelope_path: Path, out_dir: Path) -> None:
    core_root = Path(_env("ORBITBRIEF_CORE_ROOT", "/app/Orbitbrief-Core"))
    parser_root = Path(_env("PARSER_OS_ROOT", "/app/parser-os"))
    compile_py = core_root / "compile_brief.py"
    if not compile_py.is_file():
        raise RuntimeError(f"compile_brief.py not found at {compile_py}")

    ollama_url = _env(
        "OLLAMA_BASE_URL",
        "https://ollama-mac-proxy-dev-eus2.whitehill-a3348ba5.eastus2.azurecontainerapps.io",
    )
    chat_model = _env("ORBITBRIEF_CHAT_MODEL", _env("CHAT_MODEL", "qwen3:14b"))

    py_path = os.pathsep.join(
        [str(parser_root), str(core_root / "src"), os.environ.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    cmd = [
        sys.executable,
        str(compile_py),
        str(envelope_path),
        "--out",
        str(out_dir),
        "--quiet-parser",
        "--ollama",
        "--ollama-base-url",
        ollama_url,
        "--chat-model",
        chat_model,
    ]
    env = {**os.environ, "PYTHONPATH": py_path}
    proc = subprocess.run(
        cmd,
        cwd=str(core_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=int(_env("COMPILE_TIMEOUT_SEC", "840")),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-4000:]
        raise RuntimeError(
            f"compile_brief.py exited {proc.returncode}"
            + (f": {detail}" if detail else "")
        )

    # Exit 0 doesn't mean the PM handoff rendered — compile_brief.py swallows
    # render errors and exits 0 anyway.  Forward any swallowed skip warning.
    _forward_handoff_skip_warnings(proc.stderr or "")


def _pipeline_telemetry_summary(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "pipeline_log.json"
    if not path.is_file():
        return {"stage_count": 0, "total_stage_ms": 0, "stages": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"stage_count": 0, "total_stage_ms": 0, "stages": []}
    rows = payload if isinstance(payload, list) else []
    stages: list[dict[str, Any]] = []
    total_ms = 0
    for row in rows[:30]:
        if not isinstance(row, dict):
            continue
        dur = int(row.get("duration_ms") or 0)
        total_ms += dur
        stages.append(
            {
                "stage": row.get("stage") or row.get("name"),
                "status": row.get("status"),
                "duration_ms": dur,
            }
        )
    return {"stage_count": len(rows), "total_stage_ms": total_ms, "stages": stages}


def _read_pm_status(handoff_path: Path) -> str | None:
    if not handoff_path.is_file():
        return None
    try:
        data = json.loads(handoff_path.read_text(encoding="utf-8"))
        status = data.get("status")
        return str(status) if status else None
    except (json.JSONDecodeError, OSError):
        return None


def _archive_latest_handoff(client: BlobServiceClient, deal_id: str) -> None:
    """Copy current latest PM_HANDOFF to history/{compile_id}/ before overwrite."""
    latest_blob = f"deals/{deal_id}/orbitbrief/latest/PM_HANDOFF.json"
    try:
        old = client.get_blob_client(_container(), latest_blob).download_blob().readall()
    except Exception:
        return
    try:
        data = json.loads(old.decode("utf-8"))
    except json.JSONDecodeError:
        return
    compile_id = str(data.get("compile_id") or (data.get("run_telemetry") or {}).get("compile_id") or "").strip()
    if not compile_id:
        return
    safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in compile_id)[:128]
    history_blob = f"deals/{deal_id}/orbitbrief/history/{safe_id}/PM_HANDOFF.json"
    client.get_blob_client(_container(), history_blob).upload_blob(
        old,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def _upsert_compile_history_index(client: BlobServiceClient, deal_id: str, handoff: dict[str, Any]) -> None:
    compile_id = str(handoff.get("compile_id") or (handoff.get("run_telemetry") or {}).get("compile_id") or "").strip()
    if not compile_id:
        return
    safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in compile_id)[:128]
    generated_at = str(handoff.get("generated_at") or (handoff.get("run_telemetry") or {}).get("generated_at") or "")
    pqs = handoff.get("parser_quality_score") or {}
    row = {
        "compile_id": safe_id,
        "generated_at": generated_at,
        "blob_prefix": f"deals/{deal_id}/orbitbrief/history/{safe_id}",
        "parser_grade": pqs.get("grade"),
        "parser_score": pqs.get("score"),
    }
    index_blob = f"deals/{deal_id}/orbitbrief/latest/compile-history.json"
    entries: list[dict[str, Any]] = []
    try:
        raw = client.get_blob_client(_container(), index_blob).download_blob().readall()
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict) and isinstance(parsed.get("entries"), list):
            entries = parsed["entries"]
        elif isinstance(parsed, list):
            entries = parsed
    except Exception:
        entries = []
    entries = [e for e in entries if str(e.get("compile_id") or "") != safe_id]
    entries.insert(0, row)
    retain = int(_env("ORBITBRIEF_COMPILE_HISTORY_RETAIN", "20") or "20")
    payload = {"version": 1, "retention_max": retain, "entries": entries[: max(retain, 1)]}
    body = json.dumps(payload, indent=2).encode("utf-8")
    client.get_blob_client(_container(), index_blob).upload_blob(
        body,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def compile_orbitbrief_run(
    deal_id: str,
    run_id: str,
    *,
    mirror_latest: bool = True,
) -> dict[str, Any]:
    """Run Core compile and upload artifacts. Returns summary dict for API response."""
    t0 = time.time()
    client = _blob_client()
    written: list[str] = []

    with tempfile.TemporaryDirectory(prefix="ob-core-") as tmp:
        work = Path(tmp)
        envelope_path = work / "envelope.json"
        out_dir = work / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        _download_envelope(client, deal_id, envelope_path)
        if mirror_latest:
            _archive_latest_handoff(client, deal_id)
        # v45.2: don't let subprocess errors short-circuit artifact upload.
        # When compile_brief.py exits non-zero, we still want to upload
        # any pipeline_log.json the pipeline's crash-resilient handler
        # wrote locally — that's the only way we see WHY it failed.  Catch,
        # upload available artifacts, then re-raise.
        compile_error: Exception | None = None
        try:
            _run_compile(envelope_path, out_dir)
        except Exception as exc:
            compile_error = exc
            log.exception(
                "compile_brief.py raised; will still upload any artifacts: %s",
                exc,
            )

        handoff_path = out_dir / "PM_HANDOFF.json"
        pm_status = _read_pm_status(handoff_path)
        _write_calibration_signals(out_dir, envelope_path)

        for file_name, content_type in ARTIFACT_FILES:
            local = out_dir / file_name
            if not local.is_file() and file_name == "PM_QUESTION_QUEUE.csv":
                local.write_text("# PM_QUESTION_QUEUE (empty)\n", encoding="utf-8")
            _upload_file(client, deal_id, run_id, file_name, local, content_type)
            if local.is_file() or file_name == "PM_QUESTION_QUEUE.csv":
                written.append(f"{run_id}/{file_name}")
            if mirror_latest:
                _upload_file(client, deal_id, "latest", file_name, local, content_type)
                if local.is_file():
                    written.append(f"latest/{file_name}")

        compile_id = None
        case_id = None
        handoff_payload: dict[str, Any] | None = None
        if handoff_path.is_file():
            try:
                handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
                compile_id = handoff_payload.get("compile_id")
                case_id = handoff_payload.get("case_id")
            except json.JSONDecodeError:
                pass

        if mirror_latest and handoff_payload:
            _upsert_compile_history_index(client, deal_id, handoff_payload)

        pipeline = _pipeline_telemetry_summary(out_dir)
        duration_ms = int((time.time() - t0) * 1000)
        log.info(
            "orbitbrief_pipeline deal=%s run=%s %s",
            deal_id,
            run_id,
            json.dumps(
                {
                    "duration_ms": duration_ms,
                    "pm_status": pm_status,
                    "case_id": case_id,
                    **pipeline,
                },
                default=str,
            ),
        )

    if compile_error is not None:
        # v45.2: we uploaded whatever pipeline_log / partial artifacts the
        # crash-resilient handler wrote.  Now re-raise so the run is marked
        # 'failed' in orbitbrief_runs and the caller knows the brief is
        # incomplete.  pipeline_log.json in blob still shows per-stage
        # detail for diagnosis.
        raise compile_error

    return {
        "ok": True,
        "deal_id": deal_id,
        "run_id": run_id,
        "pm_status": pm_status,
        "compile_id": compile_id,
        "case_id": case_id,
        "artifacts_written": written,
        "duration_ms": duration_ms,
        "mirror_latest": mirror_latest,
        "pipeline": pipeline,
    }
