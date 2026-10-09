"""Storage tests: project files, cleanup rules, deletion authorization."""
from __future__ import annotations

import json

from studio.pipeline import storage as ST


def test_write_and_read_project_files(studio_env, tmp_path):
    pdir = ST.write_project_files(
        studio_env, "proj_test1",
        request={"topic": "t"}, script={"hook": "h"}, research={"status": "ok"},
        assets={"clips": []}, qc={"passed": True}, logs="line1\nline2",
        output_path="/x/final.mp4", attribution=[{"source": "x"}],
    )
    assert (pdir / "project.json").exists()
    assert (pdir / "script.json").exists()
    assert (pdir / "qc_report.json").exists()
    assert "line2" in (pdir / "production.log").read_text()
    usage = ST.storage_usage(studio_env)
    assert usage["used_bytes"] >= 0
    assert usage["limit_exceeded"] is False


def test_delete_requires_confirmation(studio_env, db):
    ST.write_project_files(studio_env, "proj_del", request={}, script=None, research=None,
                           assets=None, qc=None, logs="", output_path=None, attribution=[])
    db.upsert_project("proj_del", title="t", topic="t", status="COMPLETED")
    res = ST.delete_project(studio_env, "proj_del", db, confirm=False)
    assert res["deleted"] is False
    assert (studio_env.projects_dir / "proj_del").exists()
    res2 = ST.delete_project(studio_env, "proj_del", db, confirm=True)
    assert res2["deleted"] is True
    assert not (studio_env.projects_dir / "proj_del").exists()
    assert db.get_project("proj_del") is None  # soft-deleted


def test_delete_rejects_traversal_id(studio_env, db):
    res = ST.delete_project(studio_env, "../../etc", db, confirm=True)
    assert res["deleted"] is False


def test_retention_cleanup(studio_env, db, monkeypatch):
    monkeypatch.setattr(studio_env, "retention_days", 1)
    db.upsert_project("proj_old", title="old", topic="old", status="COMPLETED")
    db.execute("UPDATE projects SET created_at = ? WHERE id = ?",
               ("2020-01-01T00:00:00+00:00", "proj_old"))
    db.upsert_project("proj_new", title="new", topic="new", status="COMPLETED")
    res = ST.cleanup_expired(studio_env, db)
    assert "proj_old" in res["deleted"]
    assert "proj_new" not in res.get("deleted", [])
    # disabled retention deletes nothing
    monkeypatch.setattr(studio_env, "retention_days", 0)
    res2 = ST.cleanup_expired(studio_env, db)
    assert res2["deleted"] == []
    assert "retention disabled" in res2["note"]
