"""Build the daily lists: ten stories per edition, section lists, mood orders, editor's letter."""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta

from src.edition import EDITIONS, edition_name, edition_regions
from src.enrich import write_edition_copy
from src.models.article import SECTIONS, Article, Edition
from src.models.user import db

logger = logging.getLogger(__name__)

TEN = 10
MAX_PER_SOURCE = 2
MAX_PER_SECTION = 3
MIN_SCORE = 6.0
FRESH_HOURS = 48
SECTION_DAYS = 7
SECTION_SIZE = 8


def _candidates(edition: str, since: datetime, min_score: float = MIN_SCORE) -> list[Article]:
    regions = edition_regions(edition)
    q = (Article.query.filter(Article.is_good_news.is_(True), Article.score >= min_score,
                              Article.published >= since))
    if edition != "global":
        q = q.filter(db.or_(Article.source_region.in_(regions), Article.story_region.in_(regions)))
    return q.order_by(Article.score.desc(), Article.published.desc()).limit(400).all()


def _regional_boost(a: Article, edition: str) -> float:
    """Local stories rank a little higher in a regional edition."""
    if edition == "global":
        return 0.0
    regions = edition_regions(edition)
    home = regions[0]
    boost = 0.0
    if a.story_region == home:
        boost += 1.0
    if a.source_region == home:
        boost += 0.5
    if a.source_quality == "high":
        boost += 0.3
    if a.source_quality == "low":
        boost -= 1.0
    return boost


def pick_ten(cands: list[Article], edition: str) -> list[Article]:
    ranked = sorted(cands, key=lambda a: (a.score or 0) + _regional_boost(a, edition), reverse=True)
    by_source, by_section, picks = Counter(), Counter(), []
    for a in ranked:
        if by_source[a.source_name] >= MAX_PER_SOURCE or by_section[a.section] >= MAX_PER_SECTION:
            continue
        picks.append(a)
        by_source[a.source_name] += 1
        by_section[a.section] += 1
        if len(picks) == TEN:
            break
    if len(picks) < TEN:  # relax the diversity caps rather than publish a short list
        for a in ranked:
            if a not in picks:
                picks.append(a)
            if len(picks) == TEN:
                break
    return picks


def section_lists(edition: str, since: datetime) -> dict[str, list[Article]]:
    out = {}
    cands = _candidates(edition, since, min_score=5.0)
    for key in SECTIONS:
        rows = [a for a in cands if a.section == key]
        if key == "kids":
            rows = [a for a in cands if a.kid_safe]
        rows.sort(key=lambda a: ((a.score or 0) + _regional_boost(a, edition), a.published), reverse=True)
        seen_src, picked = Counter(), []
        for a in rows:
            if seen_src[a.source_name] >= 3:
                continue
            seen_src[a.source_name] += 1
            picked.append(a)
            if len(picked) == SECTION_SIZE:
                break
        out[key] = picked
    return out


CALM_SECTIONS = {"nature": 0, "kindness": 0, "culture": 1, "science": 1, "kids": 1, "progress": 2, "politics": 3, "sports": 3}
LIFT_SECTIONS = {"sports": 0, "kindness": 0, "progress": 0, "science": 1, "politics": 1, "nature": 2, "culture": 2, "kids": 2}


def mood_sort(picks: list[Article], mood: str) -> list[Article]:
    """Reorder the ten for a mood. Surprise = the editor's order. Never adds or drops a story."""
    def tone(a):
        return (a.enrichment or {}).get("tone", "neutral")
    tone_rank = {"calm": 0, "neutral": 1, "lift": 2}
    if mood == "calm":
        return sorted(picks, key=lambda a: (tone_rank[tone(a)], CALM_SECTIONS.get(a.section, 2), -(a.read_minutes or 3), -(a.score or 0)))
    if mood == "lift":
        return sorted(picks, key=lambda a: (-tone_rank[tone(a)], LIFT_SECTIONS.get(a.section, 2), (a.read_minutes or 3), -(a.score or 0)))
    return list(picks)


def mood_orders(picks: list[Article]) -> dict[str, list[str]]:
    return {m: [a.id for a in mood_sort(picks, m)] for m in ("calm", "lift", "surprise")}


def build_edition(edition: str, day: date | None = None, dry_run: bool = False) -> Edition:
    day = day or datetime.utcnow().date()
    now = datetime.utcnow()
    picks = pick_ten(_candidates(edition, now - timedelta(hours=FRESH_HOURS)), edition)
    if len(picks) < 3:  # thin day: widen the window rather than publish nothing
        picks = pick_ten(_candidates(edition, now - timedelta(days=SECTION_DAYS)), edition)
    sections = section_lists(edition, now - timedelta(days=SECTION_DAYS))

    copy = write_edition_copy(
        edition_name(edition),
        [a.as_card() for a in picks],
        {k: [a.as_card() for a in v] for k, v in sections.items()},
        now, dry_run=dry_run,
    )
    row = Edition.query.filter_by(day=day, edition=edition).first() or Edition(day=day, edition=edition)
    row.built_at = now
    row.status = "published"
    row.letter_title = copy.get("letter_title", "")
    row.letter = copy.get("letter", "")
    row.standfirsts = dict(copy.get("standfirsts", {}) or {})
    if copy.get("_meta"):
        row.standfirsts["_meta"] = copy["_meta"]
    row.picks = [a.id for a in picks]
    row.section_picks = {k: [a.id for a in v] for k, v in sections.items()}
    row.mood_orders = mood_orders(picks)
    db.session.add(row)
    db.session.commit()
    return row


def build_all_editions(dry_run: bool = False) -> list[Edition]:
    return [build_edition(e, dry_run=dry_run) for e in EDITIONS]


def latest_edition(edition: str) -> Edition | None:
    return (Edition.query.filter_by(edition=edition, status="published")
            .order_by(Edition.day.desc()).first())


def previous_edition(edition: str, before: date) -> Edition | None:
    return (Edition.query.filter(Edition.edition == edition, Edition.status == "published", Edition.day < before)
            .order_by(Edition.day.desc()).first())


def articles_by_ids(ids: list[str]) -> list[Article]:
    if not ids:
        return []
    rows = {a.id: a for a in Article.query.filter(Article.id.in_(ids)).all()}
    return [rows[i] for i in ids if i in rows]
