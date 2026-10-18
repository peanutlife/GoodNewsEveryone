"""Daily pipeline: fetch sources -> pre-filter -> Claude enrichment -> store -> build editions.

Run:  python -m src.pipeline run [--dry-run] [--limit N] [--editions-only]
"""
from __future__ import annotations

import argparse
import logging
import os
import html
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import feedparser
import requests

from src.edition import config as sources_config
from src.enrich import article_id, enrich_many, slugify, triage_many
from src.models.article import Article, log_event
from src.models.user import db

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; PeanutlifeBot/2.0; +https://peanutlife.com)"
BATCH = 25  # commit after every 25 enrichments
ENRICH_LIMIT = int(os.environ.get("PEANUT_ENRICH_LIMIT", "150"))  # full reads per run, after triage
TRIAGE_COMMIT = 200  # commit triage results every N articles
SKIP_PENDING_AFTER_DAYS = 2  # backlog older than this is marked skipped instead of enriched later
PROGRESS = {"stage": "idle", "done": 0, "total": 0, "started": None, "finished": None, "error": None}
MAX_AGE_DAYS = 7  # slow weekly feeds (Guardian Upside, UN, Our World in Data) still land; the ten uses FRESH_HOURS

# Cheap pre-filter so Claude never sees obvious non-candidates. Anything that passes is judged by
# Claude; this list only removes what could never be good news or is clearly not news.
HARD_EXCLUDE = re.compile(
    r"\b(dies|died|dead|death toll|killed|kills|murder|shooting|shooter|gunman|massacre|stabbing|rape|suicide|crash kills|bomb|"
    r"airstrike|missile|hostage|war crimes|genocide|famine|wildfire|hurricane|flood kills|review:|best \w+ (of|for) 20\d\d|"
    r"deals? (on|of the day)|black friday|prime day|coupon|horoscope|how to watch|live updates|"
    r"stock market|dow jones|nasdaq|s&p 500|earnings|ipo|crypto|bitcoin|"
    r"trump|biden|putin|netanyahu|musk|kardashian)\b",
    re.I,
)


def _parse_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None)
        if val:
            try:
                return datetime.fromtimestamp(time.mktime(val))
            except (OverflowError, ValueError):
                pass
    return None


def _image_from_entry(entry) -> str | None:
    best, best_w = None, -1
    for media in getattr(entry, "media_content", []) or []:
        url = media.get("url")
        if not url:
            continue
        try:
            w = int(media.get("width") or 0)
        except ValueError:
            w = 0
        if w > best_w:
            best, best_w = url, w
    if best:
        return best
    thumbs = getattr(entry, "media_thumbnail", None)
    if thumbs and thumbs[0].get("url"):
        return thumbs[0]["url"]
    for enc in getattr(entry, "enclosures", []) or []:
        if str(enc.get("type", "")).startswith("image/") and enc.get("href"):
            return enc["href"]
    html = ""
    content = getattr(entry, "content", None)
    if content:
        html = content[0].get("value", "")
    html += " " + entry.get("summary", "")
    for img in re.findall(r'<img[^>]+src="([^"]+)"', html):
        low = img.lower()
        if any(x in low for x in ("1x1", "pixel", "track", "icon", "badge", "gravatar", ".gif")):
            continue
        return img
    return None


def fetch_source(source: dict, session: requests.Session) -> list[dict]:
    try:
        resp = session.get(source["url"], timeout=20, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Fetch failed %s: %s", source["url"], e)
        return []
    feed = feedparser.parse(resp.content)
    out = []
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = _parse_date(entry) or datetime.utcnow()
        if published < cutoff:
            continue
        summary = entry.get("summary") or entry.get("description") or ""
        summary = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", summary))).strip()[:4000]
        out.append({
            "id": article_id(link),
            "link": link,
            "title": title,
            "summary": summary,
            "published": published,
            "image_url": _image_from_entry(entry),
            "source_name": source["name"],
            "source_url": source["url"],
            "source_region": source.get("region", "global"),
            "source_quality": source.get("quality", "standard"),
        })
    return out


def fetch_all(limit_sources: int | None = None) -> list[dict]:
    sources = sources_config()["sources"]
    if limit_sources:
        sources = sources[:limit_sources]
    session = requests.Session()
    items: list[dict] = []
    for i, s in enumerate(sources, 1):
        got = fetch_source(s, session)
        logger.info("[%d/%d] %s: %d entries", i, len(sources), s["name"], len(got))
        items.extend(got)
    # De-duplicate by id, keeping the first (sources are ordered best first).
    seen, unique = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        unique.append(it)
    return unique


def prefilter(items: list[dict]) -> list[dict]:
    kept = []
    for it in items:
        text = f"{it['title']} {re.sub('<[^>]+>', ' ', it['summary'])[:400]}"
        if HARD_EXCLUDE.search(text):
            continue
        kept.append(it)
    return kept


def store_new(items: list[dict]) -> list[Article]:
    """Insert unseen items as un-enriched Article rows. Returns the new rows."""
    ids = [it["id"] for it in items]
    existing = set()
    for chunk in range(0, len(ids), 500):
        rows = db.session.query(Article.id).filter(Article.id.in_(ids[chunk:chunk + 500])).all()
        existing.update(r[0] for r in rows)
    new_rows = []
    for it in items:
        if it["id"] in existing:
            continue
        row = Article(
            id=it["id"], link=it["link"], title=it["title"][:500], summary=it["summary"],
            image_url=it["image_url"], source_name=it["source_name"], source_url=it["source_url"],
            source_region=it["source_region"], source_quality=it["source_quality"],
            published=it["published"], slug=slugify(it["title"]),
        )
        db.session.add(row)
        new_rows.append(row)
    db.session.commit()
    return new_rows


QUALITY_RANK = {"high": 0, "standard": 1, "low": 2}


def triage_pending(limit: int = 3000, dry_run: bool = False) -> dict:
    """Stage 1: vet every un-triaged article from its title in batched calls. Cheap.

    'no' rows are closed immediately (enriched_at set, model 'triage-no') so they never
    reach the full read; 'yes'/'maybe' rows wait for enrich_pending.
    """
    pending = (Article.query.filter(Article.triage.is_(None), Article.enriched_at.is_(None))
               .order_by(Article.published.desc()).limit(limit).all())
    counts = {"yes": 0, "maybe": 0, "no": 0, "failed": 0}
    if not pending:
        return counts
    PROGRESS.update(stage="triaging", done=0, total=len(pending))
    for start in range(0, len(pending), TRIAGE_COMMIT):
        chunk = pending[start:start + TRIAGE_COMMIT]
        dicts = [{"title": a.title, "summary": a.summary or "", "source_name": a.source_name,
                  "source_region": a.source_region, "link": a.link} for a in chunk]
        results = triage_many(dicts, dry_run=dry_run)
        now = datetime.utcnow()
        for a, r in zip(chunk, results):
            if r is None:
                counts["failed"] += 1
                continue
            a.triage = r["verdict"]
            a.triage_score = float(r.get("score") or 0)
            a.triaged_at = now
            a.section = a.section or r.get("section")
            a.enrichment = dict(a.enrichment or {})
            a.enrichment["triage_usage"] = r.get("_usage")
            a.enrichment["triage_model"] = r.get("_model")
            if r["verdict"] == "no":
                a.enriched_at = now
                a.enrich_model = "triage-no"
                a.is_good_news = False
                a.score = a.triage_score
            counts[r["verdict"]] += 1
        db.session.commit()
        PROGRESS["done"] = min(start + TRIAGE_COMMIT, len(pending))
        logger.info("Triaged %d/%d", PROGRESS["done"], len(pending))
    return counts


def enrich_pending(limit: int = ENRICH_LIMIT, dry_run: bool = False) -> int:
    """Stage 2: full read of the articles triage said yes to (then maybe, if there is room)."""
    base = Article.query.filter(Article.enriched_at.is_(None))
    pending = base.filter(Article.triage == "yes").order_by(Article.triage_score.desc(), Article.published.desc()).limit(limit).all()
    if len(pending) < limit:
        pending += (base.filter(Article.triage == "maybe").order_by(Article.triage_score.desc(), Article.published.desc())
                    .limit(limit - len(pending)).all())
    pending.sort(key=lambda a: (-(a.triage_score or 0), QUALITY_RANK.get(a.source_quality, 1), -(a.published or datetime.min).timestamp()))
    if not pending:
        return 0
    done = 0
    PROGRESS.update(stage="enriching", done=0, total=len(pending))
    for start in range(0, len(pending), BATCH):
        chunk = pending[start:start + BATCH]
        dicts = [{
            "link": a.link, "title": a.title, "summary": a.summary or "", "published": a.published.isoformat() if a.published else "",
            "source_name": a.source_name, "source_region": a.source_region,
        } for a in chunk]
        results = enrich_many(dicts, dry_run=dry_run)
        done += _apply_enrichment(chunk, results)
        db.session.commit()
        PROGRESS["done"] = min(start + BATCH, len(pending))
        logger.info("Enriched %d/%d", PROGRESS["done"], len(pending))
    # Anything still pending and older than a couple of days will never make the ten; stop carrying it.
    stale = datetime.utcnow() - timedelta(days=SKIP_PENDING_AFTER_DAYS)
    skipped = (Article.query.filter(Article.enriched_at.is_(None), Article.published < stale)
               .update({Article.enriched_at: datetime.utcnow(), Article.enrich_model: "skipped", Article.is_good_news: False},
                       synchronize_session=False))
    db.session.commit()
    if skipped:
        logger.info("Marked %d stale pending articles as skipped", skipped)
    return done


def _apply_enrichment(pending: list[Article], results: list[dict | None]) -> int:
    done = 0
    for a, r in zip(pending, results):
        if r is None:
            continue
        a.enriched_at = datetime.utcnow()
        a.enrich_model = r.get("_model", "")
        a.is_good_news = bool(r["is_good_news"])
        a.confidence = float(r.get("confidence", 0))
        a.score = float(r.get("score", 0))
        a.section = r.get("section", "progress")
        a.story_region = r.get("story_region") or a.source_region
        a.kid_safe = bool(r.get("kid_safe")) and a.section == "kids" or bool(r.get("kid_safe"))
        a.read_minutes = int(r.get("read_minutes") or 3)
        if r.get("headline"):
            a.slug = slugify(r["headline"])
        a.enrichment = {k: v for k, v in r.items() if not k.startswith("_") and k not in
                        ("is_good_news", "confidence", "score", "section", "story_region", "kid_safe", "read_minutes")}
        a.enrichment["tone"] = r.get("tone", "neutral")
        a.enrichment["usage"] = r.get("_usage")
        done += 1
    return done


def run(dry_run: bool = False, limit: int = ENRICH_LIMIT, editions_only: bool = False, limit_sources: int | None = None):
    from src.editions import build_all_editions

    PROGRESS.update(stage="fetching", started=datetime.utcnow().isoformat(timespec="seconds"), finished=None, error=None)
    log_event("stage", f"run started (dry_run={dry_run}, limit={limit})")
    if not editions_only:
        items = fetch_all(limit_sources=limit_sources)
        logger.info("Fetched %d unique entries", len(items))
        items = prefilter(items)
        logger.info("%d pass the pre-filter", len(items))
        new_rows = store_new(items)
        logger.info("%d new articles stored", len(new_rows))
        log_event("stage", f"fetched {len(items)} after pre-filter, {len(new_rows)} new")
        t = triage_pending(dry_run=dry_run)
        logger.info("Triage: %s", t)
        log_event("stage", f"triage {t}")
        n = enrich_pending(limit=limit, dry_run=dry_run)
        log_event("stage", f"enriched {n}")
        logger.info("Enriched %d articles (%s)", n, "dry run" if dry_run else "Claude")
    PROGRESS["stage"] = "building editions"
    built = build_all_editions(dry_run=dry_run)
    PROGRESS.update(stage="idle", finished=datetime.utcnow().isoformat(timespec="seconds"))
    log_event("stage", "run finished: " + ", ".join(f"{b.edition}={len(b.picks or [])}" for b in built))
    for ed in built:
        logger.info("Edition %s/%s: %d picks", ed.day, ed.edition, len(ed.picks or []))


def main():
    parser = argparse.ArgumentParser(description="Peanutlife daily pipeline")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("run")
    p.add_argument("--dry-run", action="store_true", help="No Claude calls; deterministic stand-in enrichment")
    p.add_argument("--limit", type=int, default=400, help="Max articles to enrich this run")
    p.add_argument("--limit-sources", type=int, default=None, help="Only fetch the first N sources (testing)")
    p.add_argument("--editions-only", action="store_true", help="Skip fetch/enrich; rebuild today's editions")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from src.main import create_app

    app = create_app()
    with app.app_context():
        if args.cmd == "run":
            run(dry_run=args.dry_run, limit=args.limit, editions_only=args.editions_only,
                limit_sources=args.limit_sources)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
