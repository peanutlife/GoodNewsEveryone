"""Claude enrichment: judge whether a story is good news and write the Peanutlife layer.

One call per article, structured JSON out, cached in the database so each story is
processed once. Runs in `dry_run` mode without an API key so the rest of the site
can be developed and tested.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import html
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import anthropic

from src.models.article import REGIONS, SECTIONS

logger = logging.getLogger(__name__)

# Bulk per-article pass: cheap and good enough for classification plus short copy.
ENRICH_MODEL = os.environ.get("PEANUT_ENRICH_MODEL", "claude-haiku-5-5")
# Daily letter and standfirsts: small volume, quality matters.
EDITOR_MODEL = os.environ.get("PEANUT_EDITOR_MODEL", "claude-opus-5-5")

STYLE_PATH = os.path.join(os.path.dirname(__file__), "prompts", "style.md")

with open(STYLE_PATH, encoding="utf-8") as _f:
    STYLE_GUIDE = _f.read()

TONES = ["calm", "lift", "neutral"]

ENRICH_SCHEMA = {
    "type": "object",
    "properties": {
        "is_good_news": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reject_reason": {"type": "string"},
        "score": {"type": "number", "minimum": 0, "maximum": 10,
                  "description": "Editorial strength: 9-10 lead story, 7-8 solid, 5-6 filler, under 5 skip"},
        "section": {"type": "string", "enum": list(SECTIONS.keys())},
        "story_region": {"type": "string", "enum": REGIONS},
        "kid_safe": {"type": "boolean"},
        "tone": {"type": "string", "enum": TONES},
        "read_minutes": {"type": "integer", "minimum": 1, "maximum": 20},
        "headline": {"type": "string"},
        "one_line": {"type": "string"},
        "in_short": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "why_card": {"type": "string"},
        "why_long": {"type": "string"},
        "before": {"type": "string"},
        "now": {"type": "string"},
        "action": {"type": "string"},
        "kid_version": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["is_good_news", "confidence", "reject_reason", "score", "section", "story_region",
                 "kid_safe", "tone", "read_minutes", "headline", "one_line", "in_short", "why_card",
                 "why_long", "before", "now", "action", "kid_version", "keywords"],
    "additionalProperties": False,
}

ENRICH_SYSTEM = (
    "You are the enrichment editor for Peanutlife, a daily good-news site. For each story you "
    "receive, decide whether it is good news by the house rules, then write the pieces the site "
    "needs, in the house voice. Judge only from the text given; do not invent facts, names, numbers "
    "or organisations. If the story is not good news, set is_good_news false, give a short "
    "reject_reason, and still fill the other fields briefly (they are ignored). Use only what the "
    "source says; where it is thin, keep the copy short rather than padding.\n\n"
    "House style and rules follow.\n\n" + STYLE_GUIDE
)

EDITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "letter_title": {"type": "string", "description": "4 to 8 words"},
        "letter": {"type": "string", "description": "120-180 words, signed 'The editor'"},
        "standfirsts": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in SECTIONS},
            "required": list(SECTIONS.keys()),
            "additionalProperties": False,
        },
    },
    "required": ["letter_title", "letter", "standfirsts"],
    "additionalProperties": False,
}

EDITOR_SYSTEM = (
    "You are the editor of Peanutlife, writing the daily letter and the section standfirsts for one "
    "edition. Write only from the stories listed; do not add facts. Where a section has no stories "
    "today, write a standfirst that says what the section is for in one sentence.\n\n"
    "House style follows.\n\n" + STYLE_GUIDE
)


def article_id(link: str) -> str:
    return hashlib.md5(link.encode("utf-8")).hexdigest()


def slugify(title: str) -> str:
    slug = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    if len(slug) > 70:
        slug = slug[:70].rsplit("-", 1)[0]
    return slug or "story"


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _story_prompt(a: dict) -> str:
    summary = re.sub(r"<[^>]+>", " ", a.get("summary") or "")
    summary = re.sub(r"\s+", " ", summary).strip()[:3000]
    return (
        f"Source: {a.get('source_name', '')} (source region: {a.get('source_region', 'global')})\n"
        f"Published: {a.get('published', '')}\n"
        f"Title: {a.get('title', '')}\n"
        f"Text: {summary or '(no summary provided)'}\n"
        f"Link: {a.get('link', '')}"
    )


def enrich_one(a: dict, client: anthropic.Anthropic | None = None) -> dict:
    """Call Claude for one article dict. Returns the parsed enrichment dict."""
    client = client or _client()
    response = client.messages.create(
        model=ENRICH_MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": ENRICH_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _story_prompt(a)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ENRICH_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        return _rejected("refused by safety classifier")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Unparseable enrichment for %s (request %s)", a.get("link"), response._request_id)
        return _rejected("unparseable response")
    data["_model"] = ENRICH_MODEL
    data["_usage"] = {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
        "cache_read": getattr(response.usage, "cache_read_input_tokens", 0),
    }
    return data


def _rejected(reason: str) -> dict:
    return {
        "is_good_news": False, "confidence": 1.0, "reject_reason": reason, "score": 0,
        "section": "progress", "story_region": "global", "kid_safe": False, "tone": "neutral",
        "read_minutes": 3, "headline": "", "one_line": "", "in_short": [], "why_card": "",
        "why_long": "", "before": "", "now": "", "action": "", "kid_version": "", "keywords": [],
        "_model": "none",
    }


# Words that make the dry-run judge say "not good news", so local runs look realistic.
_DRY_BAD = re.compile(r"\b(dies|died|dead|death|killed|murder|shooting|crash|war|review|best \d|vs\.?|deal|sale|"
                      r"stock|shares|trump|election|campaign|iphone|apple|google|meta|zuck)\b", re.I)
_DRY_SECTION = [
    ("kids", r"\b(zoo|puppy|kitten|panda|children|school|kids?)\b"),
    ("nature", r"\b(reef|coral|forest|river|wildlife|species|beaver|whale|solar|wind|climate|ocean|tree)\b"),
    ("sports", r"\b(marathon|olympic|football|cricket|soccer|runner|athlete|match|team)\b"),
    ("science", r"\b(study|research|scientists?|treatment|trial|vaccine|cancer|space|nasa|telescope)\b"),
    ("politics", r"\b(bill|law|parliament|congress|council|minister|government|treaty|vote[sd]?)\b"),
    ("kindness", r"\b(volunteer|donat|stranger|neighbou?r|rescue|kindness|raised)\b"),
    ("culture", r"\b(museum|art|music|book|film|festival|heritage|library)\b"),
]


def dry_enrichment(a: dict) -> dict:
    """Deterministic stand-in for Claude so the site can be built without a key."""
    title = a.get("title", "")
    text = f"{title} {a.get('summary', '')}"
    h = int(article_id(a.get("link", title))[:8], 16)
    bad = bool(_DRY_BAD.search(text))
    section = "progress"
    for name, pat in _DRY_SECTION:
        if re.search(pat, text, re.I):
            section = name
            break
    score = 0 if bad else 5 + (h % 50) / 10.0
    return {
        "is_good_news": not bad, "confidence": 0.6, "reject_reason": "dry-run keyword" if bad else "",
        "score": round(score, 1), "section": section, "story_region": a.get("source_region", "global"),
        "kid_safe": section in ("kids", "nature", "sports") and not bad, "tone": TONES[h % 3],
        "read_minutes": 2 + h % 5, "headline": title[:100], "one_line": title[:120],
        "in_short": [s.strip()[:140] for s in re.split(r"(?<=[.!?])\s+", html.unescape(re.sub(r"<[^>]+>", "", a.get("summary", ""))))[:3] if s.strip()],
        "why_card": "Dry run: why this matters goes here once Claude is connected.",
        "why_long": "Dry run text. Set ANTHROPIC_API_KEY to generate the real summary and significance.",
        "before": "", "now": "", "action": "", "kid_version": "", "keywords": [], "_model": "dry-run",
    }


def enrich_many(articles: list[dict], dry_run: bool = False, concurrency: int = 4) -> list[dict]:
    """Enrich a list of article dicts; returns enrichment dicts in the same order."""
    if dry_run or not has_api_key():
        if not dry_run:
            logger.warning("No Anthropic credentials found; using dry-run enrichment")
        return [dry_enrichment(a) for a in articles]
    client = _client()

    def work(a):
        try:
            return enrich_one(a, client)
        except anthropic.RateLimitError:
            logger.warning("Rate limited; skipping %s this run", a.get("link"))
        except anthropic.APIStatusError as e:
            logger.error("API error %s for %s", e.status_code, a.get("link"))
        except anthropic.APIConnectionError:
            logger.error("Connection error for %s", a.get("link"))
        return None

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        return list(ex.map(work, articles))


def write_edition_copy(edition_name: str, picks: list[dict], section_lists: dict[str, list[dict]],
                       day: datetime, dry_run: bool = False) -> dict:
    """Daily letter plus one standfirst per section, from the day's chosen stories."""
    if dry_run or not has_api_key():
        return {
            "letter_title": "Today's ten",
            "letter": ("Ten stories today. Set ANTHROPIC_API_KEY to have the editor write a real letter "
                       "that finds the through-line in them.\n\nThe editor"),
            "standfirsts": {k: v for k, v in _DEFAULT_STANDFIRSTS.items()},
        }
    lines = [f"Edition: {edition_name}. Date: {day.strftime('%A %d %B %Y')}.", "", "Today's ten:"]
    for i, p in enumerate(picks, 1):
        lines.append(f"{i}. [{p['section']}] {p['title']} — {p['one_line']}")
    lines.append("")
    for section, items in section_lists.items():
        lines.append(f"Section {section} ({SECTIONS[section]}), {len(items)} stories today:")
        for p in items[:6]:
            lines.append(f"  - {p['title']}")
    client = _client()
    response = client.beta.messages.create(
        model=EDITOR_MODEL,
        max_tokens=4096,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": EDITOR_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": EDITOR_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Editor call refused")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)


_DEFAULT_STANDFIRSTS = {
    "kids": "Stories you can read aloud at breakfast. Short words, nothing scary, one question to talk about.",
    "politics": "Only the part of politics that works: laws passed, deals signed, people served.",
    "nature": "Rivers, reefs, forests, and the animals coming back to them.",
    "sports": "Comebacks, sportsmanship and firsts. The scoreboard is the least of it.",
    "science": "Discoveries and treatments that will reach real people, with the caveats kept in.",
    "kindness": "Ordinary people doing something generous, usually without being asked.",
    "culture": "Art, music, craft and heritage: made, saved or shared.",
    "progress": "Things that measurably got better, anywhere.",
}
