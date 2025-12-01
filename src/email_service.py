# src/email_service.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
from src.email_templates import generate_nyt_digest_html

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails to subscribers"""

    def __init__(self, config):
        self.smtp_server = config.MAIL_SERVER
        self.smtp_port = config.MAIL_PORT
        self.use_tls = config.MAIL_USE_TLS
        self.username = config.MAIL_USERNAME
        self.password = config.MAIL_PASSWORD
        self.sender = config.MAIL_DEFAULT_SENDER

    def send_email(self, to_email, subject, html_content):
        """Send an email"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.sender
            msg['To'] = to_email

            # Attach HTML content
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()

                if self.username and self.password:
                    server.login(self.username, self.password)

                server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def generate_daily_digest_html(self, articles, unsubscribe_url):
        """Generate HTML for daily digest email using NYT-inspired template"""
        return generate_nyt_digest_html(articles, unsubscribe_url)
