"""orbitbrief-core-worker: a failed brief is recorded and never leaves latest/
looking current; feedback stays with its deal; one compile per deal at a time."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orbitbrief-core-worker"))
compile_run = pytest.importorskip("compile_run")


class _Blob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upload_blob(self, f, overwrite=True, content_settings=None):
        self.store[self.name] = f.read() if hasattr(f, "read") else f

    def download_blob(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in self.store:
            raise ResourceNotFoundError("missing")
        data = self.store[self.name]

        class _D:
            def readall(self_inner):
                return data

            def readinto(self_inner, fh):
                fh.write(data)
        return _D()

    def delete_blob(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self.name not in self.store:
            raise ResourceNotFoundError("missing")
        del self.store[self.name]


class _Client:
    def __init__(self):
        self.store = {}

    def get_blob_client(self, container, name):
        return _Blob(self.store, name)


def _setup(monkeypatch, run):
    client = _Client()
    client.store["deals/D1/orbitbrief/latest/envelope.json"] = b"{}"
    client.store["deals/D1/orbitbrief/latest/PM_HANDOFF.json"] = b'{"status": "old"}'
    monkeypatch.setattr(compile_run, "_blob_client", lambda: client)
    monkeypatch.setattr(compile_run, "_run_compile", run)
    return client


def test_failed_brief_records_failure_and_marks_latest(monkeypatch):
    def run(env, out, fb=None):
        (out / "pipeline_log.json").write_text("[]")
        (out / "brief_failed.json").write_text(json.dumps({"brief_failed": True, "error": "IndexError"}))
        raise RuntimeError("compile_brief.py exited 3")

    client = _setup(monkeypatch, run)
    with pytest.raises(RuntimeError):
        compile_run.compile_orbitbrief_run("D1", "R1")
    latest = {k for k in client.store if "/latest/" in k}
    assert "deals/D1/orbitbrief/latest/brief_failed.json" in latest
    assert "deals/D1/orbitbrief/latest/pipeline_log.json" not in latest   # no new log beside the old brief
    assert "deals/D1/orbitbrief/R1/brief_failed.json" in client.store


def test_no_handoff_is_a_failure_even_on_exit_zero(monkeypatch):
    client = _setup(monkeypatch, lambda env, out, fb=None: None)
    with pytest.raises(RuntimeError, match="no PM_HANDOFF"):
        compile_run.compile_orbitbrief_run("D1", "R2")
    assert json.loads(client.store["deals/D1/orbitbrief/latest/brief_failed.json"])["brief_failed"]


def test_success_clears_the_failure_marker(monkeypatch):
    def run(env, out, fb=None):
        (out / "PM_HANDOFF.json").write_text(json.dumps({"status": "green", "compile_id": "c"}))

    client = _setup(monkeypatch, run)
    client.store["deals/D1/orbitbrief/latest/brief_failed.json"] = b"{}"
    out = compile_run.compile_orbitbrief_run("D1", "R3")
    assert out["ok"] and "deals/D1/orbitbrief/latest/brief_failed.json" not in client.store


def test_feedback_path_goes_to_the_subprocess_only(monkeypatch, tmp_path):
    seen = {}

    class _P:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, cwd, env, **k):
        seen["fb"] = env.get("ORBITBRIEF_QUESTION_FEEDBACK_PATH")
        return _P()

    monkeypatch.setenv("ORBITBRIEF_CORE_ROOT", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("ORBITBRIEF_QUESTION_FEEDBACK_PATH", "/tmp/other-deal.jsonl")
    monkeypatch.setattr(compile_run.subprocess, "run", fake_run)
    compile_run._run_compile(tmp_path / "e.json", tmp_path, None)
    assert seen["fb"] is None          # another deal's leftover path is not inherited
    compile_run._run_compile(tmp_path / "e.json", tmp_path, tmp_path / "fb.jsonl")
    assert seen["fb"] == str(tmp_path / "fb.jsonl")
    assert os.environ["ORBITBRIEF_QUESTION_FEEDBACK_PATH"] == "/tmp/other-deal.jsonl"


def test_same_deal_compiling_gets_409(monkeypatch):
    import importlib.util
    import types

    # db.py needs psycopg + a database; the lock never touches it.
    monkeypatch.setitem(sys.modules, "db", types.SimpleNamespace(
        mark_run_done=lambda *a, **k: None, mark_run_failed=lambda *a, **k: None))
    spec = importlib.util.spec_from_file_location(
        "core_worker_app", Path(__file__).resolve().parents[1] / "orbitbrief-core-worker" / "app.py")
    app_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_mod)
    from fastapi.testclient import TestClient

    monkeypatch.delenv("ORBITBRIEF_CORE_WORKER_BEARER", raising=False)
    monkeypatch.setattr(app_mod, "_execute_compile", lambda d, r, m: {"ok": True})
    c = TestClient(app_mod.app)
    assert app_mod._claim("DEAL-0001")
    try:
        r = c.post("/v1/compile-run", json={"deal_id": "DEAL-0001", "run_id": "RUN-0001"})
        assert r.status_code == 409
    finally:
        app_mod._release("DEAL-0001")
    assert c.post("/v1/compile-run", json={"deal_id": "DEAL-0001", "run_id": "RUN-0002"}).status_code == 200
    assert c.post("/v1/compile-run", json={"deal_id": "DEAL-0001", "run_id": "RUN-0003"}).status_code == 200
