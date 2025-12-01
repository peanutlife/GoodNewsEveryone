# src/email_templates.py
"""Modern, engaging email templates for Project Peanutlife"""

from datetime import datetime
import re


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

                    <!-- Intro -->
                    <tr>
                        <td style="padding: 40px 40px 30px 40px;">
                            <p style="margin: 0; font-size: 17px; line-height: 1.6; color: #333;">
                                Good morning! Here are today's top {len(articles)} inspiring stories, carefully selected to brighten your day and remind you of all the good happening in the world.
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
                            <p style="margin: 0 0 12px 0; color: #666; font-size: 12px; line-height: 1.5;">
                                You're receiving this because you subscribed to Project Peanutlife.
                            </p>
                            <p style="margin: 0 0 12px 0; font-size: 12px;">
                                <a href="{unsubscribe_url}" style="color: #666; text-decoration: underline;">Unsubscribe</a>
                                <span style="color: #ccc; margin: 0 8px;">|</span>
                                <a href="https://peanutlife.com" style="color: #666; text-decoration: underline;">Visit Website</a>
                            </p>
                            <p style="margin: 0; color: #999; font-size: 11px;">
                                © {datetime.now().year} Project Peanutlife. Spreading positivity, one story at a time.
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
