"""
api/jobs.py — Endpoints REST per il sistema jobs.

  GET  /api/jobs                    — lista jobs recenti
  GET  /api/jobs/<job_id>           — dettaglio singolo job
  POST /api/jobs/<job_id>/cancel    — richiesta cancellazione
"""

from flask import Blueprint, jsonify

from core.jobs import get_job, list_jobs, cancel_job
from core.utils import log
from core.event_log import log_event

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.route("/jobs", methods=["GET"])
def api_jobs_list():
    """Restituisce la lista dei job recenti (ultimi 24h)."""
    return jsonify({"jobs": list_jobs()})


@jobs_bp.route("/jobs/<job_id>", methods=["GET"])
def api_job_get(job_id):
    """Restituisce il dettaglio di un job specifico."""
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Job non trovato"}), 404
    return jsonify(job)


@jobs_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id):
    """Richiede la cancellazione di un job in esecuzione."""
    job = cancel_job(job_id)
    if job is None:
        return jsonify({"error": "Job non trovato"}), 404
    log(f"Cancellazione richiesta via API per job {job_id}", "info")
    log_event("jobs", "warning", f"Job {job_id} cancellato", {"job_id": job_id})
    return jsonify({"status": "ok", "job": job})
