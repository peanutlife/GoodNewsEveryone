# add_tags_to_cache.py
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Now import
from aggregator import classify_article_tags

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
CACHE_FILE = os.path.join(DATA_DIR, 'article_cache.json')

print("🔧 Adding tags to existing cached articles...")

try:
    # Load the cache
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)
    
    articles_by_topic = cache_data.get('articles', {})
    
    # Count articles
    total_articles = sum(len(articles) for articles in articles_by_topic.values())
    print(f"📊 Found {total_articles} articles in cache")
    
    # Add tags to each article
    articles_updated = 0
    for topic, articles in articles_by_topic.items():
        for article in articles:
            if 'tags' not in article or not article['tags']:
                # Add tags
                article['tags'] = classify_article_tags(article)
                articles_updated += 1
                
                # Show progress
                if articles_updated % 10 == 0:
                    print(f"   Processed {articles_updated} articles...")
    
    print(f"✅ Added tags to {articles_updated} articles")
    
    # Save back to cache
    cache_data['articles'] = articles_by_topic
    
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Updated cache saved to {CACHE_FILE}")
    print("🎉 Done! Refresh your browser to see the tags.")
    
    # Show some examples
    print("\n📋 Sample tagged articles:")
    count = 0
    for topic, articles in articles_by_topic.items():
        for article in articles:
            if article.get('tags'):
                count += 1
                print(f"\n   {count}. {article['title'][:60]}...")
                print(f"      Tags: {', '.join([t['name'] for t in article['tags']])}")
                if count >= 3:
                    break
        if count >= 3:
            break
    
except FileNotFoundError:
    print(f"❌ Cache file not found at {CACHE_FILE}")
    print(f"   Looking for: {CACHE_FILE}")
    print(f"   Current directory: {os.getcwd()}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
