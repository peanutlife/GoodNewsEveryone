# -*- coding: utf-8 -*-
"""Aggregates and filters news articles from RSS feeds."""

import feedparser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import re
import time
from datetime import datetime

# Import configuration and data from shared_data
from src.shared_data import FEED_URLS, NEGATIVE_KEYWORDS, POSITIVE_THRESHOLD, removed_article_links, load_removed_articles

# Ensure VADER lexicon is downloaded (should have been done externally)
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except nltk.downloader.DownloadError:
    print("VADER lexicon not found. Please download it first.")
    # In a real application, you might trigger the download here or exit
    # nltk.download("vader_lexicon")

sid = SentimentIntensityAnalyzer()

# --- Functions ---

def contains_negative_keyword(text):
    """Checks if the text contains any negative keywords."""
    if not text:
        return False
    text_lower = text.lower()
    for keyword in NEGATIVE_KEYWORDS:
        # Use word boundaries to avoid matching parts of words (e.g., "election" in "selection")
        if re.search(r"\b" + re.escape(keyword) + r"\b", text_lower):
            return True
    return False

def get_positive_sentiment_score(text):
    """Gets the VADER compound sentiment score."""
    if not text:
        return 0.0
    return sid.polarity_scores(text)["compound"]

def parse_date(entry):
    """Attempts to parse the publication date from various possible fields."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(time.mktime(entry.published_parsed))
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime.fromtimestamp(time.mktime(entry.updated_parsed))
    # Add more fallbacks if needed based on feed specifics
    return datetime.now() # Fallback to current time

def fetch_and_filter_feeds(feed_urls):
    """Fetches articles from RSS feeds and filters for positive news, excluding removed articles."""
    positive_articles = []
    # Ensure the removed list is up-to-date before fetching (in case it changed)
    # Note: In a multi-process/threaded environment, this might need more robust handling
    load_removed_articles() 

    for url in feed_urls:
        print(f"Fetching feed: {url}")
        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                print(f"  Warning: Feed may be ill-formed. {feed.bozo_exception}")
            
            for entry in feed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", "")) # Fallback to description
                pub_date = parse_date(entry)

                # Basic validation
                if not title or not link:
                    continue

                # 0. Check if article was manually removed
                if link in removed_article_links:
                    # print(f"  Skipping (manually removed): {title}")
                    continue

                # 1. Keyword Filtering (Title and Summary)
                if contains_negative_keyword(title) or contains_negative_keyword(summary):
                    # print(f"  Skipping (keyword): {title}")
                    continue

                # 2. Sentiment Analysis (Title and Summary)
                combined_text = title + ". " + summary
                combined_sentiment = get_positive_sentiment_score(combined_text)

                if combined_sentiment > POSITIVE_THRESHOLD:
                    # print(f"  Keeping (sentiment {combined_sentiment:.2f}): {title}")
                    positive_articles.append({
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "published": pub_date.isoformat(), # Store as ISO string
                        "source_feed": url,
                        "sentiment_score": combined_sentiment
                    })
                # else:
                    # print(f"  Skipping (sentiment {combined_sentiment:.2f}): {title}")

        except Exception as e:
            print(f"  Error fetching or parsing feed {url}: {e}")
            continue # Skip this feed on error

    # Sort articles by publication date (newest first)
    positive_articles.sort(key=lambda x: x["published"], reverse=True)

    return positive_articles

# --- Main Execution (for testing) ---
if __name__ == "__main__":
    print("Starting news aggregation and filtering...")
    # Now uses FEED_URLS imported from shared_data
    filtered_news = fetch_and_filter_feeds(FEED_URLS)
    print(f"\nFound {len(filtered_news)} positive articles (after filtering removed).")

    # Print titles of the first few articles
    for i, article in enumerate(filtered_news[:10]):
        print(f"  {i+1}. {article['title']} (Score: {article['sentiment_score']:.2f})")

    # In the Flask app, this function would be called, 
    # and the results stored in a database or cache.

