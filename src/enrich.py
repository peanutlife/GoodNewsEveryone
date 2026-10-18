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
RECENT_ERRORS: list[str] = []  # last few API failures, shown on /_pipeline


def _note_error(msg: str) -> None:
    RECENT_ERRORS.append(f"{datetime.utcnow().isoformat(timespec='seconds')} {msg}"[:400])
    del RECENT_ERRORS[:-8]
    try:
        from src.models.article import log_event
        log_event("error", msg)
    except Exception:  # noqa: BLE001
        pass


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


TRIAGE_BATCH = int(os.environ.get("PEANUT_TRIAGE_BATCH", "40"))

TRIAGE_SYSTEM = (
    "You vet news headlines for Peanutlife, a site that publishes only good news: things that got better, "
    "were repaired, protected, discovered, or done well, and are true. You see the title and the opening "
    "lines of many articles at once. For each, answer whether it is worth a full read.\n\n"
    "yes = clearly a good-news story a thoughtful adult would be glad to read (progress, recovery, "
    "breakthrough, protection, kindness, a law or deal that helps people, a win in sport).\n"
    "maybe = could be, but the headline alone cannot tell (ambiguous, mixed, or thin).\n"
    "no = not good news: crime, death, disaster, war, politics-as-contest, celebrity, product launches, "
    "business results, listicles, how-tos, opinion, horoscopes, deals, or routine reporting.\n\n"
    "score is 0-10 for how strong a good-news story it would be. section is one of: "
    + ", ".join(SECTIONS) + ". Be strict: most items are 'no'. Return one entry per input index."
)

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["yes", "maybe", "no"]},
                    "score": {"type": "number"},
                    "section": {"type": "string", "enum": list(SECTIONS)},
                },
                "required": ["i", "verdict", "score", "section"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _triage_prompt(items: list[dict]) -> str:
    lines = []
    for i, a in enumerate(items):
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", a.get("summary") or "")).strip()[:160]
        lines.append(f"[{i}] ({a.get('source_name', '')}) {a.get('title', '')}" + (f" :: {summary}" if summary else ""))
    return "Vet these articles:\n\n" + "\n".join(lines)


def dry_triage(a: dict) -> dict:
    d = dry_enrichment(a)
    verdict = "no" if not d["is_good_news"] else ("yes" if d["score"] >= 7 else "maybe")
    return {"verdict": verdict, "score": d["score"], "section": d["section"], "_model": "dry-run", "_usage": None}


def triage_batch(items: list[dict], client: anthropic.Anthropic | None = None) -> list[dict | None]:
    """One Claude call vets up to TRIAGE_BATCH articles from titles alone."""
    client = client or _client()
    response = client.messages.create(
        model=ENRICH_MODEL,
        max_tokens=4096,
        system=[{"type": "text", "text": TRIAGE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _triage_prompt(items)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": TRIAGE_SCHEMA}},
    )
    out: list[dict | None] = [None] * len(items)
    if response.stop_reason == "refusal":
        return out
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _note_error(f"unparseable triage response (request {response._request_id})")
        return out
    n = max(1, len(items))
    share = {
        "input": response.usage.input_tokens / n,
        "output": response.usage.output_tokens / n,
        "cache_read": (getattr(response.usage, "cache_read_input_tokens", 0) or 0) / n,
        "cache_write": (getattr(response.usage, "cache_creation_input_tokens", 0) or 0) / n,
    }
    for r in data.get("items", []):
        i = r.get("i")
        if isinstance(i, int) and 0 <= i < len(items):
            out[i] = {"verdict": r["verdict"], "score": float(r.get("score") or 0), "section": r.get("section", "progress"),
                      "_model": ENRICH_MODEL, "_usage": share}
    return out


def triage_many(articles: list[dict], dry_run: bool = False, concurrency: int = 3) -> list[dict | None]:
    """Vet articles in batches; returns one dict (or None on failure) per input, in order."""
    if dry_run or not has_api_key():
        return [dry_triage(a) for a in articles]
    client = _client()
    chunks = [articles[i:i + TRIAGE_BATCH] for i in range(0, len(articles), TRIAGE_BATCH)]

    def work(chunk):
        try:
            return triage_batch(chunk, client)
        except anthropic.RateLimitError as e:
            _note_error(f"triage rate limited: {e}")
        except anthropic.APIStatusError as e:
            _note_error(f"triage API {e.status_code}: {getattr(e, 'message', e)}")
        except anthropic.APIConnectionError as e:
            _note_error(f"triage connection: {e}")
        except Exception as e:  # noqa: BLE001
            logger.exception("Unexpected triage failure")
            _note_error(f"triage {type(e).__name__}: {e}")
        return [None] * len(chunk)

    out: list[dict | None] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for res in ex.map(work, chunks):
            out.extend(res)
    return out


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
        "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
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
        except anthropic.RateLimitError as e:
            logger.warning("Rate limited; skipping %s this run", a.get("link"))
            _note_error(f"rate limited: {e}")
        except anthropic.APIStatusError as e:
            logger.error("API error %s for %s", e.status_code, a.get("link"))
            _note_error(f"API {e.status_code}: {getattr(e, 'message', e)}")
        except anthropic.APIConnectionError as e:
            logger.error("Connection error for %s", a.get("link"))
            _note_error(f"connection: {e}")
        except Exception as e:  # noqa: BLE001 - never let one article kill the batch
            logger.exception("Unexpected enrichment failure for %s", a.get("link"))
            _note_error(f"{type(e).__name__}: {e}")
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
    copy = json.loads(text)
    copy["_meta"] = {
        "model": getattr(response, "model", EDITOR_MODEL),
        "usage": {
            "input": response.usage.input_tokens,
            "output": response.usage.output_tokens,
            "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        },
    }
    return copy


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
