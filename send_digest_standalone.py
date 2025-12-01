#!/usr/bin/env python
"""
Standalone daily digest sender that doesn't require Flask app initialization.
Connects directly to the database without creating the full Flask app.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import email service
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from email_service import EmailService
from config import config


def load_articles():
    """Load articles from cache"""
    cache_file = os.path.join(os.path.dirname(__file__), 'data', 'article_cache.json')

    if not os.path.exists(cache_file):
        logger.error(f"Cache file not found: {cache_file}")
        return []

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            articles_by_topic = cache_data.get('articles', {})

            # Flatten all articles into a single list
            all_articles = []
            for topic, articles in articles_by_topic.items():
                all_articles.extend(articles)

            logger.info(f"Loaded {len(all_articles)} total articles from cache")
            return all_articles

    except Exception as e:
        logger.error(f"Error loading articles: {e}")
        return []


def get_top_articles(articles, count=10):
    """Get top N articles by inspiration score (deduplicated by link)"""
    # Deduplicate by link first
    seen_links = set()
    unique_articles = []

    for article in articles:
        link = article.get('link', '')
        if link and link not in seen_links:
            seen_links.add(link)
            unique_articles.append(article)

    # Sort by inspiration score (descending) and published date
    sorted_articles = sorted(
        unique_articles,
        key=lambda x: (
            x.get('inspiration_score', 0),
            x.get('published', '')
        ),
        reverse=True
    )

    return sorted_articles[:count]


def get_active_subscribers(database_url):
    """Get active subscribers directly from database"""
    try:
        # Create engine
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)

        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={'sslmode': 'require'} if 'render.com' in database_url else {}
        )

        # Query subscribers
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, email, unsubscribe_token
                FROM email_subscribers
                WHERE is_active = true
            """))

            subscribers = []
            for row in result:
                subscribers.append({
                    'id': row[0],
                    'email': row[1],
                    'unsubscribe_token': row[2]
                })

            logger.info(f"Found {len(subscribers)} active subscribers")
            return subscribers, engine

    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        return [], None


def update_subscriber_stats(engine, subscriber_id):
    """Update subscriber stats after sending"""
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE email_subscribers
                SET last_sent_at = :now,
                    total_emails_sent = total_emails_sent + 1
                WHERE id = :id
            """), {'now': datetime.utcnow(), 'id': subscriber_id})
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating subscriber stats: {e}")


def send_daily_digest(test_mode=False, test_email=None):
    """Send daily digest to all active subscribers"""

    # Get configuration
    env = os.environ.get('FLASK_ENV', 'production')
    app_config = config.get(env, config['production'])

    # Check email credentials
    if not app_config.MAIL_USERNAME or not app_config.MAIL_PASSWORD:
        logger.error("Email credentials not configured!")
        return

    # Initialize email service
    email_service = EmailService(app_config)

    # Load articles
    all_articles = load_articles()
    if not all_articles:
        logger.error("No articles found. Aborting.")
        return

    # Get top 10 articles
    top_articles = get_top_articles(all_articles, count=10)
    logger.info(f"Selected top {len(top_articles)} articles for digest")

    # Get database URL
    database_url = os.environ.get('DATABASE_URL') or app_config.SQLALCHEMY_DATABASE_URI

    if test_mode and test_email:
        # Test mode
        logger.info(f"TEST MODE: Sending to {test_email}")
        subscribers = [{'id': 0, 'email': test_email, 'unsubscribe_token': 'test-token'}]
        engine = None
    else:
        # Get active subscribers from database
        subscribers, engine = get_active_subscribers(database_url)

    if not subscribers:
        logger.warning("No active subscribers found")
        return

    logger.info(f"Sending to {len(subscribers)} subscribers")

    # Send emails
    success_count = 0
    failure_count = 0

    for subscriber in subscribers:
        try:
            # Generate unsubscribe URL
            unsubscribe_url = f"https://peanutlife.com/unsubscribe/{subscriber['unsubscribe_token']}"

            # Generate HTML
            html_content = email_service.generate_daily_digest_html(
                top_articles,
                unsubscribe_url
            )

            # Send email
            subject = f"🥜 Your Daily Dose of Positivity - {datetime.now().strftime('%B %d, %Y')}"
            success = email_service.send_email(
                subscriber['email'],
                subject,
                html_content
            )

            if success:
                success_count += 1
                # Update stats (skip in test mode)
                if not test_mode and engine:
                    update_subscriber_stats(engine, subscriber['id'])
            else:
                failure_count += 1

        except Exception as e:
            logger.error(f"Error sending to {subscriber['email']}: {e}")
            failure_count += 1

    # Summary
    logger.info("=" * 60)
    logger.info("DAILY DIGEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total subscribers: {len(subscribers)}")
    logger.info(f"Successfully sent: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"Articles included: {len(top_articles)}")
    logger.info("=" * 60)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Send daily digest emails')
    parser.add_argument('--test', action='store_true', help='Test mode')
    parser.add_argument('--email', type=str, help='Test email address')

    args = parser.parse_args()

    if args.test:
        if not args.email:
            print("Error: --email required in test mode")
            sys.exit(1)
        print(f"\n🧪 TEST MODE: Sending to {args.email}\n")
        send_daily_digest(test_mode=True, test_email=args.email)
    else:
        print("\n📧 PRODUCTION MODE: Sending to all active subscribers\n")
        send_daily_digest(test_mode=False)
