# -*- coding: utf-8 -*-
import os
import sys
import json
import re
import threading
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, url_for, session, request, redirect, current_app
from flask_login import LoginManager, current_user

# Import configuration
from src.config import config as app_config

# Import models and routes
from src.models.user import db, User, Topic
from src.routes.admin import admin_bp
from src.routes.auth import auth_bp, init_topics
from src.shared_data import article_cache, get_feed_urls, removed_article_links, load_removed_articles
from src.aggregator import fetch_and_filter_feeds

# Global variables for cache management
articles_by_topic = {}
last_updated = None
cache_refresh_running = False # Global flag to prevent multiple refresh threads

# Template filter functions - define these BEFORE they're used in initialize_app
def format_datetime_filter(iso_string):
    try:
        if isinstance(iso_string, str):
            dt = datetime.fromisoformat(iso_string)
        else:
            dt = iso_string

        # Calculate time difference
        now = datetime.utcnow()
        diff = now - dt

        # If less than 24 hours, show relative time
        if diff.days < 1:
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60

            if hours > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
            elif minutes > 0:
                return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            else:
                return "Just now"

        # Otherwise show date and time
        return dt.strftime("%b %d, %Y %H:%M")
    except (ValueError, TypeError):
        return "(Date unavailable)"

def url_parse_filter(url_string):
    try:
        return urlparse(url_string)
    except Exception:
        return None

def create_app(config_name=None):
    """Application factory function"""
    # Setup Flask app
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        template_folder=os.path.join(os.path.dirname(__file__), "templates")
    )

    # Determine configuration to use
    if not config_name:
        config_name = os.environ.get('FLASK_ENV', 'default')

    # Apply configuration
    app.config.from_object(app_config[config_name])
    app_config[config_name].init_app(app)

    # Initialize services
    initialize_app(app)
    register_routes(app)

    return app

def initialize_app(app):
    """Initialize app components and extensions"""
    global articles_by_topic
    global last_updated

    # Paths for cache files
    cache_file = os.path.join(os.path.dirname(__file__), "static", "articles_cache.json")
    data_dir = app.config.get('DATA_DIR', os.path.join(os.path.dirname(__file__), "..", "data"))
    permanent_cache_file = os.path.join(data_dir, "article_cache.json")
    os.makedirs(data_dir, exist_ok=True)

    # Initialize database
    db.init_app(app)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    # Setup template filters
    app.jinja_env.filters['format_datetime'] = format_datetime_filter
    app.jinja_env.filters['url_parse'] = url_parse_filter

    # Context processors
    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow(), "request": request}

    # Load cached articles at startup
    if os.path.exists(permanent_cache_file):
        try:
            with open(permanent_cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)
                articles_by_topic = cache_data.get("articles", {})
                article_cache["articles"] = articles_by_topic
                last_updated_str = cache_data.get("last_fetched")
                if last_updated_str:
                    last_updated = datetime.fromisoformat(last_updated_str)
                else:
                    last_updated = datetime.now()
            app.logger.info(f"Loaded {sum(len(v) for v in articles_by_topic.values())} cached articles from permanent JSON.")
        except Exception as e:
            app.logger.error(f"Failed to load permanent cache JSON: {e}")
    elif os.path.exists(cache_file):
        try:
            with open(cache_file, encoding='utf-8') as f:
                articles_by_topic = json.load(f)
                last_updated = datetime.now()
            app.logger.info(f"Loaded {sum(len(v) for v in articles_by_topic.values())} cached articles from static JSON.")
        except Exception as e:
            app.logger.error(f"Failed to load cache JSON: {e}")
    else:
        app.logger.warning("Cache JSON not found. Will serve empty articles.")

    # Create database tables
    with app.app_context():
        db.create_all()
        init_topics()  # Initialize topic data

def register_routes(app):
    """Register application routes"""

    @app.route("/")
    def index():
        """Serves the main page with flat mixed feed of positive news articles."""
        global articles_by_topic
        global last_updated

        # Check if we should reload the cache from file
        permanent_cache_file = os.path.join(current_app.config['DATA_DIR'], "article_cache.json")
        try:
            if os.path.exists(permanent_cache_file):
                with open(permanent_cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    articles_by_topic = cache_data.get("articles", {})
                    last_updated_str = cache_data.get("last_fetched")
                    if last_updated_str:
                        last_updated = datetime.fromisoformat(last_updated_str)
        except Exception as e:
            current_app.logger.warning(f"Error loading cache file: {e}")
            # Continue with whatever is in memory

        # Get the topic filter from URL parameter
        selected_topic = request.args.get('topic')

        # Get the sorting option
        sort_option = request.args.get('sort', 'hot')

        if not articles_by_topic:
            articles_by_topic = article_cache.get("articles", {})
            current_app.logger.warning("Using in-memory article_cache as fallback.")

        # Apply user preferences if logged in
        min_inspiration_score = None
        if current_user.is_authenticated:
            min_inspiration_score = current_user.min_inspiration_score

        # Flatten articles
        all_articles = flatten_articles(
            articles_by_topic,
            sort_by_inspiration=(sort_option != 'new'),  # Only sort by inspiration if not "new"
            min_score=min_inspiration_score
        )

        # If sort_option is 'new', sort by published date
        if sort_option == 'new':
            all_articles.sort(key=lambda x: x.get('published', ''), reverse=True)

        # Filter by topic if specified
        if selected_topic:
            filtered_articles = []
            for article in all_articles:
                if article.get('topic_name', '').lower() == selected_topic.lower():
                    filtered_articles.append(article)
            all_articles = filtered_articles

        # Filter by user's favorite topics if logged in and no specific topic selected
        elif current_user.is_authenticated and not selected_topic and current_user.favorite_topics:
            # Only apply this filter if we have more than enough articles overall
            if len(all_articles) > 10:
                favorite_topic_names = [topic.name for topic in current_user.favorite_topics]
                # Keep some top stories regardless of topic, plus favorite topics, ordered by inspiration
                top_stories = all_articles[:4]  # Always keep top stories
                favorite_articles = [a for a in all_articles[4:] if a.get('topic_name', '') in favorite_topic_names]

                # If we have enough favorite articles, use those, otherwise supplement with other articles
                if len(favorite_articles) >= 8:
                    all_articles = top_stories + favorite_articles
                else:
                    # Find non-favorite articles to supplement
                    other_articles = [a for a in all_articles[4:] if a.get('topic_name', '') not in favorite_topic_names]
                    # Limit to a reasonable number
                    supplemental_count = max(8 - len(favorite_articles), 0)
                    all_articles = top_stories + favorite_articles + other_articles[:supplemental_count]

        # Process articles for display - add decorated titles with emojis
        for article in all_articles:
            emoji = ''
            if article.get('topic_icon_path'):
                hex_code = os.path.splitext(os.path.basename(article['topic_icon_path']))[0]
                try:
                    emoji = chr(int(hex_code, 16))
                except Exception:
                    emoji = ''
            decorated_title = f"[{emoji} {article.get('topic_name', 'General').title()}] {article['title']}"
            article['decorated_title'] = decorated_title

        # Get the list of unique topics for the sidebar
        unique_topics = []
        for topic in articles_by_topic.keys():
            if topic not in unique_topics:
                unique_topics.append(topic)

        # Sort topics alphabetically for consistent sidebar
        unique_topics.sort()

        # Get topic icons for sidebar
        topic_icons = {}
        for topic, articles_list in articles_by_topic.items():
            if articles_list and 'topic_icon_path' in articles_list[0]:
                topic_icons[topic] = articles_list[0]['topic_icon_path']

        return render_template(
            "index.html",
            articles=all_articles,
            topics=unique_topics,
            topic_icons=topic_icons,
            selected_topic=selected_topic,
            last_updated=last_updated
        )

    @app.route("/refresh")
    def refresh_articles():
        """Force a refresh of articles"""
        try:
            refresh_thread = threading.Thread(target=refresh_cache_worker)
            refresh_thread.daemon = True
            refresh_thread.start()
            return redirect(url_for('index'))
        except Exception as e:
            return f"Error refreshing: {str(e)}", 500

# Helper functions for article processing
def normalize_text(text):
    """Normalize text for better duplicate detection"""
    if not text:
        return ""
    # Convert to lowercase
    text = text.lower()
    # Remove all punctuation and special characters
    text = re.sub(r'[^\w\s]', '', text)
    # Remove excess whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_content_hash(article):
    """Generate a hash based on normalized article content to detect duplicates"""
    title = normalize_text(article.get('title', ''))
    summary = normalize_text(article.get('summary', ''))

    # Use title + first 100 chars of summary as signature
    content_signature = title + summary[:100] if summary else title
    return hashlib.md5(content_signature.encode()).hexdigest()

def deduplicate_articles(articles_by_topic):
    """
    Remove duplicate articles across topics based on content similarity
    Returns deduplicated dictionary
    """
    print("🔍 Checking for duplicate articles...")

    # Track seen content hashes
    seen_hashes = {}
    total_removed = 0

    # Track which duplicate was kept from which source
    kept_sources = {}

    # New deduplicated dictionary
    deduplicated = {}

    # First pass - identify duplicates
    for topic, articles in articles_by_topic.items():
        deduplicated[topic] = []

        for article in articles:
            content_hash = generate_content_hash(article)

            # If we've seen this content before
            if content_hash in seen_hashes:
                existing_topic = seen_hashes[content_hash]['topic']
                existing_article = seen_hashes[content_hash]['article']

                # Choose which one to keep based on criteria
                # For example, keep the one with higher sentiment score
                if article.get('sentiment_score', 0) > existing_article.get('sentiment_score', 0):
                    # Replace the existing one with this one
                    deduplicated[existing_topic].remove(existing_article)
                    deduplicated[topic].append(article)
                    seen_hashes[content_hash] = {'topic': topic, 'article': article}

                    kept_source = article.get('source_name', 'unknown')
                    kept_sources[content_hash] = kept_source

                total_removed += 1
            else:
                # New unique content
                deduplicated[topic].append(article)
                seen_hashes[content_hash] = {'topic': topic, 'article': article}

                kept_source = article.get('source_name', 'unknown')
                kept_sources[content_hash] = kept_source

    print(f"🧹 Removed {total_removed} duplicate articles")
    return deduplicated

def refresh_cache_worker():
    """Worker function to refresh the article cache in the background"""
    global cache_refresh_running
    global articles_by_topic
    global last_updated

    cache_refresh_running = True

    try:
        print("🟢 Starting background cache refresh...")

        # Load the current removed articles list
        load_removed_articles()

        # Fetch articles incrementally
        temp_articles_by_topic = fetch_and_filter_feeds(get_feed_urls())

        # Update the global articles_by_topic if we got results
        if temp_articles_by_topic and sum(len(articles) for articles in temp_articles_by_topic.values()) > 0:
            articles_by_topic = temp_articles_by_topic
            last_updated = datetime.utcnow()

            # Prepare cache JSON for permanent storage
            cache_data = {
                "last_fetched": last_updated.isoformat(),
                "articles": articles_by_topic
            }

            # Save to data/article_cache.json for persistence
            try:
                app = current_app._get_current_object()
                permanent_cache_file = os.path.join(app.config['DATA_DIR'], "article_cache.json")
                with open(permanent_cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                print(f"🎉 Permanent article cache saved to {permanent_cache_file}")
            except Exception as e:
                print(f"[ERROR] Failed to write permanent cache: {e}")
        else:
            print("[WARN] No articles fetched or empty result - keeping existing articles")

    except Exception as e:
        print(f"[ERROR] Cache refresh failed: {e}")
    finally:
        cache_refresh_running = False

def start_background_refresh(initial_delay=5, interval=None):
    """Start a background thread to refresh the cache periodically"""
    if not interval:
        interval = current_app.config.get('CACHE_DURATION_SECONDS', 900)  # Default to 15 minutes

    def refresh_loop():
        # Initial delay to let the application start up completely
        time.sleep(initial_delay)

        while True:
            # Only start a new refresh if no refresh is currently running
            global cache_refresh_running
            if not cache_refresh_running:
                refresh_thread = threading.Thread(target=refresh_cache_worker)
                refresh_thread.daemon = True  # This ensures the thread will exit when the main process exits
                refresh_thread.start()

            # Wait for the next refresh interval
            time.sleep(interval)

    background_thread = threading.Thread(target=refresh_loop)
    background_thread.daemon = True
    background_thread.start()
    print(f"🔄 Background cache refresh scheduled every {interval} seconds")

def extract_location_from_content(article):
    """
    Try to extract location from article content with improved accuracy
    Returns None if no location found
    """
    # Only process if we have title and summary
    if not article.get('title') or not article.get('summary'):
        return None

    # Combine title and summary for search
    content = f"{article['title']} {article['summary']}"

    # First check for country patterns with more context
    country_patterns = [
        (r'\bin the (United States|USA|U\.S\.|US)\b', 'USA'),
        (r'\bfrom (United States|USA|U\.S\.|US)\b', 'USA'),
        (r'\b(United States|USA|U\.S\.|US) (government|officials|president)\b', 'USA'),
        (r'\bin (the UK|Britain|England|Scotland|Wales|United Kingdom)\b', 'UK'),
        (r'\bfrom (the UK|Britain|England|Scotland|Wales|United Kingdom)\b', 'UK'),
        # Many more country patterns...
    ]

    # Check for country patterns first (more reliable)
    for pattern, country in country_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return country

    # If no country found, check for specific city patterns with context
    city_patterns = [
        (r'\bin New York\b', 'New York, USA'),
        (r'\bfrom New York\b', 'New York, USA'),
        # Many more city patterns...
    ]

    # Check for city patterns
    for pattern, city in city_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return city

    # If source name contains location clues, use that as fallback
    if article.get('source_name'):
        source_name = article['source_name'].lower()

        # USA sources
        if any(usa_source in source_name for usa_source in ['american', 'us ', 'u.s.', 'usa', '.us']):
            return 'USA'

        # UK sources
        if any(uk_source in source_name for uk_source in ['british', 'uk', 'britain', '.uk', 'england']):
            return 'UK'

    # If nothing found, return None
    return None

def flatten_articles(articles_by_topic, sort_by_inspiration=True, min_score=None):
    """
    Convert articles_by_topic dictionary to a flat list
    If sort_by_inspiration is True, sorts by inspiration_score, then published date
    If sort_by_inspiration is False, just keeps articles in chronological order
    min_score can be used to filter articles below a certain inspiration score
    """
    flat = []
    for topic, articles in articles_by_topic.items():
        for article in articles:
            # Ensure each article has an inspiration_score (default to 5 if missing)
            if 'inspiration_score' not in article:
                article['inspiration_score'] = 5

            # Apply minimum score filter if provided
            if min_score is not None and article.get('inspiration_score', 0) < min_score:
                continue

            # Try to extract location from content
            if 'location' not in article:
                location = extract_location_from_content(article)
                if location:
                    article['location'] = location

            flat.append(article)

    if sort_by_inspiration:
        # Sort by inspiration score (highest first), then by published date (newest first)
        flat.sort(key=lambda x: (x.get('is_inspirational', False), x.get('inspiration_score', 0), x.get('published', '')), reverse=True)
    else:
        # Sort by just published date (newest first)
        flat.sort(key=lambda x: x.get('published', ''), reverse=True)

    return flat

# Main entry point
if __name__ == "__main__":
    app = create_app()

    # Start the background cache refresh thread (optional, comment out if not needed)
    with app.app_context():
        cache_duration = app.config.get('CACHE_DURATION_SECONDS', 900)
        # start_background_refresh(initial_delay=5, interval=cache_duration)

    # Start the Flask application
    app.run(host="0.0.0.0", port=5005, debug=app.config.get('DEBUG', False))
