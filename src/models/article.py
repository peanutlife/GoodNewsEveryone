"""Enriched article and daily edition storage.

Articles come in from RSS, get judged and written up by Claude once, and are
then assembled into per-edition daily lists (Global / US / East Asia).
"""
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from src.models.user import db

# JSON column type that works on Postgres (JSONB) and SQLite (JSON) for tests.
JSONType = JSON().with_variant(JSONB(), "postgresql")

SECTIONS = {
    "kids": "Good news for kids",
    "politics": "Good news in politics",
    "nature": "Good news in nature",
    "sports": "Great news in sports",
    "science": "Science and health",
    "kindness": "Everyday kindness",
    "culture": "Culture and ideas",
    "progress": "Progress",
}

REGIONS = ["global", "us", "uk", "eu", "east_asia", "south_asia", "africa", "latam"]


class Article(db.Model):
    __tablename__ = "articles"

    id = db.Column(db.String(32), primary_key=True)  # md5 of the link
    link = db.Column(db.Text, nullable=False, unique=True)
    title = db.Column(db.Text, nullable=False)
    summary = db.Column(db.Text, default="")
    image_url = db.Column(db.Text)
    source_name = db.Column(db.String(120), index=True)
    source_url = db.Column(db.Text)
    source_region = db.Column(db.String(20), index=True)
    source_quality = db.Column(db.String(10), default="standard")
    published = db.Column(db.DateTime, index=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Claude's judgement and writing. Null until enriched.
    enriched_at = db.Column(db.DateTime, index=True)
    enrich_model = db.Column(db.String(60))
    is_good_news = db.Column(db.Boolean, index=True)
    confidence = db.Column(db.Float)  # 0-1
    score = db.Column(db.Float, index=True)  # 0-10 editorial strength
    section = db.Column(db.String(20), index=True)
    story_region = db.Column(db.String(20), index=True)  # where the story happened
    kid_safe = db.Column(db.Boolean, default=False)
    read_minutes = db.Column(db.Integer, default=3)
    slug = db.Column(db.String(90), index=True)
    enrichment = db.Column(JSONType)  # headline, one_line, in_short, why_card, why_long, before, now, action, kid_version, keywords

    # Follow-ups: later articles that continue this story.
    follows_id = db.Column(db.String(32), db.ForeignKey("articles.id"), nullable=True)

    def as_card(self):
        e = self.enrichment or {}
        return {
            "id": self.id,
            "slug": self.slug,
            "link": self.link,
            "title": e.get("headline") or self.title,
            "original_title": self.title,
            "one_line": e.get("one_line", ""),
            "why_card": e.get("why_card", ""),
            "action": e.get("action"),
            "image_url": self.image_url,
            "source_name": self.source_name,
            "section": self.section,
            "section_name": SECTIONS.get(self.section, "Today"),
            "region": self.story_region,
            "read_minutes": self.read_minutes or 3,
            "published": self.published,
            "score": self.score,
            "kid_safe": self.kid_safe,
        }


class Edition(db.Model):
    """One day's list for one edition (global / us / asia)."""

    __tablename__ = "editions"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, nullable=False, index=True)
    edition = db.Column(db.String(10), nullable=False, index=True)
    built_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(12), default="draft")  # draft | published
    letter = db.Column(db.Text)
    letter_title = db.Column(db.String(200))
    standfirsts = db.Column(JSONType)  # {section: text}
    picks = db.Column(JSONType)  # ordered list of article ids (the ten)
    section_picks = db.Column(JSONType)  # {section: [ids]}
    mood_orders = db.Column(JSONType)  # {"calm": [ids], "lift": [ids]}

    __table_args__ = (db.UniqueConstraint("day", "edition", name="uq_edition_day"),)


class Follow(db.Model):
    """A reader asked to be told when a story has a next chapter."""

    __tablename__ = "follows"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    article_id = db.Column(db.String(32), db.ForeignKey("articles.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notified_at = db.Column(db.DateTime)
    token = db.Column(db.String(64), unique=True)

    __table_args__ = (db.UniqueConstraint("email", "article_id", name="uq_follow"),)
