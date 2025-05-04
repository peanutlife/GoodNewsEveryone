# -*- coding: utf-8 -*-
import os
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps

# Import shared data functions and cache
from src.shared_data import article_cache, get_feed_urls, save_feed_urls, add_removed_article_link

# Basic configuration for admin user (replace with more secure method in production)
ADMIN_USERNAME = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASS", "password") # Use environment variables!

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin", url_prefix="/admin")

# --- Authentication Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_logged_in" not in session:
            return redirect(url_for("admin.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            session.permanent = True # Keep session for a reasonable time
            flash("Login successful!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("admin.dashboard"))
        else:
            flash("Invalid username or password.", "danger")
    # Log out if already logged in but visiting login page
    if "admin_logged_in" in session:
         session.pop("admin_logged_in", None)
    return render_template("login.html")

@admin_bp.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("admin.login"))

@admin_bp.route("/")
@login_required
def dashboard():
    articles = article_cache.get("articles", [])
    last_fetched_dt = article_cache.get("last_fetched")
    last_fetched_str = last_fetched_dt.strftime("%Y-%m-%d %H:%M:%S UTC") if last_fetched_dt else "Never"
    current_feeds = get_feed_urls() # Get current feeds
    
    return render_template(
        "dashboard.html", 
        username=ADMIN_USERNAME, 
        articles=articles, 
        articles_count=len(articles),
        feed_urls=current_feeds, # Pass current feeds to template
        last_fetched=last_fetched_str
    )

@admin_bp.route("/manage-feeds", methods=["GET", "POST"])
@login_required
def manage_feeds():
    if request.method == "POST":
        feeds_text = request.form.get("feeds")
        new_feeds = [line.strip() for line in feeds_text.splitlines() if line.strip()]
        if save_feed_urls(new_feeds):
            flash("Feed list updated successfully. Changes will apply on the next fetch cycle.", "success")
        else:
            flash("Error saving feed list. Check file permissions.", "danger")
        return redirect(url_for("admin.manage_feeds"))

    current_feeds = get_feed_urls()
    feeds_text = "\n".join(current_feeds)
    return render_template("manage_feeds.html", feeds_text=feeds_text)

# Article Moderation Route
@admin_bp.route("/remove-article", methods=["POST"])
@login_required
def remove_article():
    article_link = request.form.get("article_link")
    if not article_link:
        flash("No article link provided.", "warning")
        return redirect(url_for("admin.dashboard"))

    if add_removed_article_link(article_link):
        # Corrected flash message (using single line f-string, no erroneous newlines)
        flash(f"Article '{article_link}' marked for removal. It will disappear on the next fetch cycle.", "success")
    else:
        # Corrected flash message (using single line f-string, no erroneous newlines)
        flash(f"Failed to mark article '{article_link}' for removal (maybe already removed or file error?).", "warning")
        
    # Redirect back to the dashboard
    return redirect(url_for("admin.dashboard"))

# Removed the placeholder /moderate-articles route as functionality is added to dashboard

