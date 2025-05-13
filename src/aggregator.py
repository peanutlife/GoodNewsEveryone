# aggregator.py

import feedparser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import re
import time
from datetime import datetime
import os
import csv
import json
import openai
import logging
from src.shared_data import FEED_URLS, NEGATIVE_KEYWORDS, POSITIVE_THRESHOLD, removed_article_links, load_removed_articles
from urllib.parse import urlparse

# Import configuration for secure API key management
from src.config import config

# Setup logging
logger = logging.getLogger(__name__)

# Load OpenAI API Key securely
try:
    # Get the current configuration based on environment
    current_config = config[os.environ.get('FLASK_ENV', 'default')]

    # Access the API key from configuration
    OPENAI_API_KEY = current_config.OPENAI_API_KEY

    if not OPENAI_API_KEY:
        logger.error("OpenAI API key not found in configuration. Some features may not work.")

    # Initialize OpenAI client with API key
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

except Exception as e:
    logger.error(f"Error initializing OpenAI client: {e}")
    # Create a dummy client for graceful failure
    class DummyClient:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                logger.error("OpenAI client not properly initialized. Operation failed.")
                return None
            return method
    client = DummyClient()

# Load OpenMoji CSV and build topic-icon map
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
CSV_PATH = os.path.join(STATIC_DIR, 'openmoji.csv')

TOPICS = ["science", "technology", "travel", "business", "health", "culture", "environment", "sports", "kids", "teens", "good news"]

topic_icon_map = {}
try:
    with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            annotation = row['annotation'].lower()
            hexcode = row['hexcode']
            for topic in TOPICS:
                if topic in annotation and topic not in topic_icon_map:
                    topic_icon_map[topic] = hexcode

    # Fallback emojis if missing
    fallback_icons = {
        'science': '1F52C', 'technology': '1F4BB', 'travel': '2708',
        'culture': '1F3A4', 'environment': '1F333', 'teens': '1F9D1',
        'kids': '1F476', 'good news': '1F389', 'general': '1F4A1',
        'Business': '1F4BC',  # Briefcase emoji
        'all news': '1F4F0'   # Newspaper emoji
    }
    for topic, hexcode in fallback_icons.items():
        if topic not in topic_icon_map:
            topic_icon_map[topic] = hexcode

    logger.info(f"Loaded topic to emoji map: {topic_icon_map}")
except Exception as e:
    logger.error(f"Error loading emoji CSV: {e}")
    # Set default icons if CSV loading fails
    topic_icon_map = {
        'science': '1F52C', 'technology': '1F4BB', 'travel': '2708',
        'culture': '1F3A4', 'environment': '1F333', 'teens': '1F9D1',
        'kids': '1F476', 'good news': '1F389', 'general': '1F4A1'
    }

# NLTK setup
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon")

sid = SentimentIntensityAnalyzer()

# ENHANCED: More comprehensive positive keywords list
POSITIVE_KEYWORDS = [
    # Achievement-related
    "achievement", "award", "breakthrough", "discovery", "honor", "milestone", "record", "success", "victory", "wins",

    # Community & Social impact
    "charitable", "community", "cooperation", "diversity", "donation", "equity", "generosity", "inclusion", "kindness", "nonprofit",
    "philanthropy", "together", "unity", "volunteer", "welfare",

    # Emotional wellbeing
    "happiness", "healing", "hope", "joy", "optimism", "peace", "positive", "resilience", "smile", "strength", "uplifting",

    # Innovation & Growth
    "advancement", "development", "growth", "improvement", "innovation", "invention", "progress", "solution", "upgrade",

    # Transformation & Rescue
    "cured", "overcame", "recovery", "rescued", "restored", "reunion", "revival", "saved", "transformed", "turnaround",

    # Human interest
    "amazing", "beautiful", "celebrated", "good samaritan", "hero", "inspiring", "remarkable", "surprise", "touching", "wonderful"
]

DEFAULT_SOURCE_ICON = "icons/source_default.png"

TOPIC_KEYWORDS = {
    "technology": ["tech", "ai", "artificial intelligence", "software", "hardware", "internet", "gadget", "crypto", "cyber", "digital", "robot", "app", "innovation", "computer", "programming", "algorithm", "startup", "automation"],
    "science": ["science", "research", "space", "nasa", "physics", "biology", "chemistry", "discovery", "experiment", "laboratory", "scientific", "astronomy", "quantum", "molecular", "genetics", "study", "theory", "dinosaur"],
    "culture": ["art", "music", "film", "book", "theatre", "theater", "museum", "culture", "heritage", "festival", "concert", "exhibition", "performance", "literature", "dance", "painting", "sculpture", "poetry", "artist"],
    "travel": ["travel", "tourism", "destination", "holiday", "vacation", "hotel", "flight", "resort", "trip", "adventure", "explore", "journey", "tourist", "sightseeing", "cruise", "expedition", "backpacking", "wanderlust"],
    "sports": ["sport", "football", "soccer", "basketball", "tennis", "olympic", "athlete", "championship", "tournament", "game", "match", "player", "team", "coach", "victory", "medal", "fitness", "marathon", "cricket"],
    "business": ["business", "finance", "market", "stock", "economy", "company", "trade", "entrepreneur", "investment", "startup", "commerce", "industry", "corporate", "enterprise", "profit", "revenue", "leadership"],
    "health": ["health", "medical", "medicine", "doctor", "hospital", "wellness", "fitness", "nutrition", "diet", "exercise", "therapy", "mental health", "healthcare", "treatment", "healing", "recovery", "mindfulness"],
    "environment": ["environment", "climate", "nature", "wildlife", "pollution", "conservation", "sustainability", "renewable", "biodiversity", "ecosystem", "green", "recycle", "planet", "earth", "forest", "ocean", "bird", "animal"],
    "teens": ["teen", "youth", "student", "high school", "college", "young adult", "adolescent", "education", "learning", "academic", "university", "campus", "graduate", "scholarship", "career", "internship"],
    "kids": ["kids", "children", "child", "preschool", "elementary", "nursery", "baby", "toddler", "family", "parenting", "play", "toy", "childhood", "learning", "school", "birthday", "little ones"]
}

def classify_with_llm(text):
    """Ask GPT if article is positive and inspiring - Compatibility function"""
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key not available. Skipping LLM classification.")
        return False

    try:
        prompt = f"Is this news article positive and inspiring? Respond with only Yes or No.\n\nArticle:\n{text}"
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3,
            temperature=0
        )
        answer = response.choices[0].message.content.strip().lower()
        return answer == "yes"
    except Exception as e:
        logger.error(f"LLM Classification Error: {e}")
        return False

# Enhanced inspiration classification with more dimensions of analysis
def classify_inspiration_with_llm(text):
    """Use LLM to classify if an article is inspirational or just positive"""
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key not available. Skipping LLM inspiration classification.")
        return False

    try:
        prompt = (
            "Analyze this news article to determine if it is TRULY INSPIRATIONAL. "
            "An inspirational article should have at least one of the following qualities:\n"
            "1. Contains a story of personal or collective triumph over adversity\n"
            "2. Showcases exceptional kindness, compassion, or humanity\n"
            "3. Presents an innovative solution to a significant problem\n"
            "4. Documents a meaningful achievement that could inspire others\n"
            "5. Presents a compelling vision for positive change\n\n"
            "Respond only with YES (truly inspirational) or NO (merely positive or neutral).\n\n"
            f"Article:\n{text}"
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0
        )
        answer = response.choices[0].message.content.strip().lower()
        return answer == "yes"
    except Exception as e:
        logger.error(f"LLM Inspiration Error: {e}")
        return False

# Enhanced method for scoring inspirational qualities
def score_inspiration_with_llm(text):
    """Ask LLM to score article on different inspirational dimensions"""
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key not available. Returning default inspiration score.")
        return {'composite': 5}

    try:
        prompt = (
            "Rate this news article on the following dimensions from 1-10:\n\n"
            "1) EMOTIONAL IMPACT: Does it evoke positive emotions like hope, joy, or admiration? (1=No emotion, 10=Powerful emotional impact)\n"
            "2) TRIUMPH OVER ADVERSITY: Does it show people overcoming significant challenges? (1=No adversity narrative, 10=Extraordinary triumph)\n"
            "3) SOCIAL BENEFIT: Does it describe actions that help communities or society? (1=No social impact, 10=Major positive social impact)\n"
            "4) NOVELTY & INNOVATION: Does it present new ideas or approaches to problems? (1=Nothing novel, 10=Groundbreaking innovation)\n"
            "5) ACTIONABILITY: Does it offer ideas readers could apply in their own lives? (1=Not actionable, 10=Highly actionable)\n\n"
            "For each dimension, respond with ONLY a number between 1-10.\n"
            "Format your response exactly like this example:\n"
            "Emotional: 7\n"
            "Triumph: 8\n"
            "Social: 6\n"
            "Novelty: 9\n"
            "Actionable: 5\n\n"
            f"Article:\n{text}"
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=75,
            temperature=0
        )
        answer = response.choices[0].message.content.strip()

        # Parse the scores from the response
        scores = {}
        for line in answer.split('\n'):
            if ':' in line:
                dimension, value = line.split(':')
                try:
                    score = int(value.strip())
                    scores[dimension.strip().lower()] = min(max(score, 1), 10)  # Ensure between 1-10
                except (ValueError, AttributeError):
                    pass

        # Calculate weighted composite score if we got all dimensions
        if len(scores) >= 5:
            # Weight factors for each dimension - customize these based on what matters most
            weights = {
                'emotional': 0.25,
                'triumph': 0.25,
                'social': 0.2,
                'novelty': 0.15,
                'actionable': 0.15
            }

            composite_score = 0
            for dim, weight in weights.items():
                if dim in scores:
                    composite_score += scores[dim] * weight

            # Normalize to ensure it's between 1-10
            composite_score = round(composite_score, 1)
            scores['composite'] = composite_score

            # Store all dimension scores for potential UI display
            return scores
        else:
            # Fallback if parsing failed
            return {'composite': 5}

    except Exception as e:
        logger.error(f"LLM Scoring Error: {e}")
        return {'composite': 5}  # Default mid-range score

def get_topic_and_icon(title, summary):
    text_lower = (title + " " + summary).lower()
    topic_scores = {}

    # Calculate topic scores based on keyword matches
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            # Match whole words only
            matches = re.findall(r"\b" + re.escape(keyword) + r"\b", text_lower)
            score += len(matches)
        topic_scores[topic] = score

    # Get topic with highest score
    if any(topic_scores.values()):
        # Find topic with highest score
        best_topic = max(topic_scores.items(), key=lambda x: x[1])[0]
        emoji_hex = topic_icon_map.get(best_topic)
        emoji_path = f"/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
        return best_topic, emoji_path

    # Default to general/good news if no topics match
    emoji_hex = topic_icon_map.get("good news")
    emoji_path = f"/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
    return "general", emoji_path

def contains_negative_keyword(text):
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()) for kw in NEGATIVE_KEYWORDS) if text else False

def contains_positive_keyword(text):
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()) for kw in POSITIVE_KEYWORDS) if text else False

def get_positive_sentiment_score(text):
    return sid.polarity_scores(text)["compound"] if text else 0.0

def parse_date(entry):
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(time.mktime(entry.published_parsed))
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime.fromtimestamp(time.mktime(entry.updated_parsed))
    return datetime.now()

def fetch_and_filter_feeds(feed_urls):
    """
    Fetch RSS feeds incrementally, updating the cache after each feed.
    """
    articles_by_topic = {}
    load_removed_articles()

    # First, try to load existing cache to build upon
    try:
        STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
        CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                articles_by_topic = json.load(f)
                logger.info(f"Loaded existing cache with {sum(len(v) for v in articles_by_topic.values())} articles")
    except Exception as e:
        logger.warning(f"Could not load existing cache: {e}")
        articles_by_topic = {}

    # Keep track of how many new articles we've added
    new_articles_count = 0

    # Process feeds one by one
    for url_index, url in enumerate(feed_urls):
        logger.info(f"Fetching feed {url_index+1}/{len(feed_urls)}: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                logger.warning(f"Feed may be ill-formed. {feed.bozo_exception}")

            # Track new articles from this feed
            feed_new_count = 0

            for entry in feed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))
                pub_date = parse_date(entry)

                if not title or not link:
                    continue
                if link in removed_article_links:
                    continue
                if contains_negative_keyword(title) or contains_negative_keyword(summary):
                    continue

                combined_text = f"{title}. {summary}"
                sentiment_score = get_positive_sentiment_score(combined_text)
                is_positive = sentiment_score > POSITIVE_THRESHOLD or contains_positive_keyword(combined_text)
                llm_positive = classify_with_llm(combined_text)

                if is_positive and llm_positive:
                    topic_name, emoji_icon_path = get_topic_and_icon(title, summary)

                    # Get inspiration score from LLM
                    inspiration_score = score_inspiration_with_llm(combined_text)

                    # Enhanced image extraction (more robust)
                    image_url = None

                    # Try multiple sources for images in priority order
                    if 'media_content' in entry and entry.media_content:
                        # Try to find the largest image in media_content
                        best_media = None
                        best_width = 0

                        for media in entry.media_content:
                            # Some feeds include width/height attributes
                            width = media.get('width', 0)
                            if isinstance(width, str):
                                try:
                                    width = int(width)
                                except ValueError:
                                    width = 0

                            # If this media has a larger width or we haven't found any yet
                            if width > best_width or best_media is None:
                                if 'url' in media:
                                    best_media = media
                                    best_width = width

                        if best_media:
                            image_url = best_media.get('url')

                    # If no media_content with URL, try media_thumbnail
                    if not image_url and 'media_thumbnail' in entry and entry.media_thumbnail:
                        if 'url' in entry.media_thumbnail[0]:
                            image_url = entry.media_thumbnail[0].get('url')

                    # If still no image, try to extract from HTML content
                    if not image_url:
                        content_fields = ['content', 'description', 'summary']

                        for field in content_fields:
                            if hasattr(entry, field) and getattr(entry, field):
                                # Look for <img> tags
                                content = getattr(entry, field)
                                if isinstance(content, list) and len(content) > 0:
                                    content = content[0].get('value', '')

                                img_matches = re.findall(r'<img\s+[^>]*src="([^"]+)"[^>]*>', str(content))
                                if img_matches:
                                    # Skip tiny images often used as tracking pixels
                                    for img in img_matches:
                                        # Skip small tracking images and icons
                                        if any(x in img.lower() for x in ['icon', 'pixel', 'tracker', 'tracking', '1x1', 'badge']):
                                            continue
                                        # Skip image URLs with dimensions in them that are too small
                                        if re.search(r'([_-])(\d+)x(\d+)([_.-])', img):
                                            dims = re.search(r'([_-])(\d+)x(\d+)([_.-])', img)
                                            width, height = int(dims.group(2)), int(dims.group(3))
                                            if width < 100 or height < 100:
                                                continue
                                        image_url = img
                                        break
                                if image_url:
                                    break

                    # If still no image, use domain-based dynamic placeholder
                    if not image_url:
                        domain = urlparse(link).netloc
                        # Create a consistent hash from the domain for color selection
                        import hashlib
                        domain_hash = int(hashlib.md5(domain.encode()).hexdigest(), 16)

                        # Generate a color based on the domain hash
                        hue = domain_hash % 360

                        # Create a fallback placeholder that's better than favicons
                        domain_placeholder = f"/static/placeholders/{topic_name.lower()}.jpg"
                        if os.path.exists(os.path.join(STATIC_DIR, domain_placeholder.lstrip('/'))):
                            image_url = domain_placeholder
                        else:
                            # Use generic placeholder or domain favicon as last resort
                            image_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

                    article = {
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "published": pub_date.isoformat(),
                        "sentiment_score": sentiment_score,
                        "inspiration_score": inspiration_score.get('composite', 5) if isinstance(inspiration_score, dict) else 5,
                        "inspiration_dimensions": inspiration_score if isinstance(inspiration_score, dict) else {'composite': 5},
                        "is_inspirational": True,  # Flag for truly inspirational content
                        "source_name": urlparse(url).netloc,
                        "source_feed": url,  # Store the source feed URL
                        "source_icon_path": DEFAULT_SOURCE_ICON,
                        "topic_name": topic_name,
                        "topic_icon_path": emoji_icon_path,
                        "noun_icon_url": emoji_icon_path,
                        "noun_icon_attr": "OpenMoji license CC BY-SA 4.0",
                        "image_url": image_url
                    }

                    # Initialize the topic if needed
                    if topic_name not in articles_by_topic:
                        articles_by_topic[topic_name] = []

                    # Skip if this article link already exists in this topic
                    if any(a["link"] == link for a in articles_by_topic[topic_name]):
                        continue

                    # Add the article
                    articles_by_topic[topic_name].append(article)
                    feed_new_count += 1
                    new_articles_count += 1

            logger.info(f"Added {feed_new_count} new articles from {url}")

            # Sort all articles by inspiration score in this topic
            for topic in articles_by_topic:
                articles_by_topic[topic].sort(key=lambda x: (x.get("is_inspirational", False),
                                                           x.get("inspiration_score", 5),
                                                           x.get("published", "")), reverse=True)

            # Save cache incrementally after each feed
            if feed_new_count > 0:
                try:
                    STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
                    CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
                    os.makedirs(STATIC_DIR, exist_ok=True)

                    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                        json.dump(articles_by_topic, f, ensure_ascii=False, indent=2)
                    logger.info(f"Incrementally updated cache with {feed_new_count} new articles ({sum(len(v) for v in articles_by_topic.values())} total)")
                except Exception as e:
                    logger.error(f"Failed to write incremental cache: {e}")

        except Exception as e:
            logger.error(f"Error fetching/parsing feed {url}: {e}")

    # Final save to JSON cache
    STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
    CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
    os.makedirs(STATIC_DIR, exist_ok=True)

    try:
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(articles_by_topic, f, ensure_ascii=False, indent=2)
        logger.info(f"Completed fetch with {new_articles_count} new articles, total: {sum(len(v) for v in articles_by_topic.values())}")
    except Exception as e:
        logger.error(f"Failed to write final cache: {e}")

    return articles_by_topic


if __name__ == "__main__":
    # Setup console logging for direct script execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Starting news aggregation...")
    topic_articles = fetch_and_filter_feeds(FEED_URLS)
    for topic, articles in topic_articles.items():
        print(f"\n--- {topic.upper()} ({len(articles)} articles) ---")
        for i, article in enumerate(articles[:5]):
            print(f"{i+1}. {article['title']} (Sentiment: {article['sentiment_score']:.2f}, Inspiration: {article['inspiration_score']}, Truly Inspirational: {article.get('is_inspirational', False)})")
