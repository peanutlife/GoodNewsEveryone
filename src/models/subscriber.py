# src/models/subscriber.py
from src.models.user import db
from datetime import datetime

class EmailSubscriber(db.Model):
    __tablename__ = 'email_subscribers'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    unsubscribe_token = db.Column(db.String(100), unique=True)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    total_emails_sent = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<EmailSubscriber {self.email}>'
