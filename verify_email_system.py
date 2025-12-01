#!/usr/bin/env python
"""
Verification script to check if email subscription system is properly set up
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

from src.main import create_app
from src.models.subscriber import EmailSubscriber, db
from src.config import config

def verify_system():
    """Verify the email subscription system setup"""

    print("=" * 60)
    print("EMAIL SUBSCRIPTION SYSTEM VERIFICATION")
    print("=" * 60)

    app = create_app()

    with app.app_context():
        # Check 1: Database connection
        print("\n1. Checking database connection...")
        try:
            db.engine.connect()
            print("   ✓ Database connected")
        except Exception as e:
            print(f"   ❌ Database connection failed: {e}")
            return

        # Check 2: Email configuration
        print("\n2. Checking email configuration...")
        env = os.environ.get('FLASK_ENV', 'development')
        app_config = config[env]

        if app_config.MAIL_USERNAME and app_config.MAIL_PASSWORD:
            print(f"   ✓ Email configured (Server: {app_config.MAIL_SERVER})")
            print(f"   ✓ Username: {app_config.MAIL_USERNAME}")
        else:
            print("   ❌ Email credentials not configured")
            print("   Please set MAIL_USERNAME and MAIL_PASSWORD in .env")

        # Check 3: Subscriber table
        print("\n3. Checking email_subscribers table...")
        try:
            subscriber_count = EmailSubscriber.query.count()
            print(f"   ✓ Table exists with {subscriber_count} subscriber(s)")

            # Show active subscribers
            active_count = EmailSubscriber.query.filter_by(is_active=True).count()
            print(f"   ✓ Active subscribers: {active_count}")

        except Exception as e:
            print(f"   ❌ Table check failed: {e}")
            print("   Run update_subscriber_table.py to create/update the table")

        # Check 4: Article cache
        print("\n4. Checking article cache...")
        cache_file = os.path.join(os.path.dirname(__file__), 'data', 'article_cache.json')
        if os.path.exists(cache_file):
            import json
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
                articles_by_topic = cache_data.get('articles', {})
                total_articles = sum(len(articles) for articles in articles_by_topic.values())
                print(f"   ✓ Cache file exists with {total_articles} articles")
        else:
            print(f"   ❌ Cache file not found: {cache_file}")
            print("   Run the aggregator to fetch articles first")

        # Check 5: Email templates
        print("\n5. Checking email templates...")
        try:
            from src.email_templates import generate_nyt_digest_html
            print("   ✓ Email templates imported successfully")
        except Exception as e:
            print(f"   ❌ Template import failed: {e}")

        print("\n" + "=" * 60)
        print("VERIFICATION COMPLETE")
        print("=" * 60)

        # Summary
        print("\n📋 NEXT STEPS:")
        print("1. If database table needs updating, run:")
        print("   python update_subscriber_table.py")
        print("\n2. Test email sending with:")
        print("   python send_daily_digest.py --test --email your-email@example.com")
        print("\n3. Users can subscribe at:")
        print("   http://localhost:5000/subscribe")
        print("\n4. Set up cron job to send daily emails:")
        print("   0 8 * * * cd /path/to/project && python send_daily_digest.py")


if __name__ == '__main__':
    verify_system()
