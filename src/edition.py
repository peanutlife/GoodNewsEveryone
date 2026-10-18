"""Edition selection: which of Global / US / East Asia a visitor should see.

Order of precedence:
1. `?edition=` query parameter (also sets the cookie)
2. `edition` cookie (the reader chose)
3. Country from the CDN: `CF-IPCountry` (Cloudflare, which fronts Render),
   then `X-Vercel-IP-Country` / `X-Country-Code` style headers
4. `Accept-Language` as a weak hint (en-US -> us; ja, ko, zh-TW, zh-HK -> asia)
5. global
"""
from __future__ import annotations

import os

import yaml

EDITIONS = ("global", "us", "asia")
COOKIE_NAME = "edition"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

_SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.yaml")
_cfg = None


def config():
    global _cfg
    if _cfg is None:
        with open(_SOURCES_PATH, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f)
    return _cfg


def edition_for_country(country: str | None) -> str | None:
    if not country:
        return None
    country = country.upper()
    for key, ed in config()["editions"].items():
        if country in (ed.get("countries") or []):
            return key
    return None


def edition_for_language(accept_language: str | None) -> str | None:
    if not accept_language:
        return None
    first = accept_language.split(",")[0].strip().lower()
    if first.startswith(("ja", "ko", "zh-tw", "zh-hk", "zh-hant", "th", "vi", "ms", "fil", "tl")):
        return "asia"
    if first == "en-us":
        return "us"
    return None


def detect_edition(request) -> tuple[str, str]:
    """Return (edition, how) for a Flask request. `how` is for debugging."""
    q = (request.args.get("edition") or "").lower()
    if q in EDITIONS:
        return q, "query"
    c = (request.cookies.get(COOKIE_NAME) or "").lower()
    if c in EDITIONS:
        return c, "cookie"
    for header in ("CF-IPCountry", "X-Vercel-IP-Country", "X-Country-Code", "CloudFront-Viewer-Country"):
        ed = edition_for_country(request.headers.get(header))
        if ed:
            return ed, f"header:{header}"
    ed = edition_for_language(request.headers.get("Accept-Language"))
    if ed:
        return ed, "language"
    return "global", "default"


def edition_name(edition: str) -> str:
    return config()["editions"].get(edition, {}).get("name", "Global")


def edition_regions(edition: str) -> list[str]:
    return config()["editions"].get(edition, {}).get("regions", ["global"])
