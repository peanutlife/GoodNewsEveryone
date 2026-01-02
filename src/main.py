# -*- coding: utf-8 -*-
import os
import sys
import json
import re
import threading
import time
import hashlib
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, url_for, session, request, redirect, send_file
from flask_login import LoginManager, current_user

# Import models and routes
from src.models.user import db, User, Topic
from src.routes.admin import admin_bp
from src.routes.auth import auth_bp, init_topics
from src.shared_data import article_cache, CACHE_DURATION_SECONDS, get_feed_urls, removed_article_links, load_removed_articles, NEGATIVE_KEYWORDS
from src.aggregator import fetch_and_filter_feeds
from src.models.subscriber import EmailSubscriber
from src.config import config

# Set up logging
logging.basicConfig(level=logging.INFO,
                   format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')

# Hero-specific negative keywords (stricter filter for top story)
HERO_EXCLUDE_KEYWORDS = [
    "dies", "died", "death", "dead", "dying", "passing", "passed away",
    "funeral", "obituary", "tribute", "memorial", "mourning", "grief",
    "killed", "murder", "shooting", "stabbing", "violence", "accident"
]

# Global flag to prevent multiple refresh threads
cache_refresh_running = False

# Define paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# Use Render persistent disk if available, otherwise local data dir
if os.path.exists("/data"):
    # Render persistent disk
    DATA_DIR = "/data"
    logging.info("✅ Using Render persistent disk: /data")
else:
    # Local development
    DATA_DIR = os.path.join(BASE_DIR, "data")
    logging.info("📁 Using local data directory")

CACHE_FILE = os.path.join(os.path.dirname(__file__), "static", "articles_cache.json")
PERMANENT_CACHE_FILE = os.path.join(DATA_DIR, "article_cache.json")
QUOTES_FILE = os.path.join(os.path.dirname(__file__), "static", "quotes.json")

# Create necessary directories
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), "static"), exist_ok=True)

# Initialize global variables
articles_by_topic = {}
last_updated = None


def is_suitable_for_hero(article):
    """Check if an article is suitable for the hero position"""
    if not article:
        return False

    title = article.get('title', '').lower()
    summary = article.get('summary', '').lower()
    combined = f"{title} {summary}"

    # Check for death/negative keywords
    for keyword in HERO_EXCLUDE_KEYWORDS:
        if keyword in combined:
            logging.info(f"Excluding from hero: '{article.get('title', '')}' - contains '{keyword}'")
            return False

    # Require minimum inspiration score (stricter filter for hero)
    if article.get('inspiration_score', 0) < 9:
        return False

    return True


def normalize_text(text):
    """Normalize text for better duplicate detection"""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_old_articles(articles_by_topic, days_to_keep=30):
    """Remove articles older than specified days to prevent memory bloat"""
    cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
    cleaned = {}
    total_removed = 0

    for topic, articles in articles_by_topic.items():
        cleaned[topic] = []
        for article in articles:
            try:
                pub_date_str = article.get('published', '')
                if pub_date_str:
                    pub_date = datetime.fromisoformat(pub_date_str)
                    if pub_date >= cutoff_date:
                        cleaned[topic].append(article)
                    else:
                        total_removed += 1
                else:
                    # Keep articles without dates
                    cleaned[topic].append(article)
            except (ValueError, TypeError):
                # Keep articles with invalid dates
                cleaned[topic].append(article)

    logging.info(f"🧹 Cleaned {total_removed} articles older than {days_to_keep} days")
    return cleaned


def limit_articles_per_topic(articles_by_topic, max_per_topic=50):
    """Limit number of articles per topic to prevent memory bloat"""
    limited = {}
    total_removed = 0

    for topic, articles in articles_by_topic.items():
        if len(articles) > max_per_topic:
            # Keep top articles by inspiration score
            sorted_articles = sorted(
                articles,
                key=lambda x: (x.get('inspiration_score', 0), x.get('published', '')),
                reverse=True
            )
            limited[topic] = sorted_articles[:max_per_topic]
            total_removed += len(articles) - max_per_topic
        else:
            limited[topic] = articles

    logging.info(f"🧹 Removed {total_removed} articles (limit: {max_per_topic} per topic)")
    return limited


def generate_content_hash(article):
    """Generate a hash based on normalized article content to detect duplicates"""
    title = normalize_text(article.get('title', ''))
    summary = normalize_text(article.get('summary', ''))
    content_signature = title + summary[:100] if summary else title
    return hashlib.md5(content_signature.encode()).hexdigest()


def deduplicate_articles(articles_by_topic):
    """Remove duplicate articles across topics based on content similarity"""
    print("🔍 Checking for duplicate articles...")
    seen_hashes = {}
    total_removed = 0
    deduplicated = {}

    for topic, articles in articles_by_topic.items():
        deduplicated[topic] = []

        for article in articles:
            content_hash = generate_content_hash(article)

            if content_hash in seen_hashes:
                existing_topic = seen_hashes[content_hash]['topic']
                existing_article = seen_hashes[content_hash]['article']

                if article.get('sentiment_score', 0) > existing_article.get('sentiment_score', 0):
                    deduplicated[existing_topic].remove(existing_article)
                    deduplicated[topic].append(article)
                    seen_hashes[content_hash] = {'topic': topic, 'article': article}

                total_removed += 1
            else:
                deduplicated[topic].append(article)
                seen_hashes[content_hash] = {'topic': topic, 'article': article}

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

        # Clear old data from memory BEFORE fetching new data
        import gc
        old_count = sum(len(articles) for articles in articles_by_topic.values()) if articles_by_topic else 0
        articles_by_topic = {}  # Clear global cache
        gc.collect()  # Force garbage collection
        logging.info(f"🧹 Cleared {old_count} articles from memory before refresh")

        load_removed_articles()
        temp_articles_by_topic = fetch_and_filter_feeds(get_feed_urls())

        if temp_articles_by_topic and sum(len(articles) for articles in temp_articles_by_topic.values()) > 0:
            # Clean old articles (>30 days)
            temp_articles_by_topic = clean_old_articles(temp_articles_by_topic, days_to_keep=30)

            # Limit articles per topic (max 50 per topic)
            temp_articles_by_topic = limit_articles_per_topic(temp_articles_by_topic, max_per_topic=50)

            articles_by_topic = temp_articles_by_topic
            last_updated = datetime.utcnow()

            cache_data = {
                "last_fetched": last_updated.isoformat(),
                "articles": articles_by_topic
            }

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
        time.sleep(initial_delay)

        while True:
            global cache_refresh_running
            if not cache_refresh_running:
                refresh_thread = threading.Thread(target=refresh_cache_worker)
                refresh_thread.daemon = True
                refresh_thread.start()

            time.sleep(interval)

    background_thread = threading.Thread(target=refresh_loop)
    background_thread.daemon = True
    background_thread.start()
    print(f"🔄 Background cache refresh scheduled every {interval} seconds")


def extract_location_from_content(article):
    """Try to extract location from article content with improved accuracy"""
    if not article.get('title') or not article.get('summary'):
        return None

    content = f"{article['title']} {article['summary']}"

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
    ]

    for pattern, country in country_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return country

    city_patterns = [
        (r'\bin New York\b', 'New York, USA'),
        (r'\bfrom New York\b', 'New York, USA'),
        (r'\bin Los Angeles\b', 'Los Angeles, USA'),
        (r'\bin London\b', 'London, UK'),
        (r'\bin Paris\b', 'Paris, France'),
        (r'\bin Tokyo\b', 'Tokyo, Japan'),
    ]

    for pattern, city in city_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return city

    if article.get('source_name'):
        source_name = article['source_name'].lower()
        if any(usa_source in source_name for usa_source in ['american', 'us ', 'u.s.', 'usa', '.us']):
            return 'USA'
        if any(uk_source in source_name for uk_source in ['british', 'uk', 'britain', '.uk', 'england']):
            return 'UK'

    return None


def flatten_articles(articles_by_topic, sort_by_inspiration=True, min_score=None):
    """Convert articles_by_topic dictionary to a flat list"""
    flat = []
    for topic, articles in articles_by_topic.items():
        for article in articles:
            if 'inspiration_score' not in article:
                article['inspiration_score'] = 5

            if min_score is not None and article.get('inspiration_score', 0) < min_score:
                continue

            if 'location' not in article:
                location = extract_location_from_content(article)
                if location:
                    article['location'] = location

            if isinstance(article.get('published'), str):
                try:
                    article['_published_dt'] = datetime.fromisoformat(article['published'])
                except (ValueError, TypeError):
                    article['_published_dt'] = datetime.utcnow()
            else:
                article['_published_dt'] = datetime.utcnow()

            # Initialize editor's pick fields if not present
            if 'is_editors_pick' not in article:
                article['is_editors_pick'] = False
            if 'editors_note' not in article:
                article['editors_note'] = ''
            if 'pick_category' not in article:
                article['pick_category'] = ''

            flat.append(article)

    if sort_by_inspiration:
        flat.sort(key=lambda x: (
            x.get('is_inspirational', False),
            x.get('inspiration_score', 0),
            x.get('_published_dt', datetime.utcnow())
        ), reverse=True)
    else:
        flat.sort(key=lambda x: x.get('_published_dt', datetime.utcnow()), reverse=True)

    return flat


def get_daily_quote():
    """Get today's inspirational quote - birthday tribute if available, otherwise daily rotation"""
    try:
        with open(QUOTES_FILE, 'r', encoding='utf-8') as f:
            quotes_data = json.load(f)

        today = datetime.utcnow()
        date_key = today.strftime("%m-%d")  # Format: "01-15" for January 15

        # Check if today is a special birthday
        if date_key in quotes_data['birthday_quotes']:
            birthday = quotes_data['birthday_quotes'][date_key]
            return {
                'type': 'birthday',
                'person': birthday['person'],
                'year': birthday.get('year', ''),
                'quote': birthday['quote'],
                'context': birthday.get('context', '')
            }

        # Otherwise, return a daily rotating quote
        daily_quotes = quotes_data['daily_quotes']
        # Use day of year to select quote (same quote all day, rotates daily)
        day_of_year = today.timetuple().tm_yday
        quote_index = day_of_year % len(daily_quotes)
        selected_quote = daily_quotes[quote_index]

        return {
            'type': 'daily',
            'quote': selected_quote['quote'],
            'author': selected_quote['author']
        }

    except Exception as e:
        logging.error(f"Error loading daily quote: {e}")
        # Fallback quote
        return {
            'type': 'daily',
            'quote': 'Take a breath. Relax. Rediscover the good unfolding around us every day.'
        }


def generate_why_it_matters(article_title, article_summary, topic_name):
    """Generate a custom 'Why It Matters' section using OpenAI API"""
    # TEMPORARILY DISABLED: Using fallback templates to avoid API costs
    # TODO: Re-enable with proper caching to permanent storage
    return get_fallback_why_it_matters(topic_name)

    try:
        # Get API key from config
        openai_api_key = config['development'].OPENAI_API_KEY
        if not openai_api_key:
            logging.warning("OpenAI API key not configured, using fallback message")
            return get_fallback_why_it_matters(topic_name)

        # Initialize OpenAI client
        client = OpenAI(api_key=openai_api_key)

        # Create the prompt
        prompt = f"""You are writing for Peanutlife, a website that curates positive, uplifting news.

Article Title: {article_title}
Article Summary: {article_summary[:500]}
Topic: {topic_name}

Write a compelling 2-3 sentence "Why This Matters" section that:
- Explains the broader significance or impact of this story
- Connects it to hope, progress, or positive change
- Is specific to this article (use concrete details, numbers if mentioned)
- Uses warm, inspiring tone
- Avoids generic phrases

Example good outputs:
- "This breakthrough could bring clean energy to 2 million homes in foggy regions, reducing carbon emissions by 40% while cutting energy costs for families."
- "Small acts of kindness like this demonstrate how community support can transform lives and inspire others to contribute to local change."

Write only the "Why This Matters" text, nothing else:"""

        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a writer for an uplifting news website. Write concise, specific, inspiring explanations."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )

        why_it_matters = response.choices[0].message.content.strip()
        logging.info(f"Generated 'Why It Matters' for article: {article_title[:50]}...")
        return why_it_matters

    except Exception as e:
        logging.error(f"Error generating 'Why It Matters' with OpenAI: {e}")
        return get_fallback_why_it_matters(topic_name)


def get_fallback_why_it_matters(topic_name):
    """Fallback 'Why It Matters' messages when OpenAI is unavailable"""
    fallbacks = {
        'environment': "Stories like this show real progress in protecting our planet and fighting climate change, giving us hope for a sustainable future.",
        'health': "Medical breakthroughs like this offer hope to patients worldwide and represent years of dedicated research improving lives.",
        'technology': "Innovations like this demonstrate how technology can solve real-world problems and make daily life better for millions.",
        'science': "Scientific discoveries like this expand human knowledge and open new possibilities for addressing global challenges.",
        'business': "Entrepreneurial stories like this show how innovation and determination can create positive change and opportunities.",
        'relationships': "Stories of human connection like this remind us of the power of empathy, kindness, and community support.",
        'general': "Stories like this remind us of the positive change happening around the world, giving us hope and inspiring us to contribute to a better future."
    }

    topic_lower = topic_name.lower() if topic_name else 'general'
    return fallbacks.get(topic_lower, fallbacks['general'])


def generate_article_id(article_link):
    """Generate a stable, consistent article ID from the article link URL"""
    # Use MD5 hash for stable IDs across sessions (hash() is not stable)
    return hashlib.md5(article_link.encode('utf-8')).hexdigest()[:16]


def generate_article_slug(title):
    """Generate SEO-friendly URL slug from article title"""
    import unicodedata

    # Normalize unicode characters
    slug = unicodedata.normalize('NFKD', title)
    slug = slug.encode('ascii', 'ignore').decode('ascii')

    # Convert to lowercase and replace spaces with hyphens
    slug = slug.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)  # Remove non-word chars except hyphens
    slug = re.sub(r'[-\s]+', '-', slug)   # Replace multiple spaces/hyphens with single hyphen
    slug = slug.strip('-')                 # Remove leading/trailing hyphens

    # Limit length to 60 characters
    if len(slug) > 60:
        slug = slug[:60].rsplit('-', 1)[0]  # Cut at last word boundary

    return slug or 'article'  # Fallback if slug is empty


def create_app():
    """Create and configure the Flask application"""
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        template_folder=os.path.join(os.path.dirname(__file__), "templates")
    )

    # Load configuration from config class
    env = os.environ.get('FLASK_ENV', 'production')
    app_config = config[env]
    app_config.init_app(app)

    # Set session lifetime
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)

    # Log configuration info (sanitized)
    logging.info(f"🚀 Starting application in {env} mode")
    logging.info(f"Debug mode: {app.config.get('DEBUG', False)}")

    # Log database info without exposing credentials
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri:
        try:
            parsed = urlparse(db_uri)
            safe_uri = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 'default'}{parsed.path}"
            logging.info(f"Database: {safe_uri}")
        except Exception as e:
            logging.warning(f"Could not parse database URI: {e}")
    else:
        logging.warning("⚠️  No database URI configured!")

    # Initialize application with additional configuration
    initialize_app(app)

    return app


def initialize_app(app):
    """Initialize Flask application with database and routes"""
    global articles_by_topic
    global last_updated

    # Load cached articles at startup
    if os.path.exists(PERMANENT_CACHE_FILE):
        try:
            with open(PERMANENT_CACHE_FILE, encoding='utf-8') as f:
                cache_data = json.load(f)
                articles_by_topic = cache_data.get("articles", {})

                # Clean and limit articles on startup to reduce memory
                original_count = sum(len(v) for v in articles_by_topic.values())
                articles_by_topic = clean_old_articles(articles_by_topic, days_to_keep=30)
                articles_by_topic = limit_articles_per_topic(articles_by_topic, max_per_topic=50)
                final_count = sum(len(v) for v in articles_by_topic.values())

                article_cache["articles"] = articles_by_topic
                last_updated_str = cache_data.get("last_fetched")
                if last_updated_str:
                    last_updated = datetime.fromisoformat(last_updated_str)
                else:
                    last_updated = datetime.now()
            logging.info(f"✅ Loaded {final_count} cached articles from permanent JSON (cleaned {original_count - final_count} old/excess articles)")
        except Exception as e:
            logging.error(f"❌ Failed to load permanent cache JSON: {e}")
    elif os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding='utf-8') as f:
                articles_by_topic = json.load(f)

                # Clean and limit articles
                original_count = sum(len(v) for v in articles_by_topic.values())
                articles_by_topic = clean_old_articles(articles_by_topic, days_to_keep=30)
                articles_by_topic = limit_articles_per_topic(articles_by_topic, max_per_topic=50)
                final_count = sum(len(v) for v in articles_by_topic.values())

                last_updated = datetime.now()
            logging.info(f"✅ Loaded {final_count} cached articles from static JSON (cleaned {original_count - final_count} old/excess articles)")
        except Exception as e:
            logging.error(f"❌ Failed to load cache JSON: {e}")
    else:
        logging.warning("⚠️  Cache JSON not found. Will serve empty articles.")

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Initialize database
    db.init_app(app)

    with app.app_context():
        try:
            logging.info("🔌 Attempting to connect to database...")
            db.create_all()
            init_topics()

            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            logging.info(f"✅ Database initialized successfully with {len(table_names)} tables: {', '.join(table_names)}")

        except Exception as e:
            logging.error(f"❌ Error initializing database: {e}")
            logging.error(f"Database URI being used: {app.config.get('SQLALCHEMY_DATABASE_URI', 'NOT SET')[:50]}...")

    # Register blueprints
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    # Register template filters
    @app.template_filter("md5_hash")
    def md5_hash_filter(text):
        """Generate MD5 hash for template use"""
        return hashlib.md5(str(text).encode('utf-8')).hexdigest()[:8]

    @app.template_filter("format_datetime")
    def format_datetime_filter(iso_string):
        try:
            if isinstance(iso_string, str):
                dt = datetime.fromisoformat(iso_string)
            else:
                dt = iso_string

            now = datetime.utcnow()
            diff = now - dt

            if diff.days < 1:
                hours = diff.seconds // 3600
                minutes = (diff.seconds % 3600) // 60

                if hours > 0:
                    return f"{hours} hour{'s' if hours > 1 else ''} ago"
                elif minutes > 0:
                    return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
                else:
                    return "Just now"

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
    def index():
        """Serves the main page with flat mixed feed of positive news articles."""
        global articles_by_topic
        global last_updated

        # Reload cache if needed
        try:
            if os.path.exists(PERMANENT_CACHE_FILE):
                with open(PERMANENT_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    articles_by_topic = cache_data.get("articles", {})
                    last_updated_str = cache_data.get("last_fetched")
                    if last_updated_str:
                        last_updated = datetime.fromisoformat(last_updated_str)
        except Exception as e:
            logging.warning(f"Error loading cache file: {e}")

        # Get parameters
        selected_topic = request.args.get('topic')
        sort_type = request.args.get('sort', 'top')
        time_filter = request.args.get('time', 'all')

        # Pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = 24  # Divisible by 3 for clean grid layout (8 rows of 3)

        if not articles_by_topic:
            articles_by_topic = article_cache.get("articles", {})
            logging.warning("Using in-memory article_cache as fallback.")

        # Apply user preferences if logged in
        min_inspiration_score = None
        if current_user.is_authenticated:
            min_inspiration_score = current_user.min_inspiration_score

        # Flatten and sort articles based on sort_type
        if sort_type == 'latest':
            all_articles = flatten_articles(
                articles_by_topic,
                sort_by_inspiration=False,
                min_score=min_inspiration_score
            )
            logging.info("Sorting articles by newest first")
        else:  # 'top' or default
            all_articles = flatten_articles(
                articles_by_topic,
                sort_by_inspiration=True,
                min_score=min_inspiration_score
            )
            logging.info("Sorting articles by inspiration score (top)")

        # Apply time filter
        if time_filter != 'all':
            now = datetime.utcnow()
            filtered_by_time = []

            for article in all_articles:
                pub_date = article.get('_published_dt', datetime.utcnow())

                if time_filter == 'today':
                    if (now - pub_date).days < 1:
                        filtered_by_time.append(article)
                elif time_filter == 'week':
                    if (now - pub_date).days < 7:
                        filtered_by_time.append(article)
                elif time_filter == 'month':
                    if (now - pub_date).days < 30:
                        filtered_by_time.append(article)

            all_articles = filtered_by_time
            logging.info(f"Filtered to {len(all_articles)} articles from {time_filter}")

        # Filter by topic if specified
        if selected_topic:
            filtered_articles = []
            for article in all_articles:
                if article.get('topic_name', '').lower() == selected_topic.lower():
                    filtered_articles.append(article)
            all_articles = filtered_articles

        # Filter by user's favorite topics if logged in
        elif current_user.is_authenticated and not selected_topic and current_user.favorite_topics:
            if len(all_articles) > 10:
                favorite_topic_names = [topic.name for topic in current_user.favorite_topics]
                top_stories = all_articles[:4]
                favorite_articles = [a for a in all_articles[4:] if a.get('topic_name', '') in favorite_topic_names]

                if len(favorite_articles) >= 8:
                    all_articles = top_stories + favorite_articles
                else:
                    other_articles = [a for a in all_articles[4:] if
                                      a.get('topic_name', '') not in favorite_topic_names]
                    supplemental_count = max(8 - len(favorite_articles), 0)
                    all_articles = top_stories + favorite_articles + other_articles[:supplemental_count]

        # Filter hero article: ensure first article is suitable for hero position
        if all_articles and not selected_topic:  # Only apply hero filter on main feed
            if not is_suitable_for_hero(all_articles[0]):
                # Find first suitable article for hero
                hero_candidate = None
                for i, article in enumerate(all_articles[1:], start=1):
                    if is_suitable_for_hero(article):
                        hero_candidate = article
                        hero_index = i
                        break

                # If we found a better hero, move it to position 0
                if hero_candidate:
                    all_articles = [hero_candidate] + all_articles[:hero_index] + all_articles[hero_index+1:]
                    logging.info(f"Promoted better hero: '{hero_candidate.get('title', '')}'")

        # Process articles for display
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
            # Add article ID and slug for internal linking
            article['article_id'] = generate_article_id(article['link'])
            article['article_slug'] = generate_article_slug(article['title'])

        # Get unique topics
        unique_topics = list(articles_by_topic.keys())
        unique_topics.sort()

        # Get topic icons
        topic_icons = {}
        for topic, articles_list in articles_by_topic.items():
            if articles_list and 'topic_icon_path' in articles_list[0]:
                topic_icons[topic] = articles_list[0]['topic_icon_path']

        if 'Business' not in topic_icons:
            topic_icons['Business'] = '/openmoji/color/svg/1F4BC.svg'

        topic_icons['all news'] = '/openmoji/color/svg/1F4F0.svg'

        # Calculate pagination
        total_articles = len(all_articles)
        total_pages = (total_articles + per_page - 1) // per_page  # Ceiling division
        page = max(1, min(page, total_pages)) if total_pages > 0 else 1  # Clamp page number

        # Slice articles for current page
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_articles = all_articles[start_idx:end_idx]

        # Get today's quote
        daily_quote = get_daily_quote()

        # Get editor's picks (top 5 articles marked as editor's picks)
        editors_picks = [a for a in all_articles if a.get('is_editors_pick', False)][:5]

        return render_template(
            "index.html",
            articles=paginated_articles,
            topics=unique_topics,
            topic_icons=topic_icons,
            selected_topic=selected_topic,
            sort=sort_type,
            time_filter=time_filter,
            last_updated=last_updated,
            page=page,
            total_pages=total_pages,
            total_articles=total_articles,
            daily_quote=daily_quote,
            editors_picks=editors_picks
        )

    @app.route("/article/<article_id>")
    def article_detail(article_id):
        """Display individual article page - supports both legacy IDs and SEO slugs.

        Legacy URL: /article/a1b2c3d4e5f6 (MD5 hash)
        SEO URL: /article/inspiring-story-about-kindness (slug)

        For legacy IDs, redirects to SEO URL.
        """
        global articles_by_topic

        # Reload cache if needed
        try:
            if os.path.exists(PERMANENT_CACHE_FILE):
                with open(PERMANENT_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    articles_by_topic = cache_data.get("articles", {})
        except Exception as e:
            logging.warning(f"Error loading cache file: {e}")

        if not articles_by_topic:
            articles_by_topic = article_cache.get("articles", {})

        # Find the article by ID or slug
        all_articles = flatten_articles(articles_by_topic, sort_by_inspiration=True)

        target_article = None
        is_legacy_id = False

        # Check if this is a legacy MD5 ID (16 hex characters)
        if len(article_id) == 16 and all(c in '0123456789abcdef' for c in article_id):
            is_legacy_id = True
            # Find article by legacy ID
            for article in all_articles:
                current_id = generate_article_id(article['link'])
                if current_id == article_id:
                    target_article = article
                    break
        else:
            # Find article by slug
            for article in all_articles:
                article_slug = generate_article_slug(article['title'])
                if article_slug == article_id:
                    target_article = article
                    break

        if not target_article:
            return "Article not found", 404

        # If accessed via legacy ID, redirect to SEO-friendly slug URL
        if is_legacy_id:
            new_slug = generate_article_slug(target_article['title'])
            return redirect(url_for('article_detail', article_id=new_slug), code=301)

        # Get related articles from the same topic
        related_articles = []
        topic_name = target_article.get('topic_name', '')

        for article in all_articles:
            if article['link'] != target_article['link']:
                if article.get('topic_name', '') == topic_name:
                    related_articles.append(article)
                    if len(related_articles) >= 6:
                        break

        # If not enough from same topic, add from other topics
        if len(related_articles) < 6:
            for article in all_articles:
                if article['link'] != target_article['link'] and article not in related_articles:
                    related_articles.append(article)
                    if len(related_articles) >= 6:
                        break

        # Generate article IDs and slugs for related articles
        for article in related_articles:
            article['article_id'] = generate_article_id(article['link'])
            article['article_slug'] = generate_article_slug(article['title'])

        # Generate "Why It Matters" section if not cached
        if 'why_it_matters' not in target_article or not target_article['why_it_matters']:
            target_article['why_it_matters'] = generate_why_it_matters(
                target_article.get('title', ''),
                target_article.get('summary', ''),
                target_article.get('topic_name', 'General')
            )
            # TODO: Cache this back to permanent storage to avoid regenerating
            logging.info(f"Generated new 'Why It Matters' for: {target_article.get('title', '')[:50]}")

        # Get daily quote
        daily_quote = get_daily_quote()

        return render_template(
            'article.html',
            article=target_article,
            related_articles=related_articles,
            daily_quote=daily_quote,
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

    @app.route("/masonry")
    def masonry_test():
        """Masonry layout with same logic as index()"""
        global articles_by_topic
        global last_updated

        # Reload cache if needed
        try:
            if os.path.exists(PERMANENT_CACHE_FILE):
                with open(PERMANENT_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    articles_by_topic = cache_data.get("articles", {})
                    last_updated_str = cache_data.get("last_fetched")
                    if last_updated_str:
                        last_updated = datetime.fromisoformat(last_updated_str)
        except Exception as e:
            logging.warning(f"Error loading cache file: {e}")

        # Get parameters
        selected_topic = request.args.get('topic')
        sort_type = request.args.get('sort', 'top')
        time_filter = request.args.get('time', 'all')

        if not articles_by_topic:
            articles_by_topic = article_cache.get("articles", {})
            logging.warning("Using in-memory article_cache as fallback.")

        # Apply user preferences if logged in
        min_inspiration_score = None
        if current_user.is_authenticated:
            min_inspiration_score = current_user.min_inspiration_score

        # Flatten and sort articles
        if sort_type == 'latest':
            all_articles = flatten_articles(
                articles_by_topic,
                sort_by_inspiration=False,
                min_score=min_inspiration_score
            )
            logging.info("Sorting articles by newest first")
        else:  # 'top' or default
            all_articles = flatten_articles(
                articles_by_topic,
                sort_by_inspiration=True,
                min_score=min_inspiration_score
            )
            logging.info("Sorting articles by inspiration score (top)")

        # Apply time filter
        if time_filter != 'all':
            now = datetime.utcnow()
            filtered_by_time = []

            for article in all_articles:
                pub_date = article.get('_published_dt', datetime.utcnow())

                if time_filter == 'today':
                    if (now - pub_date).days < 1:
                        filtered_by_time.append(article)
                elif time_filter == 'week':
                    if (now - pub_date).days < 7:
                        filtered_by_time.append(article)
                elif time_filter == 'month':
                    if (now - pub_date).days < 30:
                        filtered_by_time.append(article)

            all_articles = filtered_by_time
            logging.info(f"Filtered to {len(all_articles)} articles from {time_filter}")

        # Filter by topic if specified
        if selected_topic:
            filtered_articles = []
            for article in all_articles:
                if article.get('topic_name', '').lower() == selected_topic.lower():
                    filtered_articles.append(article)
            all_articles = filtered_articles

        # Filter by user's favorite topics if logged in
        elif current_user.is_authenticated and not selected_topic and current_user.favorite_topics:
            if len(all_articles) > 10:
                favorite_topic_names = [topic.name for topic in current_user.favorite_topics]
                top_stories = all_articles[:4]
                favorite_articles = [a for a in all_articles[4:] if a.get('topic_name', '') in favorite_topic_names]

                if len(favorite_articles) >= 8:
                    all_articles = top_stories + favorite_articles
                else:
                    other_articles = [a for a in all_articles[4:] if
                                      a.get('topic_name', '') not in favorite_topic_names]
                    supplemental_count = max(8 - len(favorite_articles), 0)
                    all_articles = top_stories + favorite_articles + other_articles[:supplemental_count]

        # Process articles for display
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
            # Add article ID and slug for internal linking
            article['article_id'] = generate_article_id(article['link'])
            article['article_slug'] = generate_article_slug(article['title'])

        # Get unique topics
        unique_topics = list(articles_by_topic.keys())
        unique_topics.sort()

        # Get topic icons
        topic_icons = {}
        for topic, articles_list in articles_by_topic.items():
            if articles_list and 'topic_icon_path' in articles_list[0]:
                topic_icons[topic] = articles_list[0]['topic_icon_path']

        if 'Business' not in topic_icons:
            topic_icons['Business'] = '/openmoji/color/svg/1F4BC.svg'

        topic_icons['all news'] = '/openmoji/color/svg/1F4F0.svg'

        return render_template(
            "index_masonry.html",
            articles=all_articles,
            topics=unique_topics,
            topic_icons=topic_icons,
            selected_topic=selected_topic,
            sort=sort_type,
            time_filter=time_filter,
            last_updated=last_updated
        )

    @app.route("/warm")
    def warm_test():
        """Test warm design by calling existing index function"""
        return index()

    @app.route('/ads.txt')
    def ads_txt():
        """Serve ads.txt file for Google AdSense."""
        try:
            response = send_file(
                'static/ads.txt',
                mimetype='text/plain',
                as_attachment=False
            )
            # Set cache headers (Flask 2.x compatible)
            response.cache_control.max_age = 86400  # 24 hours
            return response
        except FileNotFoundError:
            return "File not found", 404

    @app.route('/robots.txt')
    def robots_txt():
        """Serve robots.txt for search engine crawlers."""
        robots_content = """User-agent: *
    Allow: /
    Disallow: /admin/
    Disallow: /api/
    Sitemap: https://peanutlife.com/sitemap.xml
    """
        return robots_content, 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.route('/sitemap.xml')
    def sitemap():
        """Generate dynamic sitemap for search engines with all articles."""
        from flask import Response
        global articles_by_topic

        # Reload cache if needed
        try:
            if os.path.exists(PERMANENT_CACHE_FILE):
                with open(PERMANENT_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    articles_by_topic = cache_data.get("articles", {})
        except Exception as e:
            logging.warning(f"Error loading cache for sitemap: {e}")

        if not articles_by_topic:
            articles_by_topic = article_cache.get("articles", {})

        # Get all articles
        all_articles = flatten_articles(articles_by_topic, sort_by_inspiration=True)

        # Start building sitemap XML
        sitemap_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://peanutlife.com/</loc>
        <changefreq>hourly</changefreq>
        <priority>1.0</priority>
        <lastmod>''' + datetime.utcnow().strftime('%Y-%m-%d') + '''</lastmod>
    </url>
    <url>
        <loc>https://peanutlife.com/auth/signup</loc>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>
    <url>
        <loc>https://peanutlife.com/auth/subscribe</loc>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>'''

        # Add all unique topics
        unique_topics = list(articles_by_topic.keys())
        for topic in unique_topics:
            sitemap_xml += f'''
    <url>
        <loc>https://peanutlife.com/?topic={topic}</loc>
        <changefreq>daily</changefreq>
        <priority>0.8</priority>
    </url>'''

        # Add all article pages (limit to most recent 1000 for sitemap size)
        for article in all_articles[:1000]:
            article_slug = generate_article_slug(article['title'])
            article_date = article.get('published', datetime.utcnow().isoformat())

            # Parse the date and format it
            try:
                if isinstance(article_date, str):
                    pub_date = datetime.fromisoformat(article_date)
                else:
                    pub_date = article_date
                lastmod = pub_date.strftime('%Y-%m-%d')
            except:
                lastmod = datetime.utcnow().strftime('%Y-%m-%d')

            sitemap_xml += f'''
    <url>
        <loc>https://peanutlife.com/article/{article_slug}</loc>
        <lastmod>{lastmod}</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.6</priority>
    </url>'''

        sitemap_xml += '''
</urlset>'''

        return Response(sitemap_xml, mimetype='application/xml')

    return app


if __name__ == "__main__":
    # Create and initialize app
    app = create_app()

    # Get environment and port
    env = os.environ.get('FLASK_ENV', 'production')
    port = int(os.environ.get("PORT", 5005))

    # Refresh cache immediately on startup in production (ensures fresh articles after deploy)
    if env == 'production':
        logging.info("🔄 Refreshing cache synchronously on startup (blocking until complete)...")
        try:
            refresh_cache_worker()  # Run synchronously, not in thread
            logging.info("✅ Startup cache refresh completed successfully")
        except Exception as e:
            logging.error(f"❌ Startup cache refresh failed: {e}")

    # Start the background cache refresh thread
    initial_delay = 60 if env == 'production' else 20
    start_background_refresh(initial_delay=initial_delay, interval=86400)

    # Log startup info
    logging.info("=" * 60)
    logging.info(f"🌟 Project Optimist News Starting")
    logging.info(f"🌐 Environment: {env}")
    logging.info(f"🔌 Port: {port}")
    logging.info(f"🔄 Cache refresh: every 24 hours (starts in {initial_delay}s)")
    logging.info("=" * 60)

    # Run with appropriate settings
    app.run(
        host="0.0.0.0",
        port=port,
        debug=(env == 'development')
    )