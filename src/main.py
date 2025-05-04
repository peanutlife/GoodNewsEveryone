# -*- coding: utf-8 -*-
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, url_for, session, request # Added session, request

# Import from shared data and aggregator
from src.shared_data import article_cache, CACHE_DURATION_SECONDS, FEED_URLS
from src.aggregator import fetch_and_filter_feeds
# Import the admin blueprint
from src.routes.admin import admin_bp

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"), template_folder=os.path.join(os.path.dirname(__file__), "templates"))
app.config["SECRET_KEY"] = "brightside_secret_key_123!" # Keep this consistent
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1) # Set session lifetime

# Register the admin blueprint
app.register_blueprint(admin_bp) # Default prefix is /admin as defined in admin.py

# --- Template Filters/Helpers ---

@app.template_filter("format_datetime")
def format_datetime_filter(iso_string):
    """Formats an ISO datetime string for display."""
    try:
        dt = datetime.fromisoformat(iso_string)
        # Format example: May 04, 2025 18:00
        return dt.strftime("%b %d, %Y %H:%M")
    except (ValueError, TypeError):
        return "(Date unavailable)"

@app.template_filter("url_parse")
def url_parse_filter(url_string):
    """Parses a URL string and returns the parsed object."""
    try:
        return urlparse(url_string)
    except Exception:
        return None # Or return an empty object/dict if preferred

@app.context_processor
def inject_now():
    """Inject current year and request object into templates."""
    return {"now": datetime.utcnow(), "request": request}

# --- Routes ---

@app.route("/")
def index():
    """Serves the main page with positive news articles."""
    now = datetime.utcnow()
    should_fetch = True
    # Use article_cache imported from shared_data
    if article_cache["last_fetched"]:
        time_diff = now - article_cache["last_fetched"]
        if time_diff.total_seconds() < CACHE_DURATION_SECONDS:
            should_fetch = False
            print("Using cached articles.")

    if should_fetch:
        print("Fetching new articles...")
        try:
            # Use FEED_URLS from shared_data
            articles = fetch_and_filter_feeds(FEED_URLS)
            article_cache["articles"] = articles
            article_cache["last_fetched"] = now
            print(f"Fetched and cached {len(articles)} articles.")
        except Exception as e:
            print(f"Error fetching articles: {e}")
            # Serve potentially stale cache if fetch fails
            articles = article_cache["articles"]
    else:
        articles = article_cache["articles"]

    return render_template("index.html", articles=articles)

# Note: The default static file serving logic from the template is handled 
# automatically by Flask when static_folder is set. No need for the explicit /<path:path> route 
# unless you need custom logic for static files.

if __name__ == "__main__":
    # Ensure NLTK data is available (though aggregator.py also checks)
    try:
        import nltk
        nltk.data.find("sentiment/vader_lexicon.zip")
    except Exception as e:
        print(f"NLTK VADER lexicon check failed: {e}. Attempting download...")
        try:
            nltk.download("vader_lexicon")
        except Exception as download_e:
            print(f"Failed to download NLTK VADER lexicon: {download_e}")
            print("Sentiment analysis may not work correctly.")
            
    # Perform initial fetch on startup if cache is empty
    if not article_cache["articles"]:
        print("Performing initial article fetch on startup...")
        try:
            initial_articles = fetch_and_filter_feeds(FEED_URLS)
            article_cache["articles"] = initial_articles
            article_cache["last_fetched"] = datetime.utcnow()
            print(f"Fetched and cached {len(initial_articles)} articles on startup.")
        except Exception as e:
            print(f"Error during initial article fetch: {e}")
            
    app.run(host="0.0.0.0", port=5005, debug=False) # Turn debug off for production-like testing

