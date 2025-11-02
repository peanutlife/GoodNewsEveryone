# retag_cache.py - save in src/ folder
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from aggregator import classify_article_tags

cache_file = '../data/article_cache.json'

with open(cache_file, 'r') as f:
    data = json.load(f)

articles_by_topic = data.get('articles', {})

for topic, articles in articles_by_topic.items():
    for article in articles:
        article['tags'] = classify_article_tags(article)

data['articles'] = articles_by_topic

with open(cache_file, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("✅ Re-tagged all articles!")
