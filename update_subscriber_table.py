#!/usr/bin/env python
"""
Migration script to add last_sent_at and total_emails_sent columns
to email_subscribers table if they don't exist.
"""

import os
import sys
from sqlalchemy import text

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

from src.main import create_app
from src.models.subscriber import db

def update_subscriber_table():
    """Add new columns to email_subscribers table if they don't exist"""

    app = create_app()

    with app.app_context():
        try:
            # Check if columns exist by querying the table structure
            with db.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='email_subscribers'
                """))
                existing_columns = [row[0] for row in result]

                print(f"Existing columns: {existing_columns}")

                # Add last_sent_at if it doesn't exist
                if 'last_sent_at' not in existing_columns:
                    print("Adding last_sent_at column...")
                    conn.execute(text("""
                        ALTER TABLE email_subscribers
                        ADD COLUMN last_sent_at TIMESTAMP
                    """))
                    conn.commit()
                    print("✓ Added last_sent_at column")
                else:
                    print("✓ last_sent_at column already exists")

                # Add total_emails_sent if it doesn't exist
                if 'total_emails_sent' not in existing_columns:
                    print("Adding total_emails_sent column...")
                    conn.execute(text("""
                        ALTER TABLE email_subscribers
                        ADD COLUMN total_emails_sent INTEGER DEFAULT 0
                    """))
                    conn.commit()
                    print("✓ Added total_emails_sent column")
                else:
                    print("✓ total_emails_sent column already exists")

            print("\n✅ Database migration complete!")

        except Exception as e:
            print(f"❌ Error updating table: {e}")
            print("\nThis might mean the table doesn't exist yet.")
            print("Run the app once to create all tables, then run this script again.")


if __name__ == '__main__':
    update_subscriber_table()
