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
import hashlib
from src.shared_data import FEED_URLS, NEGATIVE_KEYWORDS, POSITIVE_THRESHOLD, removed_article_links, \
    load_removed_articles
from urllib.parse import urlparse

# Import configuration for secure API key management
from src.config import config

# Setup logging
logger = logging.getLogger(__name__)

# Load OpenAI API Key securely
try:
    current_config = config[os.environ.get('FLASK_ENV', 'default')]
    OPENAI_API_KEY = current_config.OPENAI_API_KEY

    if not OPENAI_API_KEY:
        logger.error("OpenAI API key not found in configuration. Some features may not work.")

    client = openai.OpenAI(api_key=OPENAI_API_KEY)

except Exception as e:
    logger.error(f"Error initializing OpenAI client: {e}")


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

# Updated TOPICS list for adults
TOPICS = [
    "science", "technology", "business", "health", "environment",
    "personal_growth", "social_impact", "culture", "travel",
    "relationships", "sports", "general"
]

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
        'science': '1F52C',  # Microscope
        'technology': '1F4BB',  # Laptop
        'business': '1F4BC',  # Briefcase
        'health': '1F9E0',  # Brain
        'environment': '1F333',  # Tree
        'personal_growth': '1F4AA',  # Flexed bicep
        'social_impact': '1F91D',  # Handshake
        'culture': '1F3A8',  # Artist palette
        'travel': '2708',  # Airplane
        'relationships': '1F46B',  # Two people
        'sports': '26BD',  # Soccer ball
        'general': '1F4A1',  # Light bulb
        'good news': '1F389'  # Party popper
    }

    for topic, hexcode in fallback_icons.items():
        if topic not in topic_icon_map:
            topic_icon_map[topic] = hexcode

    logger.info(f"Loaded topic to emoji map: {topic_icon_map}")
except Exception as e:
    logger.error(f"Error loading emoji CSV: {e}")
    topic_icon_map = {
        'science': '1F52C', 'technology': '1F4BB', 'business': '1F4BC',
        'health': '1F9E0', 'environment': '1F333', 'culture': '1F3A8',
        'travel': '2708', 'sports': '26BD', 'general': '1F4A1'
    }

# NLTK setup
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon")

sid = SentimentIntensityAnalyzer()

# Positive keywords
POSITIVE_KEYWORDS = [
    "achievement", "award", "breakthrough", "discovery", "honor", "milestone", "record", "success", "victory", "wins",
    "charitable", "community", "cooperation", "diversity", "donation", "equity", "generosity", "inclusion", "kindness",
    "nonprofit",
    "philanthropy", "together", "unity", "volunteer", "welfare",
    "happiness", "healing", "hope", "joy", "optimism", "peace", "positive", "resilience", "smile", "strength",
    "uplifting",
    "advancement", "development", "growth", "improvement", "innovation", "invention", "progress", "solution", "upgrade",
    "cured", "overcame", "recovery", "rescued", "restored", "reunion", "revival", "saved", "transformed", "turnaround",
    "amazing", "beautiful", "celebrated", "good samaritan", "hero", "inspiring", "remarkable", "surprise", "touching",
    "wonderful"
]

DEFAULT_SOURCE_ICON = "icons/source_default.png"

# Topic keywords for adult-focused content
TOPIC_KEYWORDS = {
    "technology": ["tech", "ai", "artificial intelligence", "software", "startup", "innovation", "digital", "crypto",
                   "blockchain", "app", "programming", "gadget", "smartphone", "computer"],

    "science": ["science", "research", "space", "nasa", "physics", "biology", "discovery", "study", "breakthrough",
                "scientific", "astronomy", "climate", "medical research"],

    "business": ["business", "entrepreneur", "startup", "company", "market", "investment", "success story", "career",
                 "leadership", "innovation", "growth", "revenue", "ipo", "venture capital"],

    "health": ["health", "wellness", "fitness", "mental health", "meditation", "nutrition", "exercise", "therapy",
               "mindfulness", "wellbeing", "recovery", "breakthrough treatment"],

    "environment": ["environment", "climate solution", "sustainability", "renewable energy", "conservation",
                    "green technology", "solar", "wind power", "electric vehicle", "carbon neutral", "recycling"],

    "personal_growth": ["motivation", "inspiration", "personal development", "achievement", "success", "goal",
                        "mindset", "productivity", "habits", "self-improvement", "overcome", "transformation"],

    "social_impact": ["community", "charity", "volunteer", "nonprofit", "social good", "donation", "helping",
                      "kindness", "philanthropy", "activism", "change maker", "impact"],

    "culture": ["art", "music", "film", "book", "culture", "creative", "artist", "performance", "exhibition", "theater",
                "design", "photography"],

    "travel": ["travel", "destination", "adventure", "tourism", "explore", "journey", "vacation", "wanderlust",
               "discovery", "cultural exchange"],

    "relationships": ["relationship", "marriage", "friendship", "family", "connection", "love", "support", "community",
                      "belonging", "human interest"],

    "sports": ["sport", "athlete", "championship", "victory", "record", "comeback", "perseverance", "team",
               "competition", "fitness achievement"],
}


def classify_article_tags(article):
    """
    Classify article with multiple descriptive tags based on content analysis
    Returns list of tags - more precise matching
    """
    try:
        title = article.get('title', '').lower()
        summary = article.get('summary', '').lower()
        combined = f"{title} {summary}"
        topic = article.get('topic_name', '').lower()

        tags = []

        # More specific matching with context
        # Emotional Impact Tags - require stronger signals
        heartwarming_words = ['heartwarming', 'touching story', 'brought tears', 'emotional reunion', 'moved to tears']
        if any(phrase in combined for phrase in heartwarming_words):
            tags.append({'name': 'Heartwarming', 'color': '#e76f51', 'icon': '💝'})

        uplifting_words = ['uplifting', 'gives hope', 'hopeful', 'silver lining', 'bright future', 'positive outlook',
                           'reason to smile']
        if any(phrase in combined for phrase in uplifting_words):
            tags.append({'name': 'Uplifting', 'color': '#f4a261', 'icon': '🌟'})

        motivating_words = ['inspiring', 'motivating', 'never gave up', 'perseverance', 'overcame odds',
                            'against all odds', 'defied expectations', 'triumph']
        if any(phrase in combined for phrase in motivating_words):
            tags.append({'name': 'Motivating', 'color': '#2a9d8f', 'icon': '💪'})

        calming_words = ['meditation', 'mindfulness practice', 'peaceful', 'tranquil', 'serene', 'relaxation']
        if any(phrase in combined for phrase in calming_words) and 'health' in topic:
            tags.append({'name': 'Calming', 'color': '#457b9d', 'icon': '🧘'})

        # Achievement Tags - more specific
        breakthrough_words = ['breakthrough', 'scientific discovery', 'groundbreaking', 'first time ever',
                              'world first', 'unprecedented', 'revolutionary']
        if any(phrase in combined for phrase in breakthrough_words):
            tags.append({'name': 'Breakthrough', 'color': '#8338ec', 'icon': '💡'})

        success_words = ['success story', 'achieved dream', 'reached milestone', 'accomplished goal',
                         'dreams come true', 'made it']
        if any(phrase in combined for phrase in success_words):
            tags.append({'name': 'Success Story', 'color': '#06a77d', 'icon': '🏆'})

        # Social Impact Tags - require community context
        community_words = ['community came together', 'neighbors helped', 'village rallied', 'town united',
                           'collective effort', 'community project']
        if any(phrase in combined for phrase in community_words):
            tags.append({'name': 'Community', 'color': '#ff006e', 'icon': '🤝'})

        kindness_words = ['act of kindness', 'good samaritan', 'hero saved', 'rescued', 'selfless act',
                          'helped stranger', 'paid it forward']
        if any(phrase in combined for phrase in kindness_words):
            tags.append({'name': 'Acts of Kindness', 'color': '#fb5607', 'icon': '❤️'})

        # Theme-specific Tags - check topic context
        if 'health' in topic or 'wellness' in topic:
            health_words = ['medical breakthrough', 'new treatment', 'cure', 'healing', 'health recovery',
                            'patients benefited']
            if any(phrase in combined for phrase in health_words):
                tags.append({'name': 'Health Innovation', 'color': '#06a77d', 'icon': '🩺'})

        mental_health_words = ['mental health breakthrough', 'therapy success', 'depression treatment',
                               'anxiety relief', 'mental wellness']
        if any(phrase in combined for phrase in mental_health_words):
            tags.append({'name': 'Mental Health', 'color': '#7209b7', 'icon': '🧠'})

        if 'environment' in topic:
            eco_words = ['environmental victory', 'climate solution', 'saved ecosystem',
                         'renewable energy breakthrough', 'carbon neutral', 'restored habitat']
            if any(phrase in combined for phrase in eco_words):
                tags.append({'name': 'Eco-Friendly', 'color': '#52b788', 'icon': '🌱'})

        education_words = ['education breakthrough', 'learning revolution', 'scholarship program', 'students excelled',
                           'teaching innovation']
        if any(phrase in combined for phrase in education_words):
            tags.append({'name': 'Educational', 'color': '#4361ee', 'icon': '📚'})

        # Problem-solving tags
        solution_words = ['solution to', 'solved problem', 'innovative approach', 'new way to', 'game-changing']
        if any(phrase in combined for phrase in solution_words):
            tags.append({'name': 'Problem Solver', 'color': '#f72585', 'icon': '✅'})

        # If we have no tags but high inspiration score, be more lenient
        if not tags and article.get('inspiration_score', 0) >= 8:
            # Look for simpler positive indicators
            if any(word in combined for word in ['inspiring', 'amazing', 'incredible', 'extraordinary', 'remarkable']):
                tags.append({'name': 'Inspiring', 'color': '#e76f51', 'icon': '⭐'})

        # Remove duplicates while preserving order
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag['name'] not in seen:
                seen.add(tag['name'])
                unique_tags.append(tag)

        # Limit to 2 most relevant tags (cleaner UI)
        return unique_tags[:2]

    except Exception as e:
        logger.error(f"Error classifying tags: {e}")
        return []


def classify_with_llm(text):
    """
    Ask GPT if article is positive and inspiring
    DISABLED: Using VADER sentiment only to avoid rate limits
    """
    # Temporarily disabled - rate limit exceeded
    # Use VADER sentiment + keyword matching instead
    return True  # Let articles through if they pass VADER checks


def score_inspiration_with_llm(text):
    """Heuristic scoring based on sentiment + keywords"""
    from nltk.sentiment.vader import SentimentIntensityAnalyzer

    score = 5  # Base score
    text_lower = text.lower()

    # Get VADER sentiment
    sid = SentimentIntensityAnalyzer()
    sentiment = sid.polarity_scores(text)
    compound = sentiment['compound']

    # Base score from sentiment (0-10 scale)
    score = 5 + (compound * 5)  # compound is -1 to 1, scale to 0-10

    # Boost for high-impact keywords
    high_impact_words = ['breakthrough', 'triumph', 'overcame', 'hero', 'saved', 'rescued']
    high_matches = sum(1 for word in high_impact_words if word in text_lower)
    score += high_matches * 1.0

    # Cap at 10
    score = min(10, max(1, score))

    return {
        'composite': round(score, 1),
        'emotional': round(score, 1),
        'triumph': round(score, 1),
        'social': round(score, 1),
        'novelty': round(score, 1),
        'actionable': round(score, 1)
    }

# def classify_with_llm(text):
#     """Ask GPT if article is positive and inspiring"""
#     if not OPENAI_API_KEY:
#         logger.warning("OpenAI API key not available. Skipping LLM classification.")
#         return False
#
#     try:
#         prompt = f"Is this news article positive, uplifting, or inspiring? Respond with only Yes or No.\n\nArticle:\n{text[:500]}"
#         response = client.chat.completions.create(
#             model="gpt-3.5-turbo",
#             messages=[{"role": "user", "content": prompt}],
#             max_tokens=3,
#             temperature=0
#         )
#         answer = response.choices[0].message.content.strip().lower()
#         return answer == "yes"
#     except Exception as e:
#         logger.error(f"LLM Classification Error: {e}")
#         return False


# def score_inspiration_with_llm(text):
#     """Ask LLM to score article on different inspirational dimensions"""
#     if not OPENAI_API_KEY:
#         logger.warning("OpenAI API key not available. Returning default inspiration score.")
#         return {'composite': 5}
#
#     try:
#         prompt = (
#             "Rate this news article on the following dimensions from 1-10:\n\n"
#             "1) EMOTIONAL IMPACT: Does it evoke positive emotions like hope, joy, or admiration? (1=No emotion, 10=Powerful emotional impact)\n"
#             "2) TRIUMPH OVER ADVERSITY: Does it show people overcoming significant challenges? (1=No adversity narrative, 10=Extraordinary triumph)\n"
#             "3) SOCIAL BENEFIT: Does it describe actions that help communities or society? (1=No social impact, 10=Major positive social impact)\n"
#             "4) NOVELTY & INNOVATION: Does it present new ideas or approaches to problems? (1=Nothing novel, 10=Groundbreaking innovation)\n"
#             "5) ACTIONABILITY: Does it offer ideas readers could apply in their own lives? (1=Not actionable, 10=Highly actionable)\n\n"
#             "For each dimension, respond with ONLY a number between 1-10.\n"
#             "Format your response exactly like this example:\n"
#             "Emotional: 7\n"
#             "Triumph: 8\n"
#             "Social: 6\n"
#             "Novelty: 9\n"
#             "Actionable: 5\n\n"
#             f"Article:\n{text}"
#         )
#         response = client.chat.completions.create(
#             model="gpt-3.5-turbo",
#             messages=[{"role": "user", "content": prompt}],
#             max_tokens=75,
#             temperature=0
#         )
#         answer = response.choices[0].message.content.strip()
#
#         # Parse the scores
#         scores = {}
#         for line in answer.split('\n'):
#             if ':' in line:
#                 dimension, value = line.split(':')
#                 try:
#                     score = int(value.strip())
#                     scores[dimension.strip().lower()] = min(max(score, 1), 10)
#                 except (ValueError, AttributeError):
#                     pass
#
#         # Calculate weighted composite score
#         if len(scores) >= 5:
#             weights = {
#                 'emotional': 0.25,
#                 'triumph': 0.25,
#                 'social': 0.2,
#                 'novelty': 0.15,
#                 'actionable': 0.15
#             }
#
#             composite_score = 0
#             for dim, weight in weights.items():
#                 if dim in scores:
#                     composite_score += scores[dim] * weight
#
#             composite_score = round(composite_score, 1)
#             scores['composite'] = composite_score
#             return scores
#         else:
#             return {'composite': 5}
#
#     except Exception as e:
#         logger.error(f"LLM Scoring Error: {e}")
#         return {'composite': 5}


def get_topic_and_icon(title, summary):
    """Determine topic based on keyword matching"""
    text_lower = (title + " " + summary).lower()
    topic_scores = {}

    for topic, keywords in TOPIC_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            matches = re.findall(r"\b" + re.escape(keyword) + r"\b", text_lower)
            score += len(matches)
        topic_scores[topic] = score

    if any(topic_scores.values()):
        best_topic = max(topic_scores.items(), key=lambda x: x[1])[0]
        emoji_hex = topic_icon_map.get(best_topic)
        emoji_path = f"/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
        return best_topic, emoji_path

    emoji_hex = topic_icon_map.get("good news")
    emoji_path = f"/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
    return "general", emoji_path


def contains_negative_keyword(text):
    """Check if text contains negative keywords"""
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()) for kw in NEGATIVE_KEYWORDS) if text else False


def contains_positive_keyword(text):
    """Check if text contains positive keywords"""
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()) for kw in POSITIVE_KEYWORDS) if text else False


def get_positive_sentiment_score(text):
    """Get sentiment score using VADER"""
    return sid.polarity_scores(text)["compound"] if text else 0.0


def parse_date(entry):
    """Parse date from feed entry"""
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

    # Try to load existing cache
    try:
        CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                articles_by_topic = json.load(f)
                logger.info(f"Loaded existing cache with {sum(len(v) for v in articles_by_topic.values())} articles")
    except Exception as e:
        logger.warning(f"Could not load existing cache: {e}")
        articles_by_topic = {}

    new_articles_count = 0

    # Process feeds one by one
    for url_index, url in enumerate(feed_urls):
        logger.info(f"Fetching feed {url_index + 1}/{len(feed_urls)}: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                logger.warning(f"Feed may be ill-formed. {feed.bozo_exception}")

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
                    inspiration_score = score_inspiration_with_llm(combined_text)

                    # Enhanced image extraction
                    image_url = None

                    if 'media_content' in entry and entry.media_content:
                        best_media = None
                        best_width = 0
                        for media in entry.media_content:
                            width = media.get('width', 0)
                            if isinstance(width, str):
                                try:
                                    width = int(width)
                                except ValueError:
                                    width = 0
                            if width > best_width or best_media is None:
                                if 'url' in media:
                                    best_media = media
                                    best_width = width
                        if best_media:
                            image_url = best_media.get('url')

                    if not image_url and 'media_thumbnail' in entry and entry.media_thumbnail:
                        if 'url' in entry.media_thumbnail[0]:
                            image_url = entry.media_thumbnail[0].get('url')

                    if not image_url:
                        content_fields = ['content', 'description', 'summary']
                        for field in content_fields:
                            if hasattr(entry, field) and getattr(entry, field):
                                content = getattr(entry, field)
                                if isinstance(content, list) and len(content) > 0:
                                    content = content[0].get('value', '')
                                img_matches = re.findall(r'<img\s+[^>]*src="([^"]+)"[^>]*>', str(content))
                                if img_matches:
                                    for img in img_matches:
                                        if any(x in img.lower() for x in
                                               ['icon', 'pixel', 'tracker', 'tracking', '1x1', 'badge']):
                                            continue
                                        if re.search(r'([_-])(\d+)x(\d+)([_.-])', img):
                                            dims = re.search(r'([_-])(\d+)x(\d+)([_.-])', img)
                                            width, height = int(dims.group(2)), int(dims.group(3))
                                            if width < 100 or height < 100:
                                                continue
                                        image_url = img
                                        break
                                if image_url:
                                    break

                    if not image_url:
                        domain = urlparse(link).netloc
                        domain_placeholder = f"/static/placeholders/{topic_name.lower()}.jpg"
                        if os.path.exists(os.path.join(STATIC_DIR, domain_placeholder.lstrip('/'))):
                            image_url = domain_placeholder
                        else:
                            image_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

                    # Create article dictionary
                    article = {
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "published": pub_date.isoformat(),
                        "sentiment_score": sentiment_score,
                        "inspiration_score": inspiration_score.get('composite', 5) if isinstance(inspiration_score,
                                                                                                 dict) else 5,
                        "inspiration_dimensions": inspiration_score if isinstance(inspiration_score, dict) else {
                            'composite': 5},
                        "is_inspirational": True,
                        "source_name": urlparse(url).netloc,
                        "source_feed": url,
                        "source_icon_path": DEFAULT_SOURCE_ICON,
                        "topic_name": topic_name,
                        "topic_icon_path": emoji_icon_path,
                        "noun_icon_url": emoji_icon_path,
                        "noun_icon_attr": "OpenMoji license CC BY-SA 4.0",
                        "image_url": image_url
                    }

                    # Add tags after article is fully created
                    article['tags'] = classify_article_tags(article)

                    # Initialize topic if needed
                    if topic_name not in articles_by_topic:
                        articles_by_topic[topic_name] = []

                    # Skip if article already exists
                    if any(a["link"] == link for a in articles_by_topic[topic_name]):
                        continue

                    # Add article
                    articles_by_topic[topic_name].append(article)
                    feed_new_count += 1
                    new_articles_count += 1

            logger.info(f"Added {feed_new_count} new articles from {url}")

            # Sort articles by inspiration score
            for topic in articles_by_topic:
                articles_by_topic[topic].sort(
                    key=lambda x: (
                        x.get("is_inspirational", False),
                        x.get("inspiration_score", 5),
                        x.get("published", "")
                    ),
                    reverse=True
                )

            # Save cache incrementally
            if feed_new_count > 0:
                try:
                    CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
                    os.makedirs(STATIC_DIR, exist_ok=True)
                    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                        json.dump(articles_by_topic, f, ensure_ascii=False, indent=2)
                    logger.info(
                        f"Incrementally updated cache ({sum(len(v) for v in articles_by_topic.values())} total)")
                except Exception as e:
                    logger.error(f"Failed to write incremental cache: {e}")

        except Exception as e:
            logger.error(f"Error fetching/parsing feed {url}: {e}")

    # Final save
    CACHE_PATH = os.path.join(STATIC_DIR, 'articles_cache.json')
    try:
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(articles_by_topic, f, ensure_ascii=False, indent=2)
        logger.info(
            f"Completed fetch with {new_articles_count} new articles, total: {sum(len(v) for v in articles_by_topic.values())}")
    except Exception as e:
        logger.error(f"Failed to write final cache: {e}")

    return articles_by_topic


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Starting news aggregation...")
    topic_articles = fetch_and_filter_feeds(FEED_URLS)
    for topic, articles in topic_articles.items():
        print(f"\n--- {topic.upper()} ({len(articles)} articles) ---")
        for i, article in enumerate(articles[:5]):
            print(
                f"{i + 1}. {article['title']} (Sentiment: {article['sentiment_score']:.2f}, Inspiration: {article['inspiration_score']}, Tags: {len(article.get('tags', []))})")