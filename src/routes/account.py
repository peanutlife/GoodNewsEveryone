"""Passwordless accounts: a sign-in link by email, a personal page, and sync for feelings and the journal.

No passwords to forget or leak. The link is signed with the app secret and lives 30 minutes.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from src.models.article import FEELINGS, Feeling, JournalEntry
from src.models.subscriber import EmailSubscriber
from src.models.user import User, db

logger = logging.getLogger(__name__)
account_bp = Blueprint("account", __name__)

LINK_MAX_AGE = 30 * 60
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="peanut-signin")


def make_signin_token(email: str) -> str:
    return _serializer().dumps(email.strip().lower())


def read_signin_token(token: str) -> str | None:
    try:
        return _serializer().loads(token, max_age=LINK_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _mail_ready() -> bool:
    return bool(os.environ.get("MAIL_USERNAME") and os.environ.get("MAIL_PASSWORD"))


def send_signin_link(email: str, link: str) -> bool:
    from src.config import config
    from src.email_service import EmailService
    env = os.environ.get("FLASK_ENV", "production")
    svc = EmailService(config.get(env, config["production"]))
    text = ("Here is your Peanutlife sign-in link. It works for 30 minutes and only once you open it:\n\n"
            f"{link}\n\nIf you did not ask for this, ignore this email. Nothing happens unless the link is opened.")
    html = (f"<div style='font-family:Nunito Sans,system-ui,sans-serif;font-size:16px;color:#1F2A24;max-width:520px'>"
            f"<p style='font-size:22px;font-weight:700;margin:0 0 12px'>Your sign-in link 🥜</p>"
            f"<p>Tap the button to sign in to Peanutlife. The link works for 30 minutes.</p>"
            f"<p style='margin:22px 0'><a href='{link}' style='background:#B2641A;color:#fff;padding:12px 20px;border-radius:999px;"
            f"text-decoration:none;font-weight:700'>Sign me in</a></p>"
            f"<p style='font-size:13px;color:#5B655E'>If you did not ask for this, ignore it. Nothing happens unless the link is opened.</p></div>")
    ok = svc.send_email(email, "Your Peanutlife sign-in link", html, text)
    if not ok:
        logger.warning("Sign-in mail failed for %s: %s", email, svc.last_error)
    return bool(ok)


def _get_or_create_user(email: str) -> User:
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if user:
        return user
    base = re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-") or "reader"
    username = base
    while User.query.filter_by(username=username).first():
        username = f"{base}-{secrets.token_hex(2)}"
    user = User(username=username, email=email)
    user.set_password(secrets.token_urlsafe(24))  # never used; the column is required by the legacy schema
    db.session.add(user)
    db.session.commit()
    return user


@account_bp.route("/signin", methods=["GET", "POST"])
def signin():
    if current_user.is_authenticated:
        return redirect(url_for("account.me"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not _EMAIL_RE.match(email):
            flash("That doesn't look like an email address.", "danger")
            return redirect(url_for("account.signin"))
        if not _mail_ready():
            flash("Sign-in links aren't switched on yet. The mail server still needs to be set up.", "danger")
            return redirect(url_for("account.signin"))
        link = url_for("account.signin_token", token=make_signin_token(email), _external=True)
        if send_signin_link(email, link):
            return render_template("site/message.html", title="Check your email 📬",
                                   body=f"We sent a sign-in link to {email}. It works for 30 minutes. You can close this tab.")
        flash("We couldn't send the email just now. Please try again in a few minutes.", "danger")
        return redirect(url_for("account.signin"))
    return render_template("site/signin.html")


@account_bp.route("/signin/<token>")
def signin_token(token: str):
    email = read_signin_token(token)
    if not email:
        return render_template("site/message.html", title="That link has expired",
                               body="Sign-in links work for 30 minutes. Ask for a fresh one and try again."), 400
    user = _get_or_create_user(email)
    login_user(user, remember=True, duration=timedelta(days=90))
    user.last_login = datetime.utcnow()
    db.session.commit()
    flash("You're signed in. Your feelings and your journal now follow you between devices.", "success")
    return redirect(url_for("account.me"))


@account_bp.route("/signout")
def signout():
    logout_user()
    flash("Signed out. Your notes stay in your account for next time.", "info")
    return redirect(url_for("site.home"))


@account_bp.route("/me")
@login_required
def me():
    since = datetime.utcnow().date() - timedelta(days=29)
    feelings = {f.day: f.feeling for f in Feeling.query.filter(Feeling.user_id == current_user.id, Feeling.day >= since).all()}
    days = [since + timedelta(days=i) for i in range(30)]
    entries = (JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.day.desc()).limit(90).all())
    sub = EmailSubscriber.query.filter(db.func.lower(EmailSubscriber.email) == current_user.email.lower()).first()
    counts = {k: 0 for k in FEELINGS}
    for v in feelings.values():
        if v in counts:
            counts[v] += 1
    return render_template("site/me.html", days=days, feelings=feelings, entries=entries, counts=counts,
                           subscribed=bool(sub and sub.is_active))


@account_bp.route("/api/journal", methods=["GET", "POST"])
@login_required
def journal():
    if request.method == "GET":
        rows = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.day.desc()).limit(365).all()
        return jsonify({"entries": [{"d": r.day.isoformat(), "t": r.text} for r in rows]})
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()[:2000]
    try:
        day = datetime.strptime(str(data.get("day", "")), "%Y-%m-%d").date()
    except ValueError:
        day = datetime.utcnow().date()
    if not text:
        return jsonify({"error": "empty"}), 400
    row = JournalEntry.query.filter_by(user_id=current_user.id, day=day).first()
    if row:
        row.text, row.at = text, datetime.utcnow()
    else:
        db.session.add(JournalEntry(user_id=current_user.id, day=day, text=text))
    db.session.commit()
    return jsonify({"ok": True})
