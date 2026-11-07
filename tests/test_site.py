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

    for path in ["/section/kids", "/section/nature", "/dial?t=1", "/dial?t=3", "/dial?t=7", "/dial?t=15", "/promise",
                 "/about", "/privacy", "/terms", "/story/story-1", "/?mood=calm", "/?one=1"]:
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
    assert client.get("/_pipeline").status_code == 401
    assert client.get("/_pipeline", auth=("admin", "wrong")).status_code == 401
    r = client.get("/_pipeline", auth=("admin", "pw"))
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
    ed = build_edition("global", datetime.utcnow().date(), dry_run=True)  # digest_due() compares in UTC
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


def _fresh_stats(app):
    """_stats() caches for 60s per process, which outlives a test. Recompute."""
    from src.routes import site as site_routes
    site_routes._STATS_CACHE.update(at=None, value={})
    with app.app_context():
        return site_routes._stats()


def test_homepage_never_shows_a_reader_count(client, app):
    # Visit rows are one cookie per day, so returning readers and cookieless bots inflate
    # the sum. We keep writing them, but no page may present them as a number of people.
    from src.models.article import Visit, count_visit
    today = date.today()
    for d in range(7):
        for n in range(30):
            count_visit(today - timedelta(days=d), f"vid{d}-{n}")
    with app.app_context():
        assert Visit.query.count() == 210  # still stored, just not shown
    stats = _fresh_stats(app)
    assert not [k for k in stats if "reader" in k or "visit" in k], stats
    body = client.get("/").data.decode()
    assert "readers this week" not in body
    assert "210" not in body
    assert "Real numbers from our own database" not in body


def test_counter_labels_checked_stories_not_read_stories(client, app):
    for i in range(12):
        db.session.add(_article(i))
    db.session.commit()
    stats = _fresh_stats(app)
    assert stats["checked_week"] == 12 and stats["checked_today"] == 12
    body = client.get("/").data.decode()
    assert "12</b> stories checked by our software this week" in body
    assert "stories read this week" not in body


def test_source_count_is_the_same_number_everywhere(client, app):
    from src.edition import config
    with app.app_context():
        expected = len(config()["sources"])
    assert _fresh_stats(app)["sources"] == expected
    home, promise = client.get("/").data.decode(), client.get("/promise").data.decode()
    assert f"{expected}</b> sources read every morning" in home
    for body in (home, promise):
        assert f"reads {expected} sources every morning" in body or f"read {expected} sources across" in body
        assert "about 160" not in body


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


def test_like_follows_reader_and_shows_on_my_page(client, app):
    from src.models.article import Like
    with app.app_context():
        db.session.add_all([_article(1, section="nature"), _article(2, section="science")])
        db.session.commit()
    assert client.post("/api/like", json={"article_id": "nope"}).status_code == 404
    r = client.post("/api/like", json={"article_id": "id001", "on": True})
    assert r.status_code == 200 and r.get_json()["liked"] is True and r.get_json()["signed_in"] is False
    assert client.post("/api/like", json={"article_id": "id001", "on": True}).status_code == 200  # idempotent
    with app.app_context():
        assert Like.query.count() == 1 and Like.query.first().user_id is None
    # the heart is painted on the story page for this device
    html = client.get("/story/story-1").get_data(as_text=True)
    assert 'data-like="id001"' in html and 'class="like on"' in html
    # signing in claims the heart for the account
    with app.test_request_context():
        from src.routes.account import make_signin_token
        token = make_signin_token("fan@example.com")
    client.get(f"/signin/{token}")
    with app.app_context():
        assert Like.query.first().user_id is not None
    html = client.get("/me").get_data(as_text=True)
    assert "Stories you're following" in html and "Story 1" in html and "Watching for a next chapter" in html
    # un-heart
    assert client.post("/api/like", json={"article_id": "id001", "on": False}).get_json()["liked"] is False
    with app.app_context():
        assert Like.query.count() == 0


def test_chapter_linking_builds_a_thread(client, app):
    from src.chapters import link_chapters, candidates_for, tracked_roots
    from src.models.article import Like, thread_for
    with app.app_context():
        root = _article(10, section="nature", hours_ago=24 * 20)
        root.enrichment = {"headline": "Otters return to the Thames", "keywords": ["otters", "thames", "river", "wildlife"]}
        later = _article(11, section="nature", hours_ago=2)
        later.enrichment = {"headline": "Thames otters have their first pups", "keywords": ["otters", "thames", "pups"]}
        other = _article(12, section="sports", hours_ago=2)
        other.enrichment = {"headline": "Local club wins the cup", "keywords": ["football", "cup"]}
        db.session.add_all([root, later, other])
        db.session.add(Like(vid="abcdefghijklmnopqrstuv", article_id="id010"))
        db.session.commit()
        assert set(tracked_roots()) == {"id010"}
        assert [c.id for c in candidates_for(later, tracked_roots())] == ["id010"]
        assert candidates_for(other, tracked_roots()) == []
        asked = []

        def judge(new, cands):
            asked.append(new.id)
            return {"continues": cands[0].id, "what_changed": "The otters now have pups."}

        assert link_chapters(judge=judge) == 1
        assert asked == ["id011"]  # the football story never reached Claude
        assert link_chapters(judge=judge) == 0  # already checked, not asked again
        later = db.session.get(Article, "id011")
        assert later.follows_id == "id010" and later.enrichment["chapter_note"] == "The otters now have pups."
        assert [a.id for a in thread_for(db.session.get(Article, "id010"))] == ["id010", "id011"]
    html = client.get("/story/story-11").get_data(as_text=True)
    assert "The story so far" in html and "Otters return to the Thames" in html and "The otters now have pups." in html
    # the reader who hearted the root sees a new-chapter badge on their page
    client.set_cookie("pv", "abcdefghijklmnopqrstuv")
    with app.test_request_context():
        from src.routes.account import make_signin_token
        token = make_signin_token("fan@example.com")
    client.get(f"/signin/{token}")
    html = client.get("/me").get_data(as_text=True)
    assert "1 new chapter" in html and "Thames otters have their first pups" in html
    html = client.get("/me").get_data(as_text=True)  # seen now: badge gone, chapter count stays
    assert "new chapter" not in html and "2 chapters" in html


def test_similar_stories_and_my_page_groups(client, app):
    from src.chapters import similar_stories
    from src.models.article import Like
    with app.app_context():
        root = _article(20, section="nature", hours_ago=24 * 10)
        root.enrichment = {"headline": "Beavers return to Devon rivers", "keywords": ["beavers", "devon", "rivers"]}
        alike = _article(21, section="nature", hours_ago=5)
        alike.enrichment = {"headline": "Scotland's beavers get a new river", "keywords": ["beavers", "scotland", "river"]}
        unrelated = _article(22, section="sports", hours_ago=5)
        unrelated.enrichment = {"headline": "Marathon raises a record sum", "keywords": ["marathon", "charity"]}
        db.session.add_all([root, alike, unrelated])
        db.session.add(Like(vid="abcdefghijklmnopqrstuv", article_id="id020"))
        db.session.commit()
        groups = similar_stories([root], {"id020"})
        assert [(r.id, [a.id for a in sims]) for r, sims in groups] == [("id020", ["id021"])]
        build_edition("us", date.today(), dry_run=True)
    client.set_cookie("pv", "abcdefghijklmnopqrstuv")
    html = client.get("/?edition=us").get_data(as_text=True)
    assert 'id="heart-nudge" ' in html and "Following <b id=\"nudge-n\">1</b>" in html  # signed out: nudge is shown
    with app.test_request_context():
        from src.routes.account import make_signin_token
        token = make_signin_token("fan@example.com")
    client.get(f"/signin/{token}")
    html = client.get("/me").get_data(as_text=True)
    assert "More like the ones you ♥" in html and "Because you ♥" in html and "beavers get a new river" in html
    picks = html.split("More like the ones you")[1].split("Your one good things")[0]
    assert "Marathon raises a record sum" not in picks  # (it is on the page only via the ticker)


# ---------- canonical URLs, sitemap, robots ----------

def test_canonical_is_https_www_without_query(client, app):
    html = client.get("/promise?utm_source=x", base_url="http://peanutlife.com").get_data(as_text=True)
    assert '<link rel="canonical" href="https://www.peanutlife.com/promise">' in html
    assert "http://peanutlife.com" not in html and 'href="http://' not in html.split("<body", 1)[0]


# ---------- legal pages and honest wording ----------

LEGAL_PATHS = ["/privacy", "/terms", "/about"]


def test_legal_pages_render_and_are_linked_from_every_footer(client, app):
    sections = list(SECTIONS)
    for i in range(20):
        db.session.add(_article(i, section=sections[i % len(sections)], source=f"Src{i % 7}"))
    db.session.commit()
    build_edition("global", date.today(), dry_run=True)

    for path in LEGAL_PATHS:
        page = client.get(path)
        assert page.status_code == 200, path
        body = page.get_data(as_text=True)
        assert "contact@peanutlife.com" in body, path  # the only contact address, already public
        assert "TODO" not in body and "pending legal review" not in body, path

    # every page built on the site layout carries all three links in its footer
    for path in ["/", "/promise", "/story/story-1", "/dial", "/section/nature"] + LEGAL_PATHS:
        body = client.get(path).get_data(as_text=True)
        for legal in LEGAL_PATHS:
            assert f'href="{legal}"' in body, f"{legal} missing from {path}"


def test_public_pages_make_no_human_review_or_vendor_claims(client, app):
    """The pipeline has no human review step and we don't name the AI vendor to readers."""
    sections = list(SECTIONS)
    for i in range(20):
        db.session.add(_article(i, section=sections[i % len(sections)], source=f"Src{i % 7}"))
    db.session.commit()
    ed = build_edition("global", date.today(), dry_run=True)
    a = Article.query.get(ed.picks[0])
    a.enrich_model = "some-model"  # so the story byline is rendered at all
    db.session.commit()

    banned = ["claude", "anthropic", "double-check", "the humans at", "good news desk",
              "an editor chooses", "picked and double"]
    for path in ["/", "/promise", "/about", "/privacy", "/terms", "/dial", f"/story/{a.slug}"]:
        body = client.get(path).get_data(as_text=True).lower()
        for phrase in banned:
            assert phrase not in body, f"{phrase!r} still on {path}"

    # the AI disclosure itself must stay
    story = client.get(f"/story/{a.slug}").get_data(as_text=True)
    assert "Summarised with AI from" in story and "not reviewed by a person" in story
    for path in ["/", "/promise", "/about"]:
        assert "AI" in client.get(path).get_data(as_text=True), path


def test_digest_email_is_honest_and_links_the_legal_pages(app):
    from src import digest
    sections = list(SECTIONS)
    for i in range(20):
        db.session.add(_article(i, section=sections[i % len(sections)], source=f"Src{i % 7}"))
    db.session.commit()
    ed = build_edition("global", date.today(), dry_run=True)
    picks = Article.query.filter(Article.id.in_(ed.picks)).all()
    for body in (digest.build_html(ed, picks, "https://x/unsub"), digest.build_text(ed, picks, "https://x/unsub")):
        low = body.lower()
        assert "claude" not in low and "anthropic" not in low
        assert "from the editor" not in low and "double-check" not in low
        assert "written with AI from each publisher" in body
        for legal in LEGAL_PATHS:
            assert legal in body


def test_generated_letter_is_signed_peanutlife(app):
    from src.enrich import EDITOR_SCHEMA, EDITOR_SYSTEM, write_edition_copy
    assert "Peanutlife" in EDITOR_SCHEMA["properties"]["letter"]["description"]
    assert "The editor" not in EDITOR_SCHEMA["properties"]["letter"]["description"]
    assert "Sign the letter 'Peanutlife'" in EDITOR_SYSTEM
    copy = write_edition_copy("global", [], {}, datetime.utcnow(), dry_run=True)
    assert copy["letter"].rstrip().endswith("Peanutlife")


def test_robots_keeps_the_ops_json_out_of_search(client):
    robots = client.get("/robots.txt").get_data(as_text=True).splitlines()
    assert "Disallow: /_pipeline" in robots


def test_sitemap_lists_the_legal_pages(client):
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    for path in LEGAL_PATHS:
        assert f"<loc>https://www.peanutlife.com{path}</loc>" in xml


def test_sitemap_and_robots_use_canonical_origin(client):
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    assert "<loc>https://www.peanutlife.com/</loc>" in xml
    assert "https://peanutlife.com" not in xml
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "Sitemap: https://www.peanutlife.com/sitemap.xml" in robots.splitlines()
    assert all(line == line.lstrip() for line in robots.splitlines())


# ---------- publisher images and the legacy /article pages ----------

PUBLISHER_IMG = "https://assets.rebelmouse.io/eyJhbGciOi/img.png?width=1200&height=800"


def test_safe_image_url_lets_no_third_party_host_through_by_default(app):
    from src.images import og_image_url, safe_image_url
    icon = "https://www.peanutlife.com/static/icons/icon-512x512.png"
    with app.app_context():
        assert safe_image_url(PUBLISHER_IMG) is None
        assert safe_image_url("//assets.rebelmouse.io/img.png") is None  # protocol-relative
        assert safe_image_url("http://www.peanutlife.com/a.png") is None  # http, even for us
        assert safe_image_url("") is None and safe_image_url(None) is None
        # ours passes: site-relative paths and our own host
        assert safe_image_url("/static/icons/icon-512x512.png") == "/static/icons/icon-512x512.png"
        assert safe_image_url("https://www.peanutlife.com/a.png") == "https://www.peanutlife.com/a.png"
        # og:image and JSON-LD always have something on our origin
        assert og_image_url(PUBLISHER_IMG) == icon
        assert og_image_url(None) == icon
        assert og_image_url("/static/icons/icon-512x512.png") == icon


def test_widening_the_image_allowlist_is_the_whole_revert(app):
    from src.images import ALLOWLIST_KEY, safe_image_url
    with app.app_context():
        app.config[ALLOWLIST_KEY] = "assets.rebelmouse.io"
        assert safe_image_url(PUBLISHER_IMG) == PUBLISHER_IMG
        app.config[ALLOWLIST_KEY] = "*.rebelmouse.io"  # subdomain form
        assert safe_image_url(PUBLISHER_IMG) == PUBLISHER_IMG
        assert safe_image_url("https://notrebelmouse.io/a.png") is None  # not a suffix match
        app.config[ALLOWLIST_KEY] = ""
        assert safe_image_url(PUBLISHER_IMG) is None


def test_no_publisher_image_host_in_home_story_or_email(client, app):
    from src.editions import articles_by_ids
    from src.models.article import Edition
    with app.app_context():
        a = _article(30, section="nature")
        a.image_url = PUBLISHER_IMG
        db.session.add(a)
        db.session.commit()
        build_edition("us", date.today(), dry_run=True)
    for path in ("/?edition=us", "/story/story-30", "/section/nature", "/dial", "/yesterday"):
        html = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert "rebelmouse" not in html, path
    story = client.get("/story/story-30").get_data(as_text=True)
    assert 'class="hero t-nature art"' in story  # our own drawing stands in for the hero
    assert '<img src="/static/illustrations/nature.svg" alt="">' in story
    assert '<meta property="og:image" content="https://www.peanutlife.com/static/icons/icon-512x512.png">' in story
    assert '"image":"https://www.peanutlife.com/static/icons/icon-512x512.png"' in story  # JSON-LD
    with app.app_context():
        from src.digest import build_html, build_text
        ed = Edition.query.filter_by(edition="us").first()
        picks = articles_by_ids(ed.picks or [])
        assert picks and picks[0].image_url == PUBLISHER_IMG  # still in the database, so this is reversible
        email = build_html(ed, picks, "https://www.peanutlife.com/unsub")
        assert "rebelmouse" not in email and "<img" not in email
        assert "rebelmouse" not in build_text(ed, picks, "https://www.peanutlife.com/unsub")
        # the legacy digest templates are unused but must not hotlink if they are switched back on
        from src.email_templates import generate_modern_digest_html, generate_nyt_digest_html
        articles = [{"title": "Beavers are back", "link": "https://x.test/1", "topic_name": "nature",
                     "image_url": PUBLISHER_IMG,
                     "summary": f'<img src="{PUBLISHER_IMG}" /><p>Good.</p>'}]
        for build in (generate_nyt_digest_html, generate_modern_digest_html):
            legacy = build(articles, "https://www.peanutlife.com/unsub")
            assert "rebelmouse" not in legacy and "unsplash" not in legacy, build.__name__


def test_legacy_article_pages_serve_noindex_and_leave_the_sitemap(client, app, monkeypatch):
    import src.main as main
    monkeypatch.setattr(main, "PERMANENT_CACHE_FILE", "/nonexistent/article_cache.json")
    monkeypatch.setattr(main, "articles_by_topic", {"nature": [{
        "title": "Beavers are back", "link": "https://x.test/beavers", "summary": "<p>Good news.</p>",
        "image_url": PUBLISHER_IMG, "topic_name": "nature", "source_name": "Riverside Times",
        "published": datetime.utcnow().isoformat(), "why_it_matters": "Rivers come back when beavers do.",
    }]})
    r = client.get("/article/beavers-are-back")
    assert r.status_code == 200  # still reachable: old links and shares keep working
    assert r.headers["X-Robots-Tag"] == "noindex, follow"
    html = r.get_data(as_text=True)
    assert '<meta name="robots" content="noindex, follow">' in html
    assert "rebelmouse" not in html
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/article/" not in xml
    assert f"<loc>https://www.peanutlife.com/story/story-" in xml or "<loc>https://www.peanutlife.com/</loc>" in xml
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "/article" not in robots  # never blocked: Google has to crawl it to see the noindex


# ---------- section illustrations (PEA-14, variants PEA-15) ----------

ART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "static", "illustrations")


def test_every_section_has_its_drawings_small_and_well_formed():
    import xml.etree.ElementTree as ET
    from src.images import SECTION_ART, art_variants
    assert SECTION_ART == set(SECTIONS)  # one set per section, no orphans either way
    seen = set()
    for key in SECTIONS:
        for url in art_variants(key):
            name = os.path.basename(url)
            path = os.path.join(ART_DIR, name)
            assert os.path.exists(path), url
            size = os.path.getsize(path)
            assert size < 12 * 1024, f"{name} is {size} bytes"  # the budget in PEA-14
            root = ET.parse(path).getroot()  # parses, so it is not broken XML
            assert root.tag.endswith("svg") and root.get("viewBox") == "0 0 480 270"
            seen.add(name)
    # and nothing is sitting in the folder that no section can reach
    assert seen == {f for f in os.listdir(ART_DIR) if f.endswith(".svg")}


def test_drawings_stay_inert_and_self_contained():
    """We serve these as <img src>; they must not script, link or fetch anything."""
    banned = ("<script", "<foreignObject", "<use", "javascript:", "<a ", "<image", "onload", "onclick")
    for name in sorted(f for f in os.listdir(ART_DIR) if f.endswith(".svg")):
        body = open(os.path.join(ART_DIR, name), encoding="utf-8").read()
        root_tag, rest = body.split(">", 1)  # the xmlns on <svg> is the one URL allowed
        assert "http" not in rest, f"{name} refers to something off-site"
        for token in banned:
            assert token not in body, f"{name} contains {token!r}"


def test_section_art_path_always_returns_a_drawing():
    from src.images import section_art_path
    assert section_art_path("nature") == "/static/illustrations/nature.svg"
    assert section_art_path("NATURE ") == "/static/illustrations/nature.svg"
    for odd in (None, "", "weather", 7):
        assert section_art_path(odd) == "/static/illustrations/progress.svg"


def test_the_variant_is_a_stable_hash_of_the_story_id():
    # deliberately not hash(): str hashing is salted per process, so two Gunicorn
    # workers would draw the same story differently and it would move on restart
    from src.images import ART_VARIANTS, art_variant_index, art_variants, section_art_path
    assert ART_VARIANTS == 3
    assert art_variants("nature") == (
        "/static/illustrations/nature.svg",
        "/static/illustrations/nature-2.svg",
        "/static/illustrations/nature-3.svg",
    )
    # pinned: change the hash and every story's drawing changes under the readers
    assert [art_variant_index(i) for i in (1, 2, 3, 4)] == [1, 0, 1, 2]
    assert section_art_path("nature", 1) == "/static/illustrations/nature-2.svg"
    assert section_art_path("nature", 2) == "/static/illustrations/nature.svg"
    assert art_variant_index("77") == art_variant_index(77)  # str id or int, one answer
    assert section_art_path("weather", 9) == section_art_path("progress", 9)  # unknown section
    for empty in (None, "", "   "):
        assert art_variant_index(empty) == 0  # no id: the base scene, as before PEA-15
    assert {art_variant_index(i) for i in range(1, 60)} == {0, 1, 2}  # all three get used


def test_neighbouring_stories_in_a_section_usually_get_different_drawings():
    """The point of PEA-15, so it gets a number rather than a hope.

    One drawing per section meant neighbours always matched. An even three-way
    split puts two thirds of adjacent pairs on different scenes; measured 68.6%
    over ids 1-300.
    """
    from src.images import art_variant_index
    picks = [art_variant_index(i) for i in range(1, 301)]
    differ = sum(1 for a, b in zip(picks, picks[1:]) if a != b)
    assert differ / (len(picks) - 1) > 0.55, differ


def test_drawings_are_served_over_http(client):
    r = client.get("/static/illustrations/kids.svg")
    assert r.status_code == 200
    assert "svg" in r.headers["Content-Type"]


def test_pages_show_the_section_drawing_instead_of_an_empty_panel(client, app):
    with app.app_context():
        db.session.add_all([_article(i, section=s) for i, s in enumerate(SECTIONS)])
        db.session.commit()
        build_edition("global", date.today(), dry_run=True)
    for path in ("/", "/section/nature", "/story/story-2", "/dial?t=7"):  # t=7 is the card view
        html = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert "/static/illustrations/" in html, path
        assert 'class="ph"' not in html, path  # the emoji-and-label panel is gone
    from src.images import section_art_path
    home = client.get("/").get_data(as_text=True)
    nature_id = "id%03d" % list(SECTIONS).index("nature")
    assert f'<img src="{section_art_path("nature", nature_id)}" alt="" loading="lazy">' in home
    # decorative only: no drawing is described to a screen reader or handed to social cards
    assert 'alt=""' in home
    for path in ("/", "/story/story-2"):
        html = client.get(path).get_data(as_text=True)
        assert "illustrations" not in html.split("</head>")[0], path  # not in og:image or JSON-LD


def test_a_section_page_no_longer_repeats_one_drawing(client, app):
    """PEA-14 shipped one scene per section, so a section page showed it over and
    over. Six nature stories must now pull more than one of the three scenes, and
    a story's hero must be the same drawing as the card that led to it."""
    import re
    with app.app_context():
        db.session.add_all([_article(i, section="nature", source=f"Src{i}", hours_ago=i + 1) for i in range(6)])
        db.session.commit()
        build_edition("global", date.today(), dry_run=True)
    html = client.get("/section/nature").get_data(as_text=True)
    drawn = re.findall(r"/static/illustrations/(nature[-\w]*\.svg)", html)
    assert len(drawn) == 6, drawn
    assert len(set(drawn)) > 1, drawn  # the whole point of PEA-15
    story = client.get("/story/story-3").get_data(as_text=True)
    from src.images import section_art_path
    hero = section_art_path("nature", "id003")
    assert f'<img src="{hero}" alt="">' in story  # hero matches the card, same id
    assert hero in html


def test_a_real_allowlisted_image_still_wins_over_the_drawing(client, app):
    own = "https://www.peanutlife.com/static/placeholders/kids.jpg"
    with app.app_context():
        a = _article(40, section="kids")
        a.image_url = own
        db.session.add(a)
        db.session.commit()
        build_edition("us", date.today(), dry_run=True)
    story = client.get("/story/story-40").get_data(as_text=True)
    assert f'<img src="{own}" alt="">' in story
    assert "/static/illustrations/" not in story
    assert 'class="hero t-kids"' in story  # no .art class, so it keeps the photo frame height
