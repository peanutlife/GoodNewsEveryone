# -*- coding: utf-8 -*-
import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# Import shared data functions and cache
from src.shared_data import article_cache, get_feed_urls, save_feed_urls, add_removed_article_link
from src.config import config

# Configure logging
logger = logging.getLogger(__name__)

# Admin blueprint
admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin", url_prefix="/admin")

# --- Helper functions ---
def get_admin_credentials():
    """Get admin credentials from config securely"""
    # Get the current configuration
    current_config = config[os.environ.get('FLASK_ENV', 'default')]

    # Get admin credentials
    username = current_config.ADMIN_USER
    password = current_config.ADMIN_PASS

    # Security check - make sure we have valid credentials
    if not username or not password:
        logger.warning("Admin credentials not properly configured! Using default admin/admin is insecure.")
        username = username or "admin"
        password = password or "admin"

    return username, password

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
    # Get admin credentials from config
    admin_username, admin_password = get_admin_credentials()

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Implement rate limiting for failed login attempts
        if 'login_attempts' not in session:
            session['login_attempts'] = 0

        # Check for excessive login attempts
        if session.get('login_attempts', 0) >= 5:
            flash("Too many login attempts. Please try again later.", "danger")
            return render_template("login.html")

        # Verify credentials
        if username == admin_username and password == admin_password:
            # Successful login
            session["admin_logged_in"] = True
            session.permanent = True # Keep session for a reasonable time
            session.pop('login_attempts', None)  # Reset login attempts

            # Set session cookie attributes for security
            session.permanent_session_lifetime = current_app.config.get('PERMANENT_SESSION_LIFETIME')

            # Log successful login
            logger.info(f"Admin login successful for user: {username}")

            flash("Login successful!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("admin.dashboard"))
        else:
            # Failed login
            session['login_attempts'] = session.get('login_attempts', 0) + 1
            logger.warning(f"Failed admin login attempt ({session['login_attempts']}) for username: {username}")
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
    """Serves the admin dashboard with flattened article list."""
    # Get admin username for display
    admin_username, _ = get_admin_credentials()

    # Get articles from cache
    articles_by_topic = article_cache.get("articles", {})
    last_fetched_dt = article_cache.get("last_fetched")
    last_fetched_str = last_fetched_dt.strftime("%Y-%m-%d %H:%M:%S UTC") if last_fetched_dt else "Never"
    current_feeds = get_feed_urls()  # Get current feeds

    # Flatten the articles dictionary into a list for the admin dashboard
    flattened_articles = []
    for topic, articles_list in articles_by_topic.items():
        for article in articles_list:
            # Add topic to each article for display
            article['topic'] = topic
            flattened_articles.append(article)

    # Sort by most recent first
    flattened_articles.sort(key=lambda x: x.get('published', ''), reverse=True)

    return render_template(
        "dashboard.html",
        username=admin_username,
        articles=flattened_articles,
        articles_count=len(flattened_articles),
        feed_urls=current_feeds,
        last_fetched=last_fetched_str
    )

@admin_bp.route("/manage-feeds", methods=["GET", "POST"])
@login_required
def manage_feeds():
    """Manage RSS feed sources"""
    if request.method == "POST":
        feeds_text = request.form.get("feeds")

        # Basic validation
        if not feeds_text:
            flash("Feed list cannot be empty", "warning")
            return redirect(url_for("admin.manage_feeds"))

        # Process input feeds
        new_feeds = []
        for line in feeds_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Basic URL validation
            if not line.startswith(('http://', 'https://')):
                flash(f"Invalid feed URL format: {line}", "warning")
                continue

            new_feeds.append(line)

        # Save validated feeds
        if save_feed_urls(new_feeds):
            logger.info(f"Feed list updated with {len(new_feeds)} feeds")
            flash("Feed list updated successfully. Changes will apply on the next fetch cycle.", "success")
        else:
            logger.error("Failed to save feed list")
            flash("Error saving feed list. Check file permissions.", "danger")

        return redirect(url_for("admin.manage_feeds"))

    # GET request - show current feeds
    current_feeds = get_feed_urls()
    feeds_text = "\n".join(current_feeds)
    return render_template("manage_feeds.html", feeds_text=feeds_text)

@admin_bp.route("/remove-article", methods=["POST"])
@login_required
def remove_article():
    """Remove an article from the feed"""
    article_link = request.form.get("article_link")
    if not article_link:
        flash("No article link provided.", "warning")
        return redirect(url_for("admin.dashboard"))

    # Sanitize input
    article_link = article_link.strip()

    if add_removed_article_link(article_link):
        logger.info(f"Article removed: {article_link}")
        flash(f"Article marked for removal. It will disappear on the next fetch cycle.", "success")
    else:
        logger.warning(f"Failed to remove article: {article_link}")
        flash("Failed to mark article for removal. It may already be removed or there was a file error.", "warning")

    # Redirect back to the dashboard
    return redirect(url_for("admin.dashboard"))


# --- Editor's Picks Routes ---

@admin_bp.route("/editors-picks", methods=["GET"])
@login_required
def editors_picks():
    """Manage Editor's Picks - select top 5 daily articles"""
    import json
    from datetime import datetime
    
    # Load articles from cache
    cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "article_cache.json")
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            articles_by_topic = cache_data.get("articles", {})
    except Exception as e:
        logger.error(f"Error loading cache: {e}")
        articles_by_topic = {}
    
    # Flatten articles
    all_articles = []
    for topic, articles in articles_by_topic.items():
        for article in articles:
            # Add topic info
            article['topic'] = topic
            # Check if already an editor's pick
            if 'is_editors_pick' not in article:
                article['is_editors_pick'] = False
            all_articles.append(article)
    
    # Sort by inspiration score (highest first)
    all_articles.sort(key=lambda x: x.get('inspiration_score', 0), reverse=True)
    
    # Get current editor's picks
    current_picks = [a for a in all_articles if a.get('is_editors_pick', False)]
    
    # Category options
    categories = [
        {'emoji': '🔬', 'name': 'Science', 'id': 'science'},
        {'emoji': '🌍', 'name': 'Planet', 'id': 'planet'},
        {'emoji': '❤️', 'name': 'People', 'id': 'people'},
        {'emoji': '🤝', 'name': 'Kindness', 'id': 'kindness'},
        {'emoji': '💡', 'name': 'Innovation', 'id': 'innovation'},
        {'emoji': '🏆', 'name': 'Achievement', 'id': 'achievement'},
        {'emoji': '🐾', 'name': 'Animals', 'id': 'animals'},
        {'emoji': '🎨', 'name': 'Culture', 'id': 'culture'},
        {'emoji': '👥', 'name': 'Social Progress', 'id': 'social'},
        {'emoji': '💪', 'name': 'Overcoming Odds', 'id': 'triumph'},
    ]
    
    return render_template("admin/editors_picks.html", 
                          articles=all_articles[:50],  # Show top 50 candidates
                          current_picks=current_picks,
                          categories=categories,
                          today=datetime.utcnow().strftime('%B %d, %Y'))


@admin_bp.route("/editors-picks/save", methods=["POST"])
@login_required
def save_editors_picks():
    """Save editor's picks selections"""
    import json
    import hashlib
    
    # Get form data
    selected_articles = request.form.getlist('selected_articles')  # List of article links
    editors_notes = {}
    pick_categories = {}
    
    # Get notes and categories for each selected article
    for link in selected_articles:
        # Create a safe key from the link
        link_hash = hashlib.md5(link.encode('utf-8')).hexdigest()[:8]
        note_key = f'note_{link_hash}'
        category_key = f'category_{link_hash}'
        
        editors_notes[link] = request.form.get(note_key, '')
        pick_categories[link] = request.form.get(category_key, '')
    
    # Load cache
    cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "article_cache.json")
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # Update articles
        articles_by_topic = cache_data.get("articles", {})
        
        # First, clear all existing editor's picks
        for topic in articles_by_topic:
            for article in articles_by_topic[topic]:
                article['is_editors_pick'] = False
                article['editors_note'] = ''
                article['pick_category'] = ''
        
        # Now set the new editor's picks
        for topic in articles_by_topic:
            for article in articles_by_topic[topic]:
                if article['link'] in selected_articles:
                    article['is_editors_pick'] = True
                    article['editors_note'] = editors_notes.get(article['link'], '')
                    article['pick_category'] = pick_categories.get(article['link'], '')
                    logger.info(f"Set editor's pick: {article['title']}")
        
        # Save back to cache
        cache_data['articles'] = articles_by_topic
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        flash(f"Successfully saved {len(selected_articles)} editor's picks!", "success")
        logger.info(f"Saved {len(selected_articles)} editor's picks")
        
    except Exception as e:
        logger.error(f"Error saving editor's picks: {e}")
        flash(f"Error saving editor's picks: {str(e)}", "danger")
    
    return redirect(url_for('admin.editors_picks'))
