# src/models/user.py

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json
from datetime import datetime

db = SQLAlchemy()

# Association table for many-to-many relationship between users and topics
# Define the foreign keys explicitly
user_topics = db.Table('user_topics',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('topic_name', db.String(50), db.ForeignKey('topic.name', ondelete='CASCADE'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # User preference settings
    email_notifications = db.Column(db.Boolean, default=False)
    daily_digest = db.Column(db.Boolean, default=False)
    dark_mode = db.Column(db.Boolean, default=False)
    min_inspiration_score = db.Column(db.Float, default=5.0)  # Only show articles above this inspiration score

    # Favorite topics (many-to-many relationship)
    favorite_topics = db.relationship('Topic', secondary=user_topics,
                                     backref=db.backref('users_interested', lazy='dynamic'))

    # Saved/bookmarked articles
    saved_articles = db.relationship('SavedArticle', backref='user', lazy='dynamic')


    def set_password(self, password):
        """Set password hash using a compatible algorithm"""
        # Use sha256 method which is available in all Python versions
        self.password_hash = generate_password_hash(
            password,
            method='pbkdf2:sha256',  # Force a specific algorithm that's widely available
            salt_length=8
        )

    def check_password(self, password):
        """Check password against stored hash"""
        return check_password_hash(self.password_hash, password)

    def add_favorite_topic(self, topic):
        if topic not in self.favorite_topics:
            self.favorite_topics.append(topic)

    def remove_favorite_topic(self, topic):
        if topic in self.favorite_topics:
            self.favorite_topics.remove(topic)

    def save_article(self, article_link, article_title, topic_name):
        saved = SavedArticle(
            user_id=self.id,
            article_link=article_link,
            article_title=article_title,
            topic_name=topic_name
        )
        db.session.add(saved)
        db.session.commit()

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'favorite_topics': [topic.name for topic in self.favorite_topics],
            'preferences': {
                'email_notifications': self.email_notifications,
                'daily_digest': self.daily_digest,
                'dark_mode': self.dark_mode,
                'min_inspiration_score': self.min_inspiration_score
            }
        }

    def __repr__(self):
        return f'<User {self.username}>'


class Topic(db.Model):
    name = db.Column(db.String(50), primary_key=True)
    display_name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text)
    icon_path = db.Column(db.String(255))

    def __repr__(self):
        return f'<Topic {self.name}>'


class SavedArticle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    article_link = db.Column(db.String(2048), nullable=False)
    article_title = db.Column(db.String(255), nullable=False)
    topic_name = db.Column(db.String(50), nullable=True)
    saved_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SavedArticle {self.article_title[:20]}...>'
