import os
import sys
import json
import re
import hashlib
from datetime import datetime

# ✅ Ensure parent directory in sys.path so we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.aggregator import fetch_and_filter_feeds
from src.shared_data import FEED_URLS

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

print("🟢 Bootstrapping article cache...")

# Fetch articles
articles_by_topic = fetch_and_filter_feeds(FEED_URLS)
total_articles_before = sum(len(articles) for articles in articles_by_topic.values())
print(f"📊 Fetched {total_articles_before} articles across {len(articles_by_topic)} topics.")

# Remove duplicates
deduplicated_articles = deduplicate_articles(articles_by_topic)
total_articles_after = sum(len(articles) for articles in deduplicated_articles.values())
print(f"📊 After deduplication: {total_articles_after} unique articles")

# Prepare cache JSON
cache_data = {
    "last_fetched": datetime.utcnow().isoformat(),
    "articles": deduplicated_articles
}

# ✅ Save to /data/article_cache.json
data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(data_dir, exist_ok=True)  # Create data dir if missing
cache_file_path = os.path.join(data_dir, "article_cache.json")
with open(cache_file_path, "w", encoding="utf-8") as f:
    json.dump(cache_data, f, ensure_ascii=False, indent=2)
print(f"🎉 Article cache saved to {cache_file_path}")
