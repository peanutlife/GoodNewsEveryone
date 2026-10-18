"""In-process daily pipeline scheduler.

Runs inside the web service so no separate cron job is required. Once an hour it
checks whether every edition has been published for today (UTC); after
PEANUT_PIPELINE_HOUR it fetches, triages, enriches and builds whatever is missing.

With several gunicorn workers each process starts this thread, so on Postgres a
session-level advisory lock (held on a dedicated connection for the whole run)
makes sure only one of them actually runs.

Disable with PEANUT_SCHEDULER=0 (for example when a Render cron job runs
`python -m src.pipeline run` instead).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger("peanut.scheduler")

LOCK_KEY = 7_430_921  # arbitrary constant for pg_try_advisory_lock
CHECK_EVERY = int(os.environ.get("PEANUT_SCHEDULER_INTERVAL", "3600"))
RUN_AFTER_HOUR = int(os.environ.get("PEANUT_PIPELINE_HOUR", "5"))  # UTC

STATE = {"enabled": False, "thread_alive": False, "started_at": None, "last_check": None,
         "next_check": None, "checks": 0, "runs": 0, "last_decision": None, "last_error": None}
_run_lock = threading.Lock()


def _missing_editions(today: date) -> list[str]:
    from src.edition import EDITIONS
    from src.models.article import Edition

    have = {e.edition for e in Edition.query.filter_by(day=today, status="published").all()}
    return [e for e in EDITIONS if e not in have]


def _run_once(app, force: bool = False) -> str:
    """Decide whether to build, and build. Returns a short reason string for the status page."""
    from src.models.user import db
    from src.pipeline import run, PROGRESS
    from src.enrich import has_api_key

    if not _run_lock.acquire(blocking=False):
        return "a run is already in progress in this process"
    try:
        with app.app_context():
            today = datetime.utcnow().date()
            missing = _missing_editions(today)
            if not missing and not force:
                return f"all editions published for {today}"
            if (not force and datetime.utcnow().hour < RUN_AFTER_HOUR
                    and not _missing_editions(today - timedelta(days=1))):
                return f"before {RUN_AFTER_HOUR:02d}:00 UTC and yesterday's editions exist; waiting"

            lock_conn = None
            got = True
            try:
                if db.engine.dialect.name == "postgresql":
                    lock_conn = db.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
                    got = bool(lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
                if not got:
                    return "another worker holds the pipeline lock"
                STATE["runs"] += 1
                logger.info("Building editions %s for %s (%s)", missing or "forced", today,
                            "Claude" if has_api_key() else "dry run")
                run(dry_run=not has_api_key())
                return f"built {missing or 'all'} for {today}"
            except Exception as e:  # noqa: BLE001
                logger.exception("Scheduled pipeline run failed")
                PROGRESS.update(stage="failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}",
                                finished=datetime.utcnow().isoformat(timespec="seconds"))
                return f"failed: {type(e).__name__}: {e}"[:300]
            finally:
                if lock_conn is not None:
                    try:
                        if got:
                            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                    finally:
                        lock_conn.close()
    finally:
        _run_lock.release()


def trigger(app) -> threading.Thread:
    """Start a forced run in the background (used by POST /_pipeline/run)."""
    t = threading.Thread(target=lambda: STATE.update(last_decision=_run_once(app, force=True)),
                         name="peanut-manual-run", daemon=True)
    t.start()
    return t


def start(app, initial_delay: int = 30) -> threading.Thread | None:
    if os.environ.get("PEANUT_SCHEDULER", "1") != "1" or app.config.get("TESTING"):
        return None

    def loop():
        time.sleep(initial_delay)
        while True:
            STATE["last_check"] = datetime.utcnow().isoformat(timespec="seconds")
            STATE["checks"] += 1
            try:
                STATE["last_decision"] = _run_once(app)
            except Exception as e:  # noqa: BLE001 - keep the thread alive no matter what
                logger.exception("Scheduler check failed")
                STATE["last_error"] = f"{datetime.utcnow().isoformat(timespec='seconds')} {type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}"
            STATE["next_check"] = (datetime.utcnow() + timedelta(seconds=CHECK_EVERY)).isoformat(timespec="seconds")
            time.sleep(CHECK_EVERY)

    t = threading.Thread(target=loop, name="peanut-scheduler", daemon=True)
    t.start()
    STATE.update(enabled=True, thread_alive=True, started_at=datetime.utcnow().isoformat(timespec="seconds"))
    logger.info("Pipeline scheduler started (checks every %ss, builds after %02d:00 UTC)", CHECK_EVERY, RUN_AFTER_HOUR)
    return t
