"""The morning email: today's ten plus the editor's letter, sent once a day per subscriber.

Replaces the legacy digest that read the old article cache. Content comes from the
published Edition rows, so the email always matches the front page.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime

from src.models.user import db
from src.models.subscriber import EmailSubscriber
from src.models.article import SECTIONS, log_event

logger = logging.getLogger("peanut.digest")

SITE = os.environ.get("PEANUT_SITE_URL", "https://www.peanutlife.com")
DIGEST_EDITION = os.environ.get("PEANUT_DIGEST_EDITION", "global")
DIGEST_HOUR = int(os.environ.get("PEANUT_DIGEST_HOUR", "12"))  # UTC; 12 = 8am New York, 9pm Tokyo

PAPER, INK, MUTED, ACCENT, LINE, CARD = "#FBF7F1", "#1F2A24", "#5C6660", "#B2641A", "#E8E1D5", "#FFFDF9"


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def build_html(ed, picks: list, unsubscribe_url: str) -> str:
    day = ed.day.strftime("%A %-d %B %Y")
    stories = []
    for i, a in enumerate(picks, 1):
        e = a.enrichment or {}
        headline = e.get("headline") or a.title
        why = e.get("why_card") or e.get("one_line") or ""
        action = e.get("action") or ""
        url = f"{SITE}/story/{a.slug}"
        sans = "'Nunito Sans',Helvetica,Arial,sans-serif"
        why_html = (f'<p style="margin:0 0 8px 0;font:400 15px/1.55 {sans};color:{INK};">'
                    f'<span style="color:{ACCENT};font-weight:700;">Why it&#8217;s good news:</span> {_esc(why)}</p>') if why else ""
        action_html = (f'<p style="margin:0 0 8px 0;font:600 14px/1.5 {sans};color:{ACCENT};">Something you can do: '
                       f'<span style="font-weight:400;color:{INK};">{_esc(action)}</span></p>') if action else ""
        stories.append(f"""
<tr><td style="padding:0 0 18px 0;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD};border:1px solid {LINE};border-radius:14px;">
    <tr><td style="padding:18px 20px;">
      <p style="margin:0 0 6px 0;font:600 12px/1.4 'Nunito Sans',Helvetica,Arial,sans-serif;color:{MUTED};letter-spacing:.02em;">
        <span style="color:{ACCENT};font-family:Georgia,serif;font-size:15px;font-weight:700;">{i}</span>&nbsp; {_esc(a.source_name)} · {_esc(SECTIONS.get(a.section, 'Today'))} · {a.read_minutes or 3} min
      </p>
      <h2 style="margin:0 0 8px 0;font:600 21px/1.25 Fraunces,Georgia,'Times New Roman',serif;color:{INK};">
        <a href="{url}" style="color:{INK};text-decoration:none;">{_esc(headline)}</a>
      </h2>
      {why_html}
      {action_html}
      <p style="margin:0;font:600 14px/1.4 'Nunito Sans',Helvetica,Arial,sans-serif;"><a href="{url}" style="color:{ACCENT};text-decoration:none;">Read the story &rarr;</a></p>
    </td></tr>
  </table>
</td></tr>""")

    letter = ""
    if ed.letter:
        sans = "'Nunito Sans',Helvetica,Arial,sans-serif"
        paras = "".join(f'<p style="margin:0 0 12px 0;font:400 16px/1.65 {sans};color:{INK};">{_esc(p.strip())}</p>'
                        for p in ed.letter.split("\n") if p.strip())
        letter = f"""
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD};border:1px solid {LINE};border-radius:14px;">
    <tr><td style="padding:22px 24px;">
      <p style="margin:0 0 4px 0;font:600 12px/1.4 'Nunito Sans',Helvetica,Arial,sans-serif;color:{MUTED};text-transform:uppercase;letter-spacing:.08em;">From the editor</p>
      <h2 style="margin:0 0 12px 0;font:600 22px/1.25 Fraunces,Georgia,serif;color:{INK};">{_esc(ed.letter_title or "Today's ten")}</h2>
      {paras}
    </td></tr>
  </table>
</td></tr>"""

    total_min = sum((a.read_minutes or 3) for a in picks)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>Ten good things for {_esc(day)}</title></head>
<body style="margin:0;padding:0;background:{PAPER};">
<span style="display:none;max-height:0;overflow:hidden;color:transparent;">{_esc((picks[0].enrichment or {}).get('headline') or picks[0].title if picks else 'Ten good things')} &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER};">
<tr><td align="center" style="padding:28px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;">
  <tr><td style="padding:0 0 20px 0;">
    <p style="margin:0 0 6px 0;font:700 18px/1.2 Fraunces,Georgia,serif;color:{INK};"><a href="{SITE}" style="color:{INK};text-decoration:none;">Peanutlife</a></p>
    <h1 style="margin:0 0 6px 0;font:600 28px/1.2 Fraunces,Georgia,serif;color:{INK};">Good morning. Here are today&#8217;s ten good things.</h1>
    <p style="margin:0;font:400 14px/1.5 'Nunito Sans',Helvetica,Arial,sans-serif;color:{MUTED};">{_esc(day)} · about {total_min} minutes for all ten · <a href="{SITE}/dial?t=1" style="color:{ACCENT};text-decoration:none;font-weight:600;">one minute version</a></p>
  </td></tr>
  {letter}
  {''.join(stories)}
  <tr><td style="padding:10px 0 0 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{INK};border-radius:14px;">
      <tr><td style="padding:22px 24px;">
        <p style="margin:0 0 6px 0;font:600 20px/1.25 Fraunces,Georgia,serif;color:#FFFFFF;">That&#8217;s today&#8217;s ten. You&#8217;re all caught up.</p>
        <p style="margin:0;font:400 14px/1.5 'Nunito Sans',Helvetica,Arial,sans-serif;color:#D8DDD9;">Tomorrow&#8217;s ten and a fresh letter arrive at the same time. Nothing else to scroll, on purpose.</p>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:22px 4px 0 4px;">
    <p style="margin:0;font:400 12px/1.6 'Nunito Sans',Helvetica,Arial,sans-serif;color:{MUTED};">
      Liked one? Tap &#9829; on its page and we follow the story for you: next chapters and stories like it land on <a href="{SITE}/me" style="color:{MUTED};">your page</a>.<br>
      You asked for this email at peanutlife.com. One a day, no tracking pixels, no &#8220;we miss you&#8221; emails.<br>
      <a href="{unsubscribe_url}" style="color:{MUTED};">Unsubscribe in one tap</a> &nbsp;·&nbsp; <a href="{SITE}/promise" style="color:{MUTED};">Our reader promise</a>
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def build_text(ed, picks: list, unsubscribe_url: str) -> str:
    lines = [f"PEANUTLIFE — ten good things for {ed.day.strftime('%A %-d %B %Y')}", ""]
    if ed.letter:
        lines += [ed.letter_title or "Today's ten", "", ed.letter, ""]
    for i, a in enumerate(picks, 1):
        e = a.enrichment or {}
        lines.append(f"{i}. {e.get('headline') or a.title}")
        if e.get("why_card"):
            lines.append(f"   Why it's good news: {e['why_card']}")
        lines.append(f"   {SITE}/story/{a.slug}")
        lines.append("")
    lines += ["That's today's ten. You're all caught up.", "",
              f"Liked one? Tap the heart on its page and we follow the story for you: {SITE}/me", "",
              f"Unsubscribe: {unsubscribe_url}"]
    return "\n".join(lines)


def send_digest(edition: str = DIGEST_EDITION, test_email: str | None = None, force: bool = False) -> dict:
    """Send today's edition to every active subscriber who hasn't had it yet. Returns counts."""
    from src.config import config
    from src.editions import latest_edition, articles_by_ids
    from src.email_service import EmailService

    env = os.environ.get("FLASK_ENV", "production")
    cfg = config.get(env, config["production"])
    if not (cfg.MAIL_USERNAME and cfg.MAIL_PASSWORD):
        log_event("error", "digest: MAIL_USERNAME / MAIL_PASSWORD not set")
        return {"sent": 0, "failed": 0, "skipped": 0, "reason": "mail credentials not set"}

    ed = latest_edition(edition)
    if not ed or not ed.picks:
        return {"sent": 0, "failed": 0, "skipped": 0, "reason": f"no published {edition} edition"}
    picks = articles_by_ids(ed.picks)
    if not picks:
        return {"sent": 0, "failed": 0, "skipped": 0, "reason": "edition has no stories"}

    subject = f"Ten good things for {ed.day.strftime('%A %-d %B')}" + (f": {ed.letter_title}" if ed.letter_title else "")
    svc = EmailService(cfg)
    today = datetime.utcnow().date()

    if test_email:
        ok = svc.send_email(test_email, "[test] " + subject, build_html(ed, picks, f"{SITE}/unsubscribe/test"),
                            text_content=build_text(ed, picks, f"{SITE}/unsubscribe/test"))
        log_event("info", f"digest test to {test_email}: {'sent' if ok else 'failed: ' + str(svc.last_error)}")
        return {"sent": int(ok), "failed": int(not ok), "skipped": 0, "test": True, "error": svc.last_error}

    sent = failed = skipped = 0
    streak = 0
    for sub in EmailSubscriber.query.filter_by(is_active=True).order_by(EmailSubscriber.id).all():
        if streak >= 3:
            log_event("error", f"digest: stopped after 3 consecutive failures; last error: {svc.last_error}")
            break
        if not force and sub.last_sent_at and sub.last_sent_at.date() >= today:
            skipped += 1
            continue
        if not sub.unsubscribe_token:
            import secrets
            sub.unsubscribe_token = secrets.token_urlsafe(32)
        unsub = f"{SITE}/unsubscribe/{sub.unsubscribe_token}"
        ok = svc.send_email(sub.email, subject, build_html(ed, picks, unsub), text_content=build_text(ed, picks, unsub))
        if ok:
            sub.last_sent_at = datetime.utcnow()
            sub.total_emails_sent = (sub.total_emails_sent or 0) + 1
            sent += 1
            streak = 0
        else:
            failed += 1
            streak += 1
        db.session.commit()
    log_event("info", f"digest {edition} {ed.day}: sent {sent}, failed {failed}, already had it {skipped}"
              + (f"; last error: {svc.last_error}" if failed else ""))
    return {"sent": sent, "failed": failed, "skipped": skipped, "edition": edition, "day": ed.day.isoformat(), "error": svc.last_error}


BACKOFF_HOURS = 3  # after a mail-server failure, don't retry every hour from every process


def digest_due() -> bool:
    """True when it's past the send hour, someone still hasn't had today's edition, and we aren't backing off."""
    from datetime import timedelta
    from src.editions import latest_edition
    from src.models.article import PipelineEvent
    if os.environ.get("PEANUT_DIGEST", "1") != "1" or datetime.utcnow().hour < DIGEST_HOUR:
        return False
    recent_failure = (PipelineEvent.query.filter(PipelineEvent.kind == "error", PipelineEvent.message.like("digest%"),
                                                 PipelineEvent.at >= datetime.utcnow() - timedelta(hours=BACKOFF_HOURS)).first())
    if recent_failure:
        return False
    ed = latest_edition(DIGEST_EDITION)
    if not ed or ed.day != datetime.utcnow().date():
        return False
    today = datetime.utcnow().date()
    return db.session.query(EmailSubscriber.id).filter(
        EmailSubscriber.is_active.is_(True),
        (EmailSubscriber.last_sent_at.is_(None)) | (db.func.date(EmailSubscriber.last_sent_at) < today),
    ).first() is not None
