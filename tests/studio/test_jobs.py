"""Job manager tests: creation, transitions, dedupe, retry, cancellation."""
from __future__ import annotations

import time

from studio.db import utcnow


def test_job_creation(jobs, sample_request):
    res = jobs.create_job(sample_request)
    assert res["deduplicated"] is False
    job = jobs.get_job(res["job"]["id"])
    assert job["status"] == "QUEUED"
    assert job["stage"] == "QUEUED"
    assert job["progress"] == 0
    assert job["project_id"].startswith("proj_")
    assert job["request"]["topic"] == sample_request["topic"]
    logs = jobs.get_logs(job["id"])
    assert any("created" in l["message"].lower() for l in logs)


def test_duplicate_submission_dedupes(jobs, sample_request):
    a = jobs.create_job(sample_request)
    b = jobs.create_job(dict(sample_request))
    assert b["deduplicated"] is True
    assert a["job"]["id"] == b["job"]["id"]


def test_different_requests_not_deduped(jobs, sample_request):
    a = jobs.create_job(sample_request)
    other = dict(sample_request, topic="A totally different topic here")
    b = jobs.create_job(other)
    assert b["deduplicated"] is False
    assert a["job"]["id"] != b["job"]["id"]


def test_stage_transitions(jobs, sample_request):
    job_id = jobs.create_job(sample_request)["job"]["id"]
    jobs.set_stage(job_id, "RESEARCHING", "starting research")
    job = jobs.get_job(job_id)
    assert job["stage"] == "RESEARCHING"
    assert job["status"] == "RUNNING"
    assert job["progress"] == 5
    jobs.set_stage(job_id, "SCRIPTING")
    assert jobs.get_job(job_id)["progress"] == 20


def test_claim_next_queued(db, jobs, sample_request):
    job_id = jobs.create_job(sample_request)["job"]["id"]
    claimed = db.claim_next_queued()
    assert claimed is not None and claimed["id"] == job_id
    assert claimed["status"] == "RUNNING"
    # No double-claim
    assert db.claim_next_queued() is None


def test_complete_and_fail(jobs, sample_request):
    job_id = jobs.create_job(sample_request)["job"]["id"]
    project_id = jobs.get_job(job_id)["project_id"]
    jobs.complete(job_id, project_id=project_id, output_path="/tmp/x.mp4", qc={"passed": True})
    job = jobs.get_job(job_id)
    assert job["status"] == "COMPLETED"
    assert job["progress"] == 100
    assert job["output_path"] == "/tmp/x.mp4"

    job2 = jobs.create_job(dict(sample_request, topic="second topic for failure case"))["job"]["id"]
    jobs.fail(job2, error="boom", stage="RENDERING")
    job2r = jobs.get_job(job2)
    assert job2r["status"] == "FAILED"
    assert job2r["error"] == "boom"
    assert job2r["error_stage"] == "RENDERING"


def test_retry_behavior(jobs, sample_request):
    job_id = jobs.create_job(sample_request)["job"]["id"]
    # retry on non-failed job is rejected
    assert jobs.retry(job_id)["ok"] is False
    jobs.fail(job_id, error="x", stage="SCRIPTING")
    res = jobs.retry(job_id)
    assert res["ok"] is True
    job = jobs.get_job(job_id)
    assert job["status"] == "QUEUED"
    assert job["retry_count"] == 1
    assert job["error"] is None
    # exhaust retries
    jobs.fail(job_id, error="x", stage="SCRIPTING")
    assert jobs.retry(job_id)["ok"] is True
    jobs.fail(job_id, error="x", stage="SCRIPTING")
    res3 = jobs.retry(job_id)
    assert res3["ok"] is False
    assert "retry limit" in res3["error"]


def test_cancel_queued_and_running(jobs, sample_request):
    job_id = jobs.create_job(sample_request)["job"]["id"]
    res = jobs.request_cancel(job_id)
    assert res["cancelled"] is True
    job = jobs.get_job(job_id)
    assert job["status"] == "CANCELLED"

    job2 = jobs.create_job(dict(sample_request, topic="another distinct topic to cancel"))["job"]["id"]
    jobs.set_stage(job2, "RENDERING")
    res2 = jobs.request_cancel(job2)
    assert res2["cancelled"] is True
    assert jobs.is_cancel_requested(job2) is True
    job2r = jobs.get_job(job2)
    assert job2r["status"] == "RUNNING"  # stops at next safe point
    # cancelling terminal job is rejected
    jobs.db.update_job(job2, status="CANCELLED")
    assert jobs.request_cancel(job2)["cancelled"] is False


def test_job_listing_and_logs(jobs, sample_request):
    job_id = jobs.create_job(sample_request)["job"]["id"]
    jobs.log(job_id, "hello world", level="WARN", stage="SCRIPTING")
    rows = jobs.list_jobs(limit=10)
    assert any(r["id"] == job_id for r in rows)
    logs = jobs.get_logs(job_id)
    assert any(l["message"] == "hello world" and l["level"] == "WARN" for l in logs)
