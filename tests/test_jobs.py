"""
tests/test_jobs.py — Test per core/jobs.py e api/jobs.py

Copre:
- create_job
- update_job
- finish_job
- cancel_job
- get_job / list_jobs
- cleanup_old_jobs
- API endpoints (smoke test via Flask test client)
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_jobs_state():
    """Svuota jobs_state prima e dopo ogni test."""
    from core.state import jobs_state
    jobs_state.clear()
    yield
    jobs_state.clear()


@pytest.fixture()
def app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.jobs import jobs_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(jobs_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ─── test core/jobs.py ───────────────────────────────────────────────────────

def test_create_job_returns_dict():
    from core.jobs import create_job
    job = create_job("ota", "Test OTA job")
    assert isinstance(job, dict)
    assert job["type"] == "ota"
    assert job["status"] == "pending"
    assert "job_id" in job


def test_create_job_has_all_required_fields():
    from core.jobs import create_job
    job = create_job("file_copy", "Copy test", bytes_total=1024, items_total=5)
    required = [
        "job_id", "type", "status", "description",
        "progress_percent", "bytes_total", "bytes_done",
        "items_total", "items_done", "current_item",
        "message", "error", "cancel_requested",
        "created_ts", "updated_ts", "finished_ts",
    ]
    for field in required:
        assert field in job, f"Manca il campo: {field}"


def test_create_job_stores_in_jobs_state():
    from core.jobs import create_job
    from core.state import jobs_state
    job = create_job("test", "")
    assert job["job_id"] in jobs_state


def test_update_job_modifies_fields():
    from core.jobs import create_job, update_job
    job = create_job("test", "")
    job_id = job["job_id"]
    updated = update_job(job_id, status="running", progress_percent=50)
    assert updated["status"] == "running"
    assert updated["progress_percent"] == 50


def test_update_job_sets_updated_ts():
    from core.jobs import create_job, update_job
    job = create_job("test", "")
    old_ts = job["updated_ts"]
    time.sleep(0.01)
    updated = update_job(job["job_id"], message="hello")
    assert updated["updated_ts"] >= old_ts


def test_update_job_missing_id_returns_none():
    from core.jobs import update_job
    result = update_job("nonexistent-id", status="running")
    assert result is None


def test_finish_job_sets_done():
    from core.jobs import create_job, finish_job
    job = create_job("test", "")
    finished = finish_job(job["job_id"])
    assert finished["status"] == "done"
    assert finished["finished_ts"] is not None
    assert finished["progress_percent"] == 100


def test_finish_job_with_error():
    from core.jobs import create_job, finish_job
    job = create_job("test", "")
    finished = finish_job(job["job_id"], status="error", error="Something went wrong")
    assert finished["status"] == "error"
    assert finished["error"] == "Something went wrong"


def test_cancel_job_pending_sets_canceled():
    from core.jobs import create_job, cancel_job
    job = create_job("test", "")
    assert job["status"] == "pending"
    canceled = cancel_job(job["job_id"])
    assert canceled["status"] == "canceled"
    assert canceled["finished_ts"] is not None


def test_cancel_job_running_sets_cancel_requested():
    from core.jobs import create_job, update_job, cancel_job
    job = create_job("test", "")
    update_job(job["job_id"], status="running")
    canceled = cancel_job(job["job_id"])
    assert canceled["cancel_requested"] is True


def test_cancel_job_missing_returns_none():
    from core.jobs import cancel_job
    result = cancel_job("nonexistent")
    assert result is None


def test_get_job_returns_job():
    from core.jobs import create_job, get_job
    job = create_job("test", "")
    fetched = get_job(job["job_id"])
    assert fetched is not None
    assert fetched["job_id"] == job["job_id"]


def test_get_job_missing_returns_none():
    from core.jobs import get_job
    assert get_job("nonexistent") is None


def test_list_jobs_returns_list():
    from core.jobs import create_job, list_jobs
    create_job("a", "")
    create_job("b", "")
    jobs = list_jobs()
    assert isinstance(jobs, list)
    assert len(jobs) == 2


def test_list_jobs_excludes_old_finished():
    from core.jobs import create_job, finish_job, list_jobs
    from core.state import jobs_state
    job = create_job("test", "")
    finish_job(job["job_id"])
    # Simula un job molto vecchio
    jobs_state[job["job_id"]]["finished_ts"] = int(time.time()) - 90000
    jobs = list_jobs()
    assert len(jobs) == 0


def test_list_jobs_includes_old_if_flag():
    from core.jobs import create_job, finish_job, list_jobs
    from core.state import jobs_state
    job = create_job("test", "")
    finish_job(job["job_id"])
    jobs_state[job["job_id"]]["finished_ts"] = int(time.time()) - 90000
    jobs = list_jobs(include_old=True)
    assert len(jobs) == 1


def test_cleanup_removes_old_jobs():
    from core.jobs import create_job, finish_job, cleanup_old_jobs
    from core.state import jobs_state
    job = create_job("test", "")
    finish_job(job["job_id"])
    jobs_state[job["job_id"]]["finished_ts"] = int(time.time()) - 90000
    removed = cleanup_old_jobs()
    assert removed == 1
    assert job["job_id"] not in jobs_state


def test_cleanup_keeps_recent_jobs():
    from core.jobs import create_job, finish_job, cleanup_old_jobs
    job = create_job("test", "")
    finish_job(job["job_id"])
    removed = cleanup_old_jobs()
    assert removed == 0


# ─── test api/jobs.py endpoints ──────────────────────────────────────────────

def test_api_jobs_list_empty(client):
    rv = client.get("/api/jobs")
    assert rv.status_code == 200
    data = rv.get_json()
    assert "jobs" in data
    assert isinstance(data["jobs"], list)


def test_api_jobs_list_returns_jobs(client):
    from core.jobs import create_job
    create_job("ota", "Test")
    rv = client.get("/api/jobs")
    assert rv.status_code == 200
    assert len(rv.get_json()["jobs"]) == 1


def test_api_job_get_existing(client):
    from core.jobs import create_job
    job = create_job("ota", "Test")
    rv = client.get(f"/api/jobs/{job['job_id']}")
    assert rv.status_code == 200
    assert rv.get_json()["job_id"] == job["job_id"]


def test_api_job_get_missing(client):
    rv = client.get("/api/jobs/nonexistent-id")
    assert rv.status_code == 404


def test_api_job_cancel(client):
    from core.jobs import create_job, update_job
    job = create_job("test", "")
    update_job(job["job_id"], status="running")
    rv = client.post(f"/api/jobs/{job['job_id']}/cancel")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["status"] == "ok"
    assert data["job"]["cancel_requested"] is True


def test_api_job_cancel_missing(client):
    rv = client.post("/api/jobs/nonexistent-id/cancel")
    assert rv.status_code == 404
