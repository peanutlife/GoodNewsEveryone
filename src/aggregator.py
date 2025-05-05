# aggregator.py

import feedparser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import re
import time
from datetime import datetime
import os
import csv
import openai
from src.shared_data import FEED_URLS, NEGATIVE_KEYWORDS, POSITIVE_THRESHOLD, removed_article_links, load_removed_articles

# Load OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

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

# Fallback emojis if missing
fallback_icons = {
    'science': '1F52C', 'technology': '1F4BB', 'travel': '2708',
    'culture': '1F3A4', 'environment': '1F333', 'teens': '1F9D1',
    'kids': '1F476', 'good news': '1F389', 'general': '1F4A1'
}
for topic, hexcode in fallback_icons.items():
    if topic not in topic_icon_map:
        topic_icon_map[topic] = hexcode

print("[INFO] FINAL topic to emoji map:", topic_icon_map)

# NLTK setup
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon")

sid = SentimentIntensityAnalyzer()

POSITIVE_KEYWORDS = [
    "inspiring", "uplifting", "hope", "wins", "victory", "healing", "cured",
    "saved", "rescued", "restored", "joy", "optimistic", "donated",
    "scholarship", "breakthrough", "innovation", "milestone", "record",
    "achievement", "honored", "recognition", "award", "volunteer", "community",
    "success", "progress", "peace", "hero", "kindness", "good samaritan"
]

DEFAULT_SOURCE_ICON = "icons/source_default.png"

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

def classify_with_llm(text):
    """Ask GPT if article is positive and inspiring"""
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
        print(f"[LLM Error]: {e}")
        return False

def get_topic_and_icon(title, summary):
    text_lower = (title + " " + summary).lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text_lower):
                emoji_hex = topic_icon_map.get(topic)
                emoji_path = f"/openmoji/color/svg/{emoji_hex}.svg" if emoji_hex else None
                return topic, emoji_path
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

                combined_text = f"{title}. {summary}"
                sentiment_score = get_positive_sentiment_score(combined_text)
                is_positive = sentiment_score > POSITIVE_THRESHOLD or contains_positive_keyword(combined_text)
                llm_positive = classify_with_llm(combined_text)

                if is_positive and llm_positive:
                    topic_name, emoji_icon_path = get_topic_and_icon(title, summary)
                    article = {
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "published": pub_date.isoformat(),
                        "sentiment_score": sentiment_score,
                        "source_name": url.split("/")[2],
                        "source_icon_path": DEFAULT_SOURCE_ICON,
                        "topic_name": topic_name,
                        "topic_icon_path": emoji_icon_path,
                        "noun_icon_url": emoji_icon_path,
                        "noun_icon_attr": "OpenMoji license CC BY-SA 4.0"
                    }
                    articles_by_topic.setdefault(topic_name, []).append(article)
        except Exception as e:
            print(f"Error fetching/parsing feed {url}: {e}")

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
