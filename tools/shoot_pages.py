"""Seed a day, render the real pages through the test client, dump them to disk.

`app.run()` does not bind in this sandbox, so the only way to see a page is to
render it with the Flask test client and rewrite the asset URLs to file:// paths
that headless Chrome can open. Prints, for each page, which section drawing every
card got - which is how PEA-15 checks that neighbours differ.

    python tools/shoot_pages.py /tmp/shots
"""
from __future__ import annotations

import collections
import os
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FLASK_ENV", "testing")

STATIC = ROOT / "src" / "static"
PAGES = {"home": "/", "section-nature": "/section/nature", "section-politics": "/section/politics",
         "story": "/story/story-11", "story-politics": "/story/story-1", "story-politics-2": "/story/story-9"}


def seed():
    from src.editions import build_edition
    from src.models.article import SECTIONS, Article
    from src.models.user import db

    sections = list(SECTIONS)
    for i in range(32):
        db.session.add(Article(
            id=f"id{i:03d}", link=f"https://x.test/{i}", title=f"Story {i}",
            summary="A short summary of what happened and why it is good.",
            source_name=f"Source {i % 9}", source_url="https://x.test/feed",
            source_region="global", source_quality="standard",
            published=datetime.utcnow() - timedelta(hours=i + 1), fetched_at=datetime.utcnow(),
            enriched_at=datetime.utcnow(), enrich_model="dry-run", is_good_news=True,
            confidence=0.9, score=9 - (i % 5) * 0.4, section=sections[i % len(sections)],
            story_region="global", kid_safe=True, read_minutes=3, slug=f"story-{i}",
            enrichment={
                "headline": f"A quietly good thing happened, number {i}",
                "one_line": "Something went right and here is the gist of it.",
                "why_card": "It worked, it is cheap, and somebody else can copy it.",
                "why_long": "It worked, it is cheap, and somebody else can copy it.",
                "in_short": ["The first thing.", "The second thing.", "The third thing."],
                "tone": "calm",
            },
        ))
    db.session.commit()
    build_edition("global", date.today(), dry_run=True)


def localise(html: str) -> str:
    """Point /static/... at the real files so Chrome can load them off disk."""
    return re.sub(r'(["\'(])/static/', lambda m: f"{m.group(1)}file://{STATIC}/", html)


def main(outdir: str) -> None:
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    from src.main import create_app
    from src.models.user import db

    app = create_app()
    app.config.update(TESTING=True, ADS_ENABLED=False)
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed()
        client = app.test_client()
        for name, path in PAGES.items():
            html = client.get(path, follow_redirects=True).get_data(as_text=True)
            (out / f"{name}.html").write_text(localise(html), encoding="utf-8")
            drawn = re.findall(r"/static/illustrations/([\w-]+\.svg)", html)
            print(f"{path:24} {len(drawn)} <img> tags, {len(set(drawn))} distinct drawings")

        # the number PEA-15 is actually about: on each section page, how often does
        # a card sit next to a card of the same section wearing the same drawing?
        from src.images import section_art_path
        from src.models.article import SECTIONS
        from src.routes.site import _edition_payload
        print("\nsection pages, drawing per card in page order:")
        _, _, sections, _ = _edition_payload("global")
        pairs = same = 0
        for slug in SECTIONS:
            items = sections.get(slug, [])
            picks = [os.path.basename(section_art_path(a.section, a.id)) for a in items]
            # The `kids` bucket is every kid-safe story, not the kids section
            # (src/editions.py:76), so its neighbours wear different drawings
            # because they are different sections. Counting those would flatter
            # the result; only same-section neighbours test the hash.
            for (x, a), (y, b) in zip(zip(picks, items), zip(picks[1:], items[1:])):
                if a.section != b.section:
                    continue
                pairs += 1
                same += x == y
            print(f"  {slug:9} {' '.join(p.replace('.svg', '') for p in picks) or '(empty)'}")
        print(f"\n  adjacent same-section pairs: {pairs}, sharing a drawing: {same}"
              f" ({same / pairs:.0%})  [before PEA-15 this was 100%; even 3-way split predicts 33%]")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots")
