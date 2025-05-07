# -*- coding: utf-8 -*-
import os
import sys
import json
import re
import threading
import time
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, url_for, session, request, redirect

from src.shared_data import article_cache, CACHE_DURATION_SECONDS, get_feed_urls, removed_article_links, load_removed_articles
from src.routes.admin import admin_bp
from src.aggregator import fetch_and_filter_feeds

# Global flag to prevent multiple refresh threads
cache_refresh_running = False

# Load cached articles JSON at startup
CACHE_FILE = os.path.join(os.path.dirname(__file__), "static", "articles_cache.json")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PERMANENT_CACHE_FILE = os.path.join(DATA_DIR, "article_cache.json")
os.makedirs(DATA_DIR, exist_ok=True)  # Create data dir if missing

articles_by_topic = {}

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

            # Prepare cache JSON for permanent storage
            cache_data = {
                "last_fetched": datetime.utcnow().isoformat(),
                "articles": articles_by_topic
            }

            # Save to data/article_cache.json for persistence
            try:
                with open(PERMANENT_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                print(f"🎉 Permanent article cache saved to {PERMANENT_CACHE_FILE}")
            except Exception as e:
                print(f"[ERROR] Failed to write permanent cache: {e}")
        else:
            print("[WARN] No articles fetched or empty result - keeping existing articles")

    except Exception as e:
        print(f"[ERROR] Cache refresh failed: {e}")
    finally:
        cache_refresh_running = False

def start_background_refresh(initial_delay=5, interval=CACHE_DURATION_SECONDS):
    """Start a background thread to refresh the cache periodically"""
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
        (r'\bin Canada\b', 'Canada'),
        (r'\bfrom Canada\b', 'Canada'),
        (r'\bin Australia\b', 'Australia'),
        (r'\bfrom Australia\b', 'Australia'),
        (r'\bin Germany\b', 'Germany'),
        (r'\bfrom Germany\b', 'Germany'),
        (r'\bin France\b', 'France'),
        (r'\bfrom France\b', 'France'),
        (r'\bin Japan\b', 'Japan'),
        (r'\bfrom Japan\b', 'Japan'),
        (r'\bin China\b', 'China'),
        (r'\bfrom China\b', 'China'),
        (r'\bin India\b', 'India'),
        (r'\bfrom India\b', 'India'),
        (r'\bin Russia\b', 'Russia'),
        (r'\bfrom Russia\b', 'Russia'),
        (r'\bin Brazil\b', 'Brazil'),
        (r'\bfrom Brazil\b', 'Brazil'),
        (r'\bin South Africa\b', 'South Africa'),
        (r'\bfrom South Africa\b', 'South Africa'),
        (r'\bin Mexico\b', 'Mexico'),
        (r'\bfrom Mexico\b', 'Mexico'),
        (r'\bin Italy\b', 'Italy'),
        (r'\bfrom Italy\b', 'Italy'),
        (r'\bin Spain\b', 'Spain'),
        (r'\bfrom Spain\b', 'Spain'),
        (r'\bin Belgium\b', 'Belgium'),
        (r'\bfrom Belgium\b', 'Belgium'),
        (r'\bin the Netherlands\b', 'Netherlands'),
        (r'\bfrom the Netherlands\b', 'Netherlands'),
        (r'\bin Sweden\b', 'Sweden'),
        (r'\bfrom Sweden\b', 'Sweden'),
        (r'\bin Norway\b', 'Norway'),
        (r'\bfrom Norway\b', 'Norway'),
        (r'\bin Denmark\b', 'Denmark'),
        (r'\bfrom Denmark\b', 'Denmark'),
        (r'\bin Finland\b', 'Finland'),
        (r'\bfrom Finland\b', 'Finland'),
        (r'\bin Switzerland\b', 'Switzerland'),
        (r'\bfrom Switzerland\b', 'Switzerland'),
        (r'\bin Austria\b', 'Austria'),
        (r'\bfrom Austria\b', 'Austria'),
        (r'\bin Israel\b', 'Israel'),
        (r'\bfrom Israel\b', 'Israel'),
        (r'\bin Saudi Arabia\b', 'Saudi Arabia'),
        (r'\bfrom Saudi Arabia\b', 'Saudi Arabia'),
        (r'\bin Singapore\b', 'Singapore'),
        (r'\bfrom Singapore\b', 'Singapore'),
        # Add more country patterns as needed
    ]

    # Check for country patterns first (more reliable)
    for pattern, country in country_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return country

    # If no country found, check for specific city patterns with context
    city_patterns = [
        (r'\bin New York\b', 'New York, USA'),
        (r'\bfrom New York\b', 'New York, USA'),
        (r'\bin Los Angeles\b', 'Los Angeles, USA'),
        (r'\bfrom Los Angeles\b', 'Los Angeles, USA'),
        (r'\bin Chicago\b', 'Chicago, USA'),
        (r'\bfrom Chicago\b', 'Chicago, USA'),
        (r'\bin London\b', 'London, UK'),
        (r'\bfrom London\b', 'London, UK'),
        (r'\bin Paris\b', 'Paris, France'),
        (r'\bfrom Paris\b', 'Paris, France'),
        (r'\bin Berlin\b', 'Berlin, Germany'),
        (r'\bfrom Berlin\b', 'Berlin, Germany'),
        (r'\bin Tokyo\b', 'Tokyo, Japan'),
        (r'\bfrom Tokyo\b', 'Tokyo, Japan'),
        (r'\bin Beijing\b', 'Beijing, China'),
        (r'\bfrom Beijing\b', 'Beijing, China'),
        (r'\bin Delhi\b', 'Delhi, India'),
        (r'\bfrom Delhi\b', 'Delhi, India'),
        (r'\bin Mumbai\b', 'Mumbai, India'),
        (r'\bfrom Mumbai\b', 'Mumbai, India'),
        (r'\bin Sydney\b', 'Sydney, Australia'),
        (r'\bfrom Sydney\b', 'Sydney, Australia'),
        (r'\bin Toronto\b', 'Toronto, Canada'),
        (r'\bfrom Toronto\b', 'Toronto, Canada'),
        # Add more city patterns as needed
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

        # Add more source patterns as needed

    # If nothing found, return None
    return None

def flatten_articles(articles_by_topic, sort_by_inspiration=True):
    """
    Convert articles_by_topic dictionary to a flat list
    If sort_by_inspiration is True, sorts by inspiration_score, then published date
    Otherwise sorts just by published date
    """
    flat = []
    for topic, articles in articles_by_topic.items():
        for article in articles:
            # Ensure each article has an inspiration_score (default to 5 if missing)
            if 'inspiration_score' not in article:
                article['inspiration_score'] = 5

            # Try to extract location from content
            if 'location' not in article:
                location = extract_location_from_content(article)
                if location:
                    article['location'] = location

            flat.append(article)

    if sort_by_inspiration:
        # Sort by inspiration score (highest first), then by published date (newest first)
        flat.sort(key=lambda x: (x.get('inspiration_score', 0), x.get('published', '')), reverse=True)
    else:
        # Sort by just published date (newest first)
        flat.sort(key=lambda x: x.get('published', ''), reverse=True)

    return flat

# Load cached articles at startup
if os.path.exists(PERMANENT_CACHE_FILE):
    try:
        with open(PERMANENT_CACHE_FILE, encoding='utf-8') as f:
            cache_data = json.load(f)
            articles_by_topic = cache_data.get("articles", {})
            article_cache["articles"] = articles_by_topic
            article_cache["last_fetched"] = datetime.fromisoformat(cache_data.get("last_fetched", datetime.now().isoformat()))
        print(f"[INFO] Loaded {sum(len(v) for v in articles_by_topic.values())} cached articles from permanent JSON.")
    except Exception as e:
        print(f"[ERROR] Failed to load permanent cache JSON: {e}")
elif os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, encoding='utf-8') as f:
            articles_by_topic = json.load(f)
        print(f"[INFO] Loaded {sum(len(v) for v in articles_by_topic.values())} cached articles from static JSON.")
    except Exception as e:
        print(f"[ERROR] Failed to load cache JSON: {e}")
else:
    print("[WARN] Cache JSON not found. Will serve empty articles.")

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    template_folder=os.path.join(os.path.dirname(__file__), "templates")
)

app.config["SECRET_KEY"] = "brightside_secret_key_123!"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)

app.register_blueprint(admin_bp)

@app.template_filter("format_datetime")
def format_datetime_filter(iso_string):
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime("%b %d, %Y %H:%M")
    except (ValueError, TypeError):
        return "(Date unavailable)"

@app.template_filter("url_parse")
def url_parse_filter(url_string):
    try:
        return urlparse(url_string)
    except Exception:
        return None

@app.context_processor
def inject_now():
    return {"now": datetime.utcnow(), "request": request}

@app.route("/")
# Update your main.py route function to reload the cache on each request
# Replace your current index route with this:

@app.route("/")
def index():
    """Serves the main page with flat mixed feed of positive news articles."""
    global articles_by_topic

    # Check if we should reload the cache from file
    # This ensures we always have the latest articles
    try:
        STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
        CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                articles_by_topic = json.load(f)
    except Exception as e:
        print(f"[WARN] Error loading cache file: {e}")
        # Continue with whatever is in memory

    # Get the topic filter from URL parameter
    selected_topic = request.args.get('topic')

    if not articles_by_topic:
        articles_by_topic = article_cache.get("articles", {})
        print("[WARN] Using in-memory article_cache as fallback.")

    # Flatten and sort articles by inspiration score (for top stories)
    all_articles = flatten_articles(articles_by_topic, sort_by_inspiration=True)

    # Filter by topic if specified
    if selected_topic:
        filtered_articles = []
        for article in all_articles:
            if article.get('topic_name', '').lower() == selected_topic.lower():
                filtered_articles.append(article)
        all_articles = filtered_articles

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
        selected_topic=selected_topic
    )

@app.route("/refresh")
def refresh_articles():
    """Force a refresh of articles"""
    try:
        # Use this route only in development
        if app.debug:
            refresh_thread = threading.Thread(target=refresh_cache_worker)
            refresh_thread.daemon = True
            refresh_thread.start()
            return redirect(url_for('index'))
        else:
            return "Refresh only available in debug mode", 403
    except Exception as e:
        return f"Error refreshing: {str(e)}", 500

if __name__ == "__main__":
    # Start the background cache refresh thread
    start_background_refresh(initial_delay=5, interval=CACHE_DURATION_SECONDS)

    # Start the Flask application
    app.run(host="0.0.0.0", port=5005, debug=False)
