# test_feeds.py
import feedparser
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from shared_data import get_feed_urls

print("🧪 Testing all RSS feeds...\n")

feed_urls = get_feed_urls()
working_feeds = []
broken_feeds = []

for i, url in enumerate(feed_urls, 1):
    print(f"Testing {i}/{len(feed_urls)}: {url[:60]}...", end=" ")
    
    try:
        feed = feedparser.parse(url)
        
        # Check if feed is valid and has entries
        if feed.bozo:
            print(f"❌ BROKEN: {feed.bozo_exception}")
            broken_feeds.append((url, str(feed.bozo_exception)))
        elif len(feed.entries) == 0:
            print("⚠️  EMPTY (no entries)")
            broken_feeds.append((url, "No entries found"))
        else:
            print(f"✅ OK ({len(feed.entries)} entries)")
            working_feeds.append(url)
    
    except Exception as e:
        print(f"❌ ERROR: {e}")
        broken_feeds.append((url, str(e)))

# Summary
print("\n" + "="*80)
print(f"📊 SUMMARY")
print("="*80)
print(f"✅ Working feeds: {len(working_feeds)}/{len(feed_urls)}")
print(f"❌ Broken feeds: {len(broken_feeds)}/{len(feed_urls)}")

# Save working feeds
if working_feeds:
    print("\n💾 Saving working feeds to feeds_working.txt...")
    with open('feeds_working.txt', 'w') as f:
        for url in working_feeds:
            f.write(url + '\n')
    print(f"✅ Saved {len(working_feeds)} working feeds")

# Save broken feeds for review
if broken_feeds:
    print("\n📝 Saving broken feeds to feeds_broken.txt...")
    with open('feeds_broken.txt', 'w') as f:
        for url, error in broken_feeds:
            f.write(f"{url}\n  Error: {error}\n\n")
    print(f"✅ Saved {len(broken_feeds)} broken feeds")

print("\n🎯 Next step: Replace feeds.txt with feeds_working.txt")
