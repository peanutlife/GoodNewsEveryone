# -*- coding: utf-8 -*-
"""Shared data and configuration for the BrightSide News app."""

import os
from datetime import datetime
import threading

# --- Constants ---
BASE_DIR = os.path.dirname(__file__)
FEEDS_FILE_PATH = os.path.join(BASE_DIR, "feeds.txt")
REMOVED_ARTICLES_FILE_PATH = os.path.join(BASE_DIR, "removed_articles.txt")

# --- Thread Lock for File Access ---
# Simple lock to prevent race conditions if multiple threads access files
# (e.g., web requests and background fetcher in a more complex setup)
file_lock = threading.Lock()

# --- Dynamic Data ---

# Cache for articles (simple in-memory cache)
article_cache = {
    "articles": [],
    "last_fetched": None
}

# Set to store removed article links for quick lookup
removed_article_links = set()

# --- Configuration ---

# Cache duration
CACHE_DURATION_SECONDS = 15 * 60 # Fetch new articles every 15 minutes

# Sentiment threshold (VADER compound score)
# Increased threshold to filter for more clearly positive articles
POSITIVE_THRESHOLD = 0.80 # Articles must have a compound score > this value (was 0.05)

# Keywords to filter out (case-insensitive)
NEGATIVE_KEYWORDS = [
    "politics", "political", "election", "vote", "government", "parliament", "congress",
    "sex", "sexual", "abuse", "assault",
    "crime", "murder", "killed", "death", "dead", "shooting", "stabbed", "violence", "violent", "arrest", "police", "theft", "robbery", "fraud",
    "stock market", "shares", "dow jones", "nasdaq", "finance", "economy", "economic", "recession", "inflation", "tariff",
    "war", "conflict", "military", "attack", "bombing", "invasion",
    "disaster", "crash", "crisis", "emergency",
    "protest", "riot",
    "scandal",
    # Add more as needed
]

# --- Functions for Dynamic Config & Data ---

def get_feed_urls():
    """Reads the list of feed URLs from the feeds file."""
    with file_lock:
        try:
            with open(FEEDS_FILE_PATH, "r") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            return urls
        except FileNotFoundError:
            print(f"Warning: Feeds file not found at {FEEDS_FILE_PATH}. Returning empty list.")
            return []

def save_feed_urls(urls):
    """Saves the list of feed URLs to the feeds file."""
    with file_lock:
        try:
            with open(FEEDS_FILE_PATH, "w") as f:
                for url in urls:
                    f.write(url + "\n")
            # Update the global variable after saving
            global FEED_URLS
            FEED_URLS = urls
            return True
        except IOError as e:
            print(f"Error saving feeds file at {FEEDS_FILE_PATH}: {e}")
            return False

def load_removed_articles():
    """Loads removed article links from the file into the set."""
    global removed_article_links
    with file_lock:
        try:
            with open(REMOVED_ARTICLES_FILE_PATH, "r") as f:
                removed_article_links = {line.strip() for line in f if line.strip()}
            print(f"Loaded {len(removed_article_links)} removed article links.")
        except FileNotFoundError:
            print(f"Removed articles file not found at {REMOVED_ARTICLES_FILE_PATH}. Initializing empty set.")
            removed_article_links = set()

def add_removed_article_link(link):
    """Adds an article link to the removed list file and set."""
    global removed_article_links
    link = link.strip()
    if not link or link in removed_article_links:
        return False # Already removed or empty link

    with file_lock:
        try:
            with open(REMOVED_ARTICLES_FILE_PATH, "a") as f:
                f.write(link + "\n")
            removed_article_links.add(link)
            # Corrected print statement (avoiding multiline f-string issues)
            print(f"Added '{link}' to removed articles list.")
            return True
        except IOError as e:
            print(f"Error adding to removed articles file at {REMOVED_ARTICLES_FILE_PATH}: {e}")
            return False

# --- Initial Load ---
FEED_URLS = get_feed_urls()
load_removed_articles()
