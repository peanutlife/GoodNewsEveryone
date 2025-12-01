# src/email_templates.py
"""Modern, engaging email templates for Project Peanutlife"""

from datetime import datetime
import re
import random

# Inspirational quotes for daily emails (quote, author, image_url)
DAILY_QUOTES = [
    ("Be the change you wish to see in the world.", "Mahatma Gandhi", "https://images.unsplash.com/photo-1615461066841-6116e61058f4?w=400&h=400&fit=crop"),
    ("The only way to do great work is to love what you do.", "Steve Jobs", "https://images.unsplash.com/photo-1531297484001-80022131f5a1?w=400&h=400&fit=crop"),
    ("Believe you can and you're halfway there.", "Theodore Roosevelt", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop"),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein", "https://images.unsplash.com/photo-1509023464722-18d996393ca8?w=400&h=400&fit=crop"),
    ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb", "https://images.unsplash.com/photo-1516410529446-2c777cb7366d?w=400&h=400&fit=crop"),
    ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt", "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=400&h=400&fit=crop"),
    ("It is during our darkest moments that we must focus to see the light.", "Aristotle", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&h=400&fit=crop"),
    ("Whoever is happy will make others happy too.", "Anne Frank", "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=400&h=400&fit=crop"),
    ("Do not let what you cannot do interfere with what you can do.", "John Wooden", "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400&h=400&fit=crop"),
    ("You will face many defeats in life, but never let yourself be defeated.", "Maya Angelou", "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=400&h=400&fit=crop"),
    ("The greatest glory in living lies not in never falling, but in rising every time we fall.", "Nelson Mandela", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop"),
    ("In the end, it's not the years in your life that count. It's the life in your years.", "Abraham Lincoln", "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=400&h=400&fit=crop"),
    ("Life is what happens when you're busy making other plans.", "John Lennon", "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=400&h=400&fit=crop"),
    ("Spread love everywhere you go.", "Mother Teresa", "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=400&h=400&fit=crop"),
    ("The only impossible journey is the one you never begin.", "Tony Robbins", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&h=400&fit=crop"),
    ("Life is 10% what happens to you and 90% how you react to it.", "Charles R. Swindoll", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&h=400&fit=crop"),
    ("Your time is limited, don't waste it living someone else's life.", "Steve Jobs", "https://images.unsplash.com/photo-1531297484001-80022131f5a1?w=400&h=400&fit=crop"),
    ("Whether you think you can or you think you can't, you're right.", "Henry Ford", "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400&h=400&fit=crop"),
    ("The way to get started is to quit talking and begin doing.", "Walt Disney", "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=400&h=400&fit=crop"),
    ("Don't watch the clock; do what it does. Keep going.", "Sam Levenson", "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&h=400&fit=crop"),
]


def extract_image_from_summary(summary):
    """Extract first image URL from HTML summary"""
    if not summary:
        return None

    # Look for img tags in the summary
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if img_match:
        return img_match.group(1)
    return None


def strip_html(html_text):
    """Remove HTML tags from text"""
    if not html_text:
        return ""
    # Remove img tags first
    text = re.sub(r'<img[^>]*>', '', html_text)
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    return text.strip()


def generate_nyt_digest_html(articles, unsubscribe_url):
    """Generate clean NYT Wirecutter-inspired HTML for daily digest email"""

    # Get random daily quote
    quote_text, quote_author, quote_image = random.choice(DAILY_QUOTES)

    # Build article sections
    article_sections = ""
    for i, article in enumerate(articles, 1):
        topic_name = article.get('topic_name', 'general').title().replace('_', ' ')
        title = article.get('title', 'No title')
        summary_html = article.get('summary', '')
        link = article.get('link', '#')
        inspiration_score = article.get('inspiration_score', 5)

        # Extract image from summary HTML
        image_url = extract_image_from_summary(summary_html)

        # Clean summary text (remove HTML)
        summary = strip_html(summary_html)
        # Truncate to reasonable length
        if len(summary) > 250:
            summary = summary[:250] + '...'

        # Build image HTML if we have an image
        image_html = ""
        if image_url and image_url.startswith('http'):
            image_html = f"""
            <tr>
                <td style="padding: 0 0 20px 0;">
                    <a href="{link}" target="_blank" rel="noopener noreferrer">
                        <img src="{image_url}" alt="{title}" style="width: 100%; max-width: 600px; height: auto; display: block; border-radius: 4px;" />
                    </a>
                </td>
            </tr>
            """

        # Topic badge and score
        score_stars = '★' * min(int(inspiration_score), 5)

        article_sections += f"""
        <tr>
            <td style="padding: 0 0 40px 0; border-bottom: 1px solid #e5e5e5;">
                <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="padding: 0 0 12px 0;">
                            <span style="color: #666; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">{topic_name}</span>
                            <span style="color: #999; margin: 0 8px;">•</span>
                            <span style="color: #f59e0b; font-size: 13px;">{score_stars} {inspiration_score}/10</span>
                        </td>
                    </tr>
                    {image_html}
                    <tr>
                        <td style="padding: 0 0 12px 0;">
                            <h2 style="margin: 0; font-size: 22px; font-weight: 700; line-height: 1.3; color: #000;">
                                <a href="{link}" target="_blank" rel="noopener noreferrer" style="color: #000; text-decoration: none;">{title}</a>
                            </h2>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 0 16px 0;">
                            <p style="margin: 0; color: #333; font-size: 15px; line-height: 1.6;">{summary}</p>
                        </td>
                    </tr>
                    <tr>
                        <td>
                            <a href="{link}" target="_blank" rel="noopener noreferrer" style="color: #2563eb; text-decoration: none; font-size: 15px; font-weight: 500;">Read the full story →</a>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        """

    # Full HTML template - NYT Wirecutter inspired
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Daily Dose of Positivity</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; background-color: #ffffff;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f9f9f9;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff;">

                    <!-- Header -->
                    <tr>
                        <td align="center" style="padding: 40px 40px 20px 40px; border-bottom: 1px solid #e5e5e5;">
                            <div style="color: #999; font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">
                                View in browser
                            </div>
                            <h1 style="margin: 20px 0 8px 0; font-size: 14px; font-weight: 700; letter-spacing: 0.5px; color: #000; text-transform: uppercase;">
                                🥜 Project Peanutlife
                            </h1>
                            <h2 style="margin: 0; font-size: 32px; font-weight: 700; color: #000; font-family: Georgia, 'Times New Roman', serif;">
                                The Daily Dose
                            </h2>
                            <p style="margin: 8px 0 0 0; color: #666; font-size: 15px;">
                                The Recommendation
                            </p>
                            <p style="margin: 16px 0 0 0; color: #999; font-size: 13px;">
                                {datetime.now().strftime('%B %d, %Y')}
                            </p>
                        </td>
                    </tr>

                    <!-- Daily Quote with Image -->
                    <tr>
                        <td style="padding: 30px 40px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                                <tr>
                                    <td style="padding: 0;">
                                        <table width="100%" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <!-- Quote Image -->
                                                <td width="120" style="vertical-align: top; padding: 30px 0 30px 30px;">
                                                    <img src="{quote_image}" alt="{quote_author}" style="width: 100px; height: 100px; border-radius: 50%; border: 4px solid rgba(255,255,255,0.3); display: block; object-fit: cover;" />
                                                </td>
                                                <!-- Quote Text -->
                                                <td style="vertical-align: middle; padding: 30px 30px 30px 20px;">
                                                    <p style="margin: 0 0 12px 0; font-size: 19px; line-height: 1.5; color: white; font-style: italic; font-weight: 500;">
                                                        "{quote_text}"
                                                    </p>
                                                    <p style="margin: 0; font-size: 15px; color: rgba(255,255,255,0.9); font-weight: 600;">
                                                        — {quote_author}
                                                    </p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Intro -->
                    <tr>
                        <td style="padding: 20px 40px 30px 40px;">
                            <p style="margin: 0; font-size: 17px; line-height: 1.6; color: #333; text-align: center;">
                                Good morning! Here are today's top {len(articles)} inspiring stories to brighten your day ☀️
                            </p>
                        </td>
                    </tr>

                    <!-- Articles -->
                    <tr>
                        <td style="padding: 0 40px 20px 40px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                {article_sections}
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 40px; text-align: center; border-top: 1px solid #e5e5e5; background-color: #f9f9f9;">
                            <p style="margin: 0 0 16px 0; color: #666; font-size: 13px; line-height: 1.6;">
                                You're receiving this because you chose to start your days with positivity. ☀️<br>
                                <strong>We will never spam you, share your email, or send you ads.</strong>
                            </p>
                            <p style="margin: 0 0 12px 0; font-size: 12px;">
                                <a href="{unsubscribe_url}" style="color: #666; text-decoration: underline;">Unsubscribe</a>
                                <span style="color: #ccc; margin: 0 8px;">|</span>
                                <a href="https://peanutlife.com" style="color: #666; text-decoration: underline;">Visit Website</a>
                            </p>
                            <p style="margin: 0; color: #999; font-size: 11px;">
                                © {datetime.now().year} Project Peanutlife. Spreading positivity, one story at a time. 💛
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>
    """

    return html


def generate_modern_digest_html(articles, unsubscribe_url):
    """Generate modern, card-based HTML for daily digest email"""

    # Build article cards
    article_cards = ""
    for i, article in enumerate(articles, 1):
        topic_name = article.get('topic_name', 'general').title().replace('_', ' ')
        title = article.get('title', 'No title')
        summary = article.get('summary', '')[:150] + '...' if len(article.get('summary', '')) > 150 else article.get('summary', '')
        link = article.get('link', '#')
        image_url = article.get('image_url', '')
        inspiration_score = article.get('inspiration_score', 5)

        # Topic color mapping
        topic_colors = {
            'science': '#667eea',
            'technology': '#4299e1',
            'business': '#ed8936',
            'health': '#48bb78',
            'environment': '#38b2ac',
            'personal growth': '#9f7aea',
            'social impact': '#ed64a6',
            'culture': '#f56565',
            'travel': '#4299e1',
            'relationships': '#ed64a6',
            'sports': '#ed8936',
            'general': '#718096'
        }
        topic_color = topic_colors.get(topic_name.lower(), '#667eea')

        # Star rating
        score_stars = '★' * min(int(inspiration_score), 5)

        # Card HTML with image as background
        article_cards += f"""
        <tr>
            <td style="padding: 10px;">
                <table width="100%" cellpadding="0" cellspacing="0" style="background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <!-- Image Header -->
                    <tr>
                        <td style="height: 180px; background: linear-gradient(135deg, rgba(102, 126, 234, 0.9), rgba(118, 75, 162, 0.9)), url('{image_url}') center/cover; position: relative; padding: 20px;">
                            <div style="position: relative; z-index: 2;">
                                <div style="display: inline-block; background: {topic_color}; color: white; padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600; text-transform: uppercase; margin-bottom: 8px;">
                                    {topic_name}
                                </div>
                                <div style="color: #fbbf24; font-size: 16px; font-weight: bold;">
                                    {score_stars} {inspiration_score}/10
                                </div>
                            </div>
                        </td>
                    </tr>
                    <!-- Content -->
                    <tr>
                        <td style="padding: 20px;">
                            <h3 style="margin: 0 0 12px 0; font-size: 18px; line-height: 1.4; color: #1a202c;">
                                <a href="{link}" target="_blank" style="color: #1a202c; text-decoration: none; font-weight: 600;">{title}</a>
                            </h3>
                            <p style="margin: 0 0 16px 0; color: #4a5568; font-size: 14px; line-height: 1.6;">
                                {summary}
                            </p>
                            <a href="{link}" target="_blank" rel="noopener noreferrer" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px;">
                                Read Full Story →
                            </a>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        """

    # Full HTML
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Daily Dose of Positivity</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
    <table width="100%" cellpadding="0" cellspacing="0" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table width="600" cellpadding="0" cellspacing="0">
                    <!-- Header -->
                    <tr>
                        <td style="text-align: center; padding: 40px 20px;">
                            <h1 style="color: white; margin: 0; font-size: 36px; font-weight: 700; text-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                                🥜 Project Peanutlife
                            </h1>
                            <p style="color: rgba(255,255,255,0.95); margin: 8px 0 0 0; font-size: 18px; font-weight: 500;">
                                Your Daily Dose of Positivity
                            </p>
                            <div style="margin-top: 20px; padding: 12px 24px; background: rgba(255,255,255,0.2); border-radius: 30px; display: inline-block; backdrop-filter: blur(10px);">
                                <span style="color: white; font-size: 14px; font-weight: 600;">
                                    ☀️ {datetime.now().strftime('%A, %B %d, %Y')}
                                </span>
                            </div>
                        </td>
                    </tr>

                    <!-- Intro Card -->
                    <tr>
                        <td style="padding: 0 10px 20px 10px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: white; border-radius: 12px; padding: 30px; text-align: center;">
                                <tr>
                                    <td>
                                        <h2 style="margin: 0 0 12px 0; color: #1a202c; font-size: 24px; font-weight: 700;">
                                            Today's Top {len(articles)} Inspiring Stories
                                        </h2>
                                        <p style="margin: 0; color: #4a5568; font-size: 16px; line-height: 1.6;">
                                            Hand-picked by our AI to brighten your day and warm your heart ❤️
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Article Cards -->
                    {article_cards}

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 30px 10px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background: rgba(255,255,255,0.95); border-radius: 12px; padding: 30px; text-align: center;">
                                <tr>
                                    <td>
                                        <p style="margin: 0 0 16px 0; color: #4a5568; font-size: 14px; line-height: 1.6;">
                                            You're receiving this because you subscribed to Project Peanutlife
                                        </p>
                                        <div style="margin-bottom: 16px;">
                                            <a href="{unsubscribe_url}" style="color: #667eea; text-decoration: none; font-size: 14px; margin: 0 12px;">Unsubscribe</a>
                                            <span style="color: #cbd5e0;">|</span>
                                            <a href="https://peanutlife.com" style="color: #667eea; text-decoration: none; font-size: 14px; margin: 0 12px;">Visit Website</a>
                                        </div>
                                        <p style="margin: 0; color: #718096; font-size: 12px;">
                                            © {datetime.now().year} Project Peanutlife. Spreading positivity, one story at a time.
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
    """

    return html
