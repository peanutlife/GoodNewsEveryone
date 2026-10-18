"""Tests for the redesign: edition detection, pre-filter, edition builder, dry-run enrichment, routes."""
import os
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from src.main import create_app  # noqa: E402
from src.models.user import db  # noqa: E402
from src.models.article import Article, Edition, SECTIONS  # noqa: E402
from src.edition import detect_edition, edition_for_country, edition_for_language  # noqa: E402
from src.pipeline import prefilter  # noqa: E402
from src.enrich import dry_enrichment, ENRICH_SCHEMA  # noqa: E402
from src.editions import pick_ten, build_edition  # noqa: E402


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(TESTING=True, ADS_ENABLED=False)
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------- edition detection ----------

def test_edition_for_country():
    assert edition_for_country("US") == "us"
    assert edition_for_country("JP") == "asia"
    assert edition_for_country("KR") == "asia"
    assert edition_for_country("FR") is None
    assert edition_for_country(None) is None


def test_edition_for_language():
    assert edition_for_language("ja,en;q=0.8") == "asia"
    assert edition_for_language("en-US,en;q=0.9") == "us"
    assert edition_for_language("de-DE") is None


def test_detect_edition_precedence(app):
    with app.test_request_context("/?edition=asia", headers={"CF-IPCountry": "US"}):
        from flask import request
        assert detect_edition(request) == ("asia", "query")
    with app.test_request_context("/", headers={"CF-IPCountry": "US", "Cookie": "edition=asia"}):
        from flask import request
        assert detect_edition(request)[0] == "asia"
    with app.test_request_context("/", headers={"CF-IPCountry": "JP"}):
        from flask import request
        assert detect_edition(request) == ("asia", "header:CF-IPCountry")
    with app.test_request_context("/", headers={"Accept-Language": "en-US"}):
        from flask import request
        assert detect_edition(request)[0] == "us"
    with app.test_request_context("/"):
        from flask import request
        assert detect_edition(request)[0] == "global"


# ---------- pre-filter ----------

def _item(title, summary=""):
    return {"title": title, "summary": summary, "link": "https://x.test/" + title[:10]}


def test_prefilter_drops_hard_excludes_and_keeps_rest():
    items = [
        _item("Village rebuilds school after flood"),
        _item("Man who took out school shooter speaks"),
        _item("Dow Jones hits record as stock market rallies"),
        _item("Best laptops of 2026: our picks"),
        _item("Scientists restore hearing in deaf mice"),
    ]
    kept = [i["title"] for i in prefilter(items)]
    assert "Scientists restore hearing in deaf mice" in kept
    assert all("shooter" not in t and "Dow Jones" not in t and "Best laptops" not in t for t in kept)


# ---------- enrichment ----------

def test_dry_enrichment_matches_schema_keys():
    out = dry_enrichment({"title": "Town plants 10,000 trees", "summary": "Volunteers planted trees. It took a week. Birds returned.",
                          "source_name": "NPR", "source_region": "us", "link": "https://x.test/trees"})
    required = set(ENRICH_SCHEMA["required"])
    assert required <= set(out.keys())
    assert out["section"] in SECTIONS
    assert 0 <= out["score"] <= 10
    assert isinstance(out["in_short"], list) and len(out["in_short"]) <= 3


# ---------- edition builder ----------

def _article(i, *, region="us", section="nature", score=8.0, source="S%d", kid_safe=True, hours_ago=1):
    a = Article(
        id=f"id{i:03d}", link=f"https://x.test/{i}", title=f"Story {i}", summary="s", source_name=source % i if "%d" in source else source,
        source_url="https://x.test/feed", source_region=region, source_quality="standard",
        published=datetime.utcnow() - timedelta(hours=hours_ago), fetched_at=datetime.utcnow(), enriched_at=datetime.utcnow(),
        enrich_model="dry-run", is_good_news=True, confidence=0.9, score=score, section=section, story_region=region,
        kid_safe=kid_safe, read_minutes=3, slug=f"story-{i}", enrichment={"headline": f"Story {i}", "tone": "calm"},
    )
    return a


def test_pick_ten_limits_per_source_and_section(app):
    # Diverse pool: caps of 2 per source and 3 per section hold.
    sections = list(SECTIONS)
    cands = [_article(i, source=f"Src{i % 8}", section=sections[i % len(sections)], score=9 - (i % 5) * 0.5) for i in range(40)]
    picks = pick_ten(cands, "us")
    assert len(picks) == 10
    from collections import Counter
    assert max(Counter(p.source_name for p in picks).values()) <= 2
    assert max(Counter(p.section for p in picks).values()) <= 3
    # Homogeneous pool: caps relax rather than publishing a short list.
    same = [_article(100 + i, source="SameSource", section="nature") for i in range(20)]
    assert len(pick_ten(same, "us")) == 10


def test_build_edition_persists_ten_with_diversity(app):
    sections = list(SECTIONS)
    for i in range(40):
        db.session.add(_article(i, section=sections[i % len(sections)], source=f"Src{i % 12}", region="us" if i % 2 else "global"))
    db.session.commit()
    ed = build_edition("us", date.today(), dry_run=True)
    assert ed.status == "published"
    assert len(ed.picks) == 10
    picked = Article.query.filter(Article.id.in_(ed.picks)).all()
    by_section = {}
    for a in picked:
        by_section[a.section] = by_section.get(a.section, 0) + 1
    assert max(by_section.values()) <= 3
    assert set(ed.section_picks) <= set(SECTIONS)
    assert all(Article.query.get(i).kid_safe for i in ed.section_picks.get("kids", []))


# ---------- routes ----------

def test_home_without_edition_renders_placeholder(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"on their way" in r.data


def test_pages_render_with_edition(client, app):
    sections = list(SECTIONS)
    for i in range(30):
        db.session.add(_article(i, section=sections[i % len(sections)], source=f"Src{i % 10}"))
    db.session.commit()
    build_edition("global", date.today(), dry_run=True)

    r = client.get("/")
    assert r.status_code == 200
    assert b"ten good things" in r.data
    assert b"adsbygoogle" not in r.data  # ADS_ENABLED=False in tests

    for path in ["/section/kids", "/section/nature", "/dial?t=1", "/dial?t=3", "/dial?t=7", "/dial?t=15", "/promise", "/story/story-1", "/?mood=calm", "/?one=1"]:
        r = client.get(path)
        assert r.status_code == 200, path

    r = client.get("/story/does-not-exist")
    assert r.status_code == 404

    r = client.get("/edition/asia")
    assert r.status_code == 302
    assert "edition=asia" in r.headers.get("Set-Cookie", "")

    r = client.get("/_edition", headers={"CF-IPCountry": "KR"})
    assert r.get_json()["edition"] == "asia"


def test_ask_and_follow_endpoints(client, app):
    db.session.add(_article(1))
    db.session.commit()
    r = client.post("/api/ask", json={"article_id": "id001", "question": "How long did it take?"})
    assert r.status_code == 200 and "answer" in r.get_json()
    r = client.post("/api/ask", json={"article_id": "nope", "question": "x"})
    assert r.status_code == 404
    r = client.post("/follow", json={"article_id": "id001", "email": "reader@example.com"})
    assert r.status_code == 200 and r.get_json().get("ok")
    r = client.post("/follow", json={"article_id": "id001", "email": "not-an-email"})
    assert r.status_code == 400


def test_legacy_index_still_served(client):
    assert client.get("/legacy").status_code == 200


# ---------- triage ----------

def test_triage_closes_no_rows_and_enrich_reads_yes_first(app):
    from src.pipeline import triage_pending, enrich_pending
    good = Article(id="g1", link="https://x.test/g1", title="Village restores wetland and birds return", summary="Volunteers rebuilt the marsh.",
                   source_name="NPR", source_url="u", source_region="us", source_quality="high", published=datetime.utcnow(), fetched_at=datetime.utcnow())
    bad = Article(id="b1", link="https://x.test/b1", title="Three killed in highway crash", summary="",
                  source_name="NPR", source_url="u", source_region="us", source_quality="high", published=datetime.utcnow(), fetched_at=datetime.utcnow())
    db.session.add_all([good, bad]); db.session.commit()
    counts = triage_pending(dry_run=True)
    assert counts["no"] >= 1 and (counts["yes"] + counts["maybe"]) >= 1
    assert Article.query.get("b1").enrich_model == "triage-no"
    assert Article.query.get("b1").enriched_at is not None
    assert Article.query.get("g1").enriched_at is None
    n = enrich_pending(dry_run=True)
    assert n == 1
    assert Article.query.get("g1").enriched_at is not None


def test_pipeline_run_endpoint_requires_admin(client, app):
    assert client.post("/_pipeline/run").status_code == 401
    app.config.update(ADMIN_USER="admin", ADMIN_PASS="pw")
    assert client.post("/_pipeline/run", auth=("admin", "wrong")).status_code == 401
    r = client.get("/_pipeline")
    assert r.status_code == 200 and "scheduler" in r.get_json()


# ---------- digest ----------

def test_digest_builds_and_sends_once_per_day(app, monkeypatch):
    from src import digest
    from src.models.subscriber import EmailSubscriber
    sections = list(SECTIONS)
    for i in range(20):
        db.session.add(_article(i, section=sections[i % len(sections)], source=f"Src{i % 7}"))
    db.session.add(EmailSubscriber(email="a@example.com", unsubscribe_token="tok-a", is_active=True))
    db.session.add(EmailSubscriber(email="b@example.com", unsubscribe_token="tok-b", is_active=False))
    db.session.commit()
    ed = build_edition("global", date.today(), dry_run=True)
    html_out = digest.build_html(ed, Article.query.filter(Article.id.in_(ed.picks)).all(), "https://x/unsub")
    assert "Story" in html_out and "unsub" in html_out and "caught up" in html_out

    sent = []
    monkeypatch.setattr(digest, "DIGEST_HOUR", 0)
    import src.email_service as es
    monkeypatch.setattr(es.EmailService, "send_email", lambda self, to, subject, html, text_content=None: sent.append((to, subject)) or True)
    monkeypatch.setattr("src.config.config", {"testing": type("C", (), {"MAIL_USERNAME": "u", "MAIL_PASSWORD": "p", "MAIL_SERVER": "s", "MAIL_PORT": 1, "MAIL_USE_TLS": False, "MAIL_DEFAULT_SENDER": "n@x"})(), "production": None})
    monkeypatch.setenv("FLASK_ENV", "testing")
    assert digest.digest_due() is True
    r = digest.send_digest()
    assert r["sent"] == 1 and [s[0] for s in sent] == ["a@example.com"]
    assert digest.digest_due() is False  # everyone active has today's
    assert digest.send_digest()["skipped"] == 1


def test_subscribe_redirects_to_new_home(client, app):
    r = client.post("/subscribe", data={"email": "new@example.com"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    r = client.get("/")
    assert b"Thank you" in r.data
    assert client.post("/_pipeline/digest").status_code == 401


def test_reader_counter_counts_once_per_day(client, app):
    from src.models.article import Visit
    r = client.get("/")
    assert "pv=" in r.headers.get("Set-Cookie", "")
    client.get("/")
    client.get("/")
    with app.app_context():
        assert Visit.query.count() == 1


def test_feeling_is_one_per_reader_per_day(client, app):
    from src.models.article import Feeling
    r = client.post("/api/feel", json={"feeling": "better"})
    assert r.status_code == 200 and r.get_json()["tally"]["total"] == 1
    r = client.post("/api/feel", json={"feeling": "calmer"})
    assert r.get_json()["tally"]["lifted_pct"] == 100
    assert client.post("/api/feel", json={"feeling": "angry"}).status_code == 400
    with app.app_context():
        assert Feeling.query.count() == 1 and Feeling.query.first().feeling == "calmer"


def test_signin_link_creates_account_and_syncs_journal(client, app):
    from src.models.article import JournalEntry
    with app.test_request_context():
        from src.routes.account import make_signin_token, read_signin_token
        token = make_signin_token("Reader@Example.com")
        assert read_signin_token(token) == "reader@example.com"
        assert read_signin_token("not-a-token") is None
    assert client.get("/api/journal").status_code in (302, 401)
    r = client.get(f"/signin/{token}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["Location"].endswith("/me")
    assert client.get("/me").status_code == 200
    assert client.post("/api/journal", json={"day": "2026-10-18", "text": "The soup turned out."}).status_code == 200
    assert client.post("/api/journal", json={"day": "2026-10-18", "text": "Better soup."}).status_code == 200
    with app.app_context():
        rows = JournalEntry.query.all()
        assert len(rows) == 1 and rows[0].text == "Better soup."
    assert client.get("/api/journal").get_json()["entries"][0]["t"] == "Better soup."
    r = client.post("/api/feel", json={"feeling": "calmer"})
    assert r.status_code == 200
