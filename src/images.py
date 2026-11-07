"""One gate every image URL on the site has to pass.

Pictures used to be hotlinked straight from the publisher's CDN, which sends our
readers' IP addresses to third parties, breaks whenever a publisher blocks us,
and spends someone else's bandwidth on their copyrighted photo. `safe_image_url`
hands back a URL only when its host is ours or explicitly allowlisted; otherwise
templates fall back to the topic styling. The raw value stays in
Article.image_url, so widening IMAGE_HOST_ALLOWLIST is the whole revert.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

#: Comma-separated hosts we may load images from. Empty by default; our own host
#: is always allowed. An entry may start with "." (or "*.") to mean subdomains:
#: ".images.example.com" matches "a.images.example.com" and the bare host.
ALLOWLIST_KEY = "IMAGE_HOST_ALLOWLIST"

#: Shown to social cards and search engines when a story has no usable picture.
FALLBACK_IMAGE_PATH = "/static/icons/icon-512x512.png"

DEFAULT_SITE_URL = "https://www.peanutlife.com"


def _config(key: str):
    try:
        from flask import current_app
        return current_app.config.get(key)
    except Exception:  # noqa: BLE001  (no app context: fall back to the environment)
        return None


def site_url() -> str:
    return (_config("SITE_URL") or os.environ.get("SITE_URL") or DEFAULT_SITE_URL).rstrip("/")


def allowed_image_hosts() -> frozenset[str]:
    """Hosts we are willing to render an <img> from: our own, plus anything configured."""
    raw = _config(ALLOWLIST_KEY)
    if raw is None:
        raw = os.environ.get(ALLOWLIST_KEY, "")
    entries = raw.split(",") if isinstance(raw, str) else list(raw)
    hosts = set()
    for entry in entries:
        entry = (entry or "").strip().lower().lstrip("*")
        if entry:
            hosts.add(entry)
    own = urlsplit(site_url()).hostname
    if own:
        hosts.add(own.lower())
    return frozenset(hosts)


def _host_allowed(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    for entry in allowed_image_hosts():
        if entry.startswith("."):
            if host == entry[1:] or host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


def safe_image_url(url) -> str | None:
    """The URL if we may render it, else None.

    Site-relative paths are ours and always pass. Absolute URLs must be https on
    an allowlisted host, so a publisher CDN never gets a request from a reader.
    """
    url = (url or "").strip() if isinstance(url, str) else ""
    if not url:
        return None
    if url.startswith("//"):  # protocol-relative: host is not ours to trust
        return None
    if url.startswith("/"):
        return url
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return url if _host_allowed(parts.hostname) else None


def og_image_url(url=None) -> str:
    """An absolute image for og:image, twitter:image and JSON-LD.

    Always returns something on our own origin unless the picture itself is
    allowlisted, so social cards keep working without hotlinking.
    """
    safe = safe_image_url(url)
    if safe is None:
        return site_url() + FALLBACK_IMAGE_PATH
    return site_url() + safe if safe.startswith("/") else safe
