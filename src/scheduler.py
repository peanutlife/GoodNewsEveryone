"""In-process daily pipeline scheduler.

Runs inside the web service so no separate cron job is required. Once an hour it
checks whether every edition has been published for today (UTC); after
PEANUT_PIPELINE_HOUR it fetches, enriches and builds whatever is missing.

With several gunicorn workers each process starts this thread, so on Postgres a
session-level advisory lock makes sure only one of them actually runs.

Disable with PEANUT_SCHEDULER=0 (for example when a Render cron job runs
`python -m src.pipeline run` instead).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime

logger = logging.getLogger("peanut.scheduler")

LOCK_KEY = 7_430_921  # arbitrary constant for pg_try_advisory_lock
CHECK_EVERY = int(os.environ.get("PEANUT_SCHEDULER_INTERVAL", "3600"))
RUN_AFTER_HOUR = int(os.environ.get("PEANUT_PIPELINE_HOUR", "5"))  # UTC


def _missing_editions(today: date) -> list[str]:
    from src.edition import EDITIONS
    from src.models.article import Edition

    have = {e.edition for e in Edition.query.filter_by(day=today, status="published").all()}
    return [e for e in EDITIONS if e not in have]


def _run_once(app) -> None:
    from src.models.user import db
    from src.pipeline import run
    from src.enrich import has_api_key

    with app.app_context():
        today = datetime.utcnow().date()
        missing = _missing_editions(today)
        if not missing:
            return
        if datetime.utcnow().hour < RUN_AFTER_HOUR and _missing_editions(date.fromordinal(today.toordinal() - 1)) == []:
            return  # yesterday's edition is still fresh enough until the morning build

        conn = db.engine.raw_connection()
        locked = True
        try:
            if db.engine.dialect.name == "postgresql":
                cur = conn.cursor()
                cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
                locked = bool(cur.fetchone()[0])
            if not locked:
                logger.info("Another worker holds the pipeline lock; skipping")
                return
            logger.info("Building editions %s for %s (%s)", missing, today, "Claude" if has_api_key() else "dry run")
            run(dry_run=not has_api_key())
        except Exception as e:  # noqa: BLE001
            logger.exception("Scheduled pipeline run failed")
            from src.pipeline import PROGRESS
            import traceback
            PROGRESS.update(stage="failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}",
                            finished=datetime.utcnow().isoformat(timespec="seconds"))
        finally:
            try:
                if locked and db.engine.dialect.name == "postgresql":
                    cur = conn.cursor()
                    cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            finally:
                conn.close()


def start(app, initial_delay: int = 30) -> threading.Thread | None:
    if os.environ.get("PEANUT_SCHEDULER", "1") != "1" or app.config.get("TESTING"):
        return None

    def loop():
        time.sleep(initial_delay)
        while True:
            _run_once(app)
            time.sleep(CHECK_EVERY)

    t = threading.Thread(target=loop, name="peanut-scheduler", daemon=True)
    t.start()
    logger.info("Pipeline scheduler started (checks every %ss, builds after %02d:00 UTC)", CHECK_EVERY, RUN_AFTER_HOUR)
    return t
