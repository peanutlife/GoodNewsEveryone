# aggregator.py

import feedparser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import re
import time
from datetime import datetime
import os
import csv  # ADD THIS

from src.shared_data import FEED_URLS, NEGATIVE_KEYWORDS, POSITIVE_THRESHOLD, removed_article_links, load_removed_articles

# Load OpenMoji CSV and build topic-icon map
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
CSV_PATH = os.path.join(STATIC_DIR, 'openmoji.csv')

TOPICS = ["science", "technology", "travel", "health", "culture", "environment", "sports", "kids", "teens", "good news"]

topic_icon_map = {}

with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        annotation = row['annotation'].lower()
        hexcode = row['hexcode']
        for topic in TOPICS:
            if topic in annotation and topic not in topic_icon_map:
                topic_icon_map[topic] = hexcode

print("[INFO] Topic to emoji map:", topic_icon_map)
fallback_icons = {
    'science': '1F52C',      # microscope
    'technology': '1F4BB',   # laptop
    'travel': '2708',        # airplane
    'culture': '1F3A4',      # microphone
    'environment': '1F333',  # tree
    'teens': '1F9D1',        # person
    'kids': '1F476',         # baby
    'good news': '1F389',     # party popper
    'general': '1F4A1'        # 💡 light bulb
}
for topic, hexcode in fallback_icons.items():
    if topic not in topic_icon_map:
        topic_icon_map[topic] = hexcode

print("[INFO] FINAL topic to emoji map:", topic_icon_map)


# Ensure NLTK
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except nltk.downloader.DownloadError:
    print("VADER lexicon not found. Please download it first.")

sid = SentimentIntensityAnalyzer()

POSITIVE_KEYWORDS = [
    "inspiring", "uplifting", "hope", "wins", "victory", "healing", "cured", "saved",
    "rescued", "restored", "joy", "optimistic", "donated", "scholarship", "breakthrough",
    "innovation", "milestone", "record", "achievement", "honored", "recognition", "award",
    "volunteer", "community", "success", "progress", "peace", "hero", "kindness", "good samaritan"
]

DEFAULT_SOURCE_ICON = "icons/source_default.png"
DEFAULT_TOPIC_ICON = "icons/topic_default.png"

TOPIC_KEYWORDS = {
    "technology": ["tech", "ai", "software", "hardware", "internet", "gadget", "crypto", "cyber"],
    "science": ["science", "research", "space", "nasa", "physics", "biology", "chemistry", "discovery"],
    "culture": ["art", "music", "film", "book", "theatre", "museum", "culture", "heritage"],
    "travel": ["travel", "tourism", "destination", "holiday", "vacation", "hotel", "flight"],
    "sports": ["sport", "football", "soccer", "basketball", "tennis", "olympic", "judo", "cricket"],
    "business": ["business", "finance", "market", "stock", "economy", "company", "trade"],
    "health": ["health", "medical", "medicine", "doctor", "hospital", "wellness", "disease", "virus", "hair"],
    "environment": ["environment", "climate", "nature", "wildlife", "pollution", "conservation", "bird"],
    "teens": ["teen", "youth", "student", "high school", "college", "young adult"],
    "kids": ["kids", "children", "child", "preschool", "elementary", "nursery"]
}

def get_topic_and_icon(title, summary):
    text_lower = (title + " " + summary).lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text_lower):
                # 🎉 Check if OpenMoji hexcode exists
                emoji_hex = topic_icon_map.get(topic)
                emoji_path = f"/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
                return topic, emoji_path
    # fallback
    emoji_hex = topic_icon_map.get("good news")
    emoji_path = f"/static/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
    return "general", emoji_path

def contains_negative_keyword(text):
    if not text: return False
    text_lower = text.lower()
    return any(re.search(r"\b" + re.escape(keyword) + r"\b", text_lower) for keyword in NEGATIVE_KEYWORDS)

def contains_positive_keyword(text):
    if not text: return False
    text_lower = text.lower()
    return any(re.search(r"\b" + re.escape(keyword) + r"\b", text_lower) for keyword in POSITIVE_KEYWORDS)

def get_positive_sentiment_score(text):
    if not text: return 0.0
    return sid.polarity_scores(text)["compound"]

def parse_date(entry):
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(time.mktime(entry.published_parsed))
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime.fromtimestamp(time.mktime(entry.updated_parsed))
    return datetime.now()

def fetch_and_filter_feeds(feed_urls):
    articles_by_topic = {}
    load_removed_articles()

    for url in feed_urls:
        print(f"Fetching feed: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                print(f"Warning: Feed may be ill-formed. {feed.bozo_exception}")
            for entry in feed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))
                pub_date = parse_date(entry)

                if not title or not link: continue
                if link in removed_article_links: continue
                if contains_negative_keyword(title) or contains_negative_keyword(summary): continue

                combined_text = title + ". " + summary
                combined_sentiment = get_positive_sentiment_score(combined_text)

                if combined_sentiment > POSITIVE_THRESHOLD or contains_positive_keyword(combined_text):
                    topic_name, emoji_icon_path = get_topic_and_icon(title, summary)
                    article = {
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "published": pub_date.isoformat(),
                        "sentiment_score": combined_sentiment,
                        "source_name": url.split("/")[2],
                        "source_icon_path": DEFAULT_SOURCE_ICON,
                        "topic_name": topic_name,
                        "topic_icon_path": emoji_icon_path,
                        "noun_icon_url": emoji_icon_path,  # ✅ reuse emoji icon
                        "noun_icon_attr": "OpenMoji license CC BY-SA 4.0"  # attribution
                    }
                    if topic_name not in articles_by_topic:
                        articles_by_topic[topic_name] = []
                    articles_by_topic[topic_name].append(article)
        except Exception as e:
            print(f"Error fetching/parsing feed {url}: {e}")
            continue

    for topic in articles_by_topic:
        articles_by_topic[topic].sort(key=lambda x: x["published"], reverse=True)

    return articles_by_topic

if __name__ == "__main__":
    print("Starting news aggregation...")
    topic_articles = fetch_and_filter_feeds(FEED_URLS)
    for topic, articles in topic_articles.items():
        print(f"\n--- {topic.upper()} ({len(articles)} articles) ---")
        for i, article in enumerate(articles[:5]):
            print(f"{i+1}. {article['title']} (Sentiment: {article['sentiment_score']:.2f})")
