# check_db_connection.py
import os
import psycopg2

# Get the DATABASE_URL from environment
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("❌ No DATABASE_URL found!")
    exit(1)

# Replace postgres:// with postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

print(f"🔍 Testing connection to: {DATABASE_URL[:50]}...")

try:
    # Try connecting with different SSL modes
    for sslmode in ['require', 'prefer', 'allow', 'disable']:
        try:
            print(f"\n🔌 Trying sslmode={sslmode}...")

            # Parse the URL
            from urllib.parse import urlparse

            result = urlparse(DATABASE_URL)

            conn = psycopg2.connect(
                database=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port,
                sslmode=sslmode,
                connect_timeout=10
            )

            print(f"✅ SUCCESS with sslmode={sslmode}!")

            # Test the connection
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()
            print(f"📊 PostgreSQL version: {version[0][:50]}...")

            cursor.close()
            conn.close()

            print(f"\n✅ SOLUTION: Use sslmode={sslmode}")
            break

        except Exception as e:
            print(f"❌ Failed with sslmode={sslmode}: {str(e)[:100]}")

except Exception as e:
    print(f"❌ All connection attempts failed: {e}")