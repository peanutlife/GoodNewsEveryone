# db.py
import os
os.environ['FLASK_ENV'] = 'development'

from src.main import app, db

# Create all tables
with app.app_context():
    db.create_all()
    print("✅ Tables created successfully!")
    
    # Show what tables were created
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f"📋 Created tables: {', '.join(tables)}")
