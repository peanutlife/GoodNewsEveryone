#!/usr/bin/env python
"""
Complete daily automation: Fetch fresh articles → Send digest
Runs the full pipeline without any manual intervention.
"""

import os
import sys
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_aggregator():
    """Fetch fresh articles from RSS feeds"""
    logger.info("=" * 60)
    logger.info("STEP 1: FETCHING FRESH ARTICLES")
    logger.info("=" * 60)

    try:
        # Import and run aggregator
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
        from aggregator import main as fetch_articles

        logger.info("Fetching latest articles from RSS feeds...")
        fetch_articles()
        logger.info("✅ Articles fetched and cached successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Error fetching articles: {e}")
        # Continue anyway with cached articles
        logger.warning("Continuing with existing cached articles...")
        return False


def send_digest():
    """Send daily digest to subscribers"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: SENDING DAILY DIGEST")
    logger.info("=" * 60)

    try:
        # Import and run digest sender
        from send_digest_standalone import send_daily_digest

        logger.info("Sending emails to active subscribers...")
        send_daily_digest(test_mode=False)
        logger.info("✅ Daily digest completed")
        return True

    except Exception as e:
        logger.error(f"❌ Error sending digest: {e}")
        return False


def main():
    """Run the complete daily automation pipeline"""
    start_time = datetime.now()

    logger.info("🤖 DAILY AUTOMATION STARTING")
    logger.info(f"⏰ Time: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logger.info("")

    # Step 1: Fetch fresh articles
    articles_success = run_aggregator()

    # Step 2: Send digest (even if fetching failed, use cached)
    digest_success = send_digest()

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("")
    logger.info("=" * 60)
    logger.info("🎯 AUTOMATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Articles fetched: {'✅ Success' if articles_success else '⚠️  Failed (used cache)'}")
    logger.info(f"Digest sent: {'✅ Success' if digest_success else '❌ Failed'}")
    logger.info(f"Total duration: {duration:.2f} seconds")
    logger.info("=" * 60)

    # Exit with appropriate code
    if digest_success:
        logger.info("✅ Daily automation completed successfully!")
        sys.exit(0)
    else:
        logger.error("❌ Daily automation failed!")
        sys.exit(1)


if __name__ == '__main__':
    main()
