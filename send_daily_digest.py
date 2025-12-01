#!/usr/bin/env python
# send_daily_digest.py
"""
Daily digest email sender for Project Peanutlife subscribers.
Sends top 10 inspiring articles to all active subscribers.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

from src.main import create_app
from src.models.subscriber import EmailSubscriber, db
from src.email_service import EmailService
from src.config import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


def get_articles_from_last_24_hours(articles):
    """Filter articles published in the last 24 hours"""
    now = datetime.utcnow()
    yesterday = now - timedelta(hours=24)

    recent_articles = []
    for article in articles:
        try:
            pub_date_str = article.get('published')
            if pub_date_str:
                pub_date = datetime.fromisoformat(pub_date_str)
                if pub_date >= yesterday:
                    recent_articles.append(article)
        except (ValueError, TypeError):
            continue

    logger.info(f"Found {len(recent_articles)} articles from last 24 hours")
    return recent_articles


def send_daily_digest(test_mode=False, test_email=None):
    """Send daily digest to all active subscribers"""

    # Create app context
    app = create_app()

    with app.app_context():
        # Load configuration
        env = os.environ.get('FLASK_ENV', 'development')
        app_config = config[env]

        # Check email credentials
        if not app_config.MAIL_USERNAME or not app_config.MAIL_PASSWORD:
            logger.error("Email credentials not configured!")
            logger.error("Please set MAIL_USERNAME and MAIL_PASSWORD in .env file")
            return

        # Initialize email service
        email_service = EmailService(app_config)

        # Load articles
        all_articles = load_articles()
        if not all_articles:
            logger.error("No articles found. Aborting.")
            return

        # Get recent articles (last 24 hours) or all if none found
        recent_articles = get_articles_from_last_24_hours(all_articles)
        if not recent_articles:
            logger.warning("No articles from last 24 hours, using top articles overall")
            recent_articles = all_articles

        # Get top 10 articles
        top_articles = get_top_articles(recent_articles, count=10)
        logger.info(f"Selected top {len(top_articles)} articles for digest")

        # Get active subscribers
        if test_mode and test_email:
            # Test mode: send to specific email
            logger.info(f"TEST MODE: Sending to {test_email}")
            subscribers = [type('obj', (object,), {
                'email': test_email,
                'unsubscribe_token': 'test-token-123',
                'id': 0
            })]
        else:
            subscribers = EmailSubscriber.query.filter_by(is_active=True).all()

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
                unsubscribe_url = f"https://peanutlife.com/unsubscribe/{subscriber.unsubscribe_token}"

                # Generate HTML
                html_content = email_service.generate_daily_digest_html(
                    top_articles,
                    unsubscribe_url
                )

                # Send email
                subject = f"🥜 Your Daily Dose of Positivity - {datetime.now().strftime('%B %d, %Y')}"
                success = email_service.send_email(
                    subscriber.email,
                    subject,
                    html_content
                )

                if success:
                    success_count += 1

                    # Update subscriber stats (skip in test mode)
                    if not test_mode:
                        subscriber.last_sent_at = datetime.utcnow()
                        subscriber.total_emails_sent += 1

                else:
                    failure_count += 1

            except Exception as e:
                logger.error(f"Error sending to {subscriber.email}: {e}")
                failure_count += 1

        # Commit database changes (skip in test mode)
        if not test_mode:
            try:
                db.session.commit()
                logger.info("Database updated successfully")
            except Exception as e:
                logger.error(f"Error updating database: {e}")
                db.session.rollback()

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
    parser.add_argument('--test', action='store_true', help='Test mode (doesn\'t update database)')
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
