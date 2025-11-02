# src/routes/auth.py

from flask import Blueprint, request, render_template, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from src.models.user import User, Topic, db
from src.models.subscriber import EmailSubscriber
from src.shared_data import article_cache
import os
import secrets


auth_bp = Blueprint('auth', __name__, template_folder='../templates/auth')

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')

        # Validate form data
        if not (username and email and password and password_confirm):
            flash('All fields are required', 'danger')
            return render_template('signup.html')

        if password != password_confirm:
            flash('Passwords do not match', 'danger')
            return render_template('signup.html')

        # Check if username or email already exists
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            flash('Username or email already registered', 'danger')
            return render_template('signup.html')

        # Create new user
        new_user = User(username=username, email=email)
        new_user.set_password(password)

        # Add default topics - we'll create a page later for them to select more
        default_topics = Topic.query.limit(3).all()
        for topic in default_topics:
            new_user.add_favorite_topic(topic)

        db.session.add(new_user)
        db.session.commit()

        # Log the user in
        login_user(new_user)
        flash('Your account has been created successfully!', 'success')
        return redirect(url_for('index'))

    # GET request - show signup form
    return render_template('signup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = 'remember' in request.form

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            user.last_login = db.func.now()
            db.session.commit()

            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@auth_bp.route('/profile')
@login_required
def profile():
    # Get all topics for the user to choose from
    all_topics = Topic.query.all()

    # Get count of saved articles
    saved_count = current_user.saved_articles.count()

    return render_template('profile.html',
                          user=current_user,
                          all_topics=all_topics,
                          saved_count=saved_count)

@auth_bp.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    if request.method == 'POST':
        # Update email if provided and different
        email = request.form.get('email')
        if email and email != current_user.email:
            existing = User.query.filter_by(email=email).first()
            if existing and existing.id != current_user.id:
                flash('Email already in use', 'danger')
            else:
                current_user.email = email

        # Update password if provided
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        if password:
            if password != password_confirm:
                flash('Passwords do not match', 'danger')
            else:
                current_user.set_password(password)
                flash('Password updated', 'success')

        # Update preferences
        current_user.email_notifications = 'email_notifications' in request.form
        current_user.daily_digest = 'daily_digest' in request.form
        current_user.dark_mode = 'dark_mode' in request.form
        try:
            inspiration_score = float(request.form.get('min_inspiration_score', 5.0))
            current_user.min_inspiration_score = max(min(inspiration_score, 10.0), 1.0)
        except ValueError:
            pass  # Invalid input, keep existing value

        # Update favorite topics
        selected_topics = request.form.getlist('topics')

        # Clear existing topics
        current_user.favorite_topics = []

        # Add selected topics
        for topic_name in selected_topics:
            topic = Topic.query.get(topic_name)
            if topic:
                current_user.add_favorite_topic(topic)

        db.session.commit()
        flash('Your profile has been updated', 'success')

    return redirect(url_for('auth.profile'))

@auth_bp.route('/saved_articles')
@login_required
def saved_articles():
    saved = current_user.saved_articles.order_by(db.desc('saved_at')).all()
    return render_template('saved_articles.html', articles=saved)

@auth_bp.route('/save_article', methods=['POST'])
@login_required
def save_article():
    if request.method == 'POST':
        article_link = request.form.get('article_link')
        article_title = request.form.get('article_title')
        topic_name = request.form.get('topic_name')

        if not (article_link and article_title):
            flash('Missing article information', 'danger')
            return redirect(request.referrer or url_for('index'))

        # Check if already saved
        existing = current_user.saved_articles.filter_by(article_link=article_link).first()
        if existing:
            flash('Article already saved', 'info')
        else:
            current_user.save_article(article_link, article_title, topic_name)
            flash('Article saved!', 'success')

    return redirect(request.referrer or url_for('index'))

@auth_bp.route('/remove_saved_article/<int:article_id>', methods=['POST'])
@login_required
def remove_saved_article(article_id):
    article = current_user.saved_articles.filter_by(id=article_id).first()

    if article:
        db.session.delete(article)
        db.session.commit()
        flash('Article removed from saved list', 'success')
    else:
        flash('Article not found', 'danger')

    return redirect(url_for('auth.saved_articles'))


@auth_bp.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        # Validate email
        if not email or '@' not in email:
            flash('Please enter a valid email address', 'danger')
            return redirect(url_for('auth.subscribe'))

        # Check if already subscribed
        existing = EmailSubscriber.query.filter_by(email=email).first()
        if existing:
            if existing.is_active:
                flash('This email is already subscribed!', 'info')
            else:
                existing.is_active = True
                db.session.commit()
                flash('Welcome back! Your subscription has been reactivated.', 'success')
            return redirect(url_for('index'))

        # Create new subscriber
        subscriber = EmailSubscriber(
            email=email,
            unsubscribe_token=secrets.token_urlsafe(32)
        )
        db.session.add(subscriber)
        db.session.commit()

        flash('Thank you for subscribing! You\'ll receive daily positive news in your inbox.', 'success')
        return redirect(url_for('index'))

    return render_template('subscribe.html')


@auth_bp.route('/unsubscribe/<token>')
def unsubscribe(token):
    subscriber = EmailSubscriber.query.filter_by(unsubscribe_token=token).first()

    if subscriber:
        subscriber.is_active = False
        db.session.commit()
        flash('You have been unsubscribed. We\'re sorry to see you go!', 'info')
    else:
        flash('Invalid unsubscribe link', 'danger')

    return redirect(url_for('index'))


# Initialize topics
def init_topics():
    # Get topics from your existing system
    topics_to_create = [
        {"name": "science", "display_name": "Science", "description": "Scientific discoveries and breakthroughs"},
        {"name": "technology", "display_name": "Technology", "description": "Tech innovations and digital trends"},
        {"name": "health", "display_name": "Health", "description": "Health, wellness, and medical advances"},
        {"name": "environment", "display_name": "Environment", "description": "Environmental news and sustainability"},
        {"name": "culture", "display_name": "Culture", "description": "Arts, music, and cultural developments"},
        {"name": "travel", "display_name": "Travel", "description": "Travel destinations and tourism"},
        {"name": "sports", "display_name": "Sports", "description": "Sports news and achievements"},
        {"name": "kids", "display_name": "Kids", "description": "News for children and about education"},
        {"name": "teens", "display_name": "Teens", "description": "Content relevant to teenagers"},
        {"name": "general", "display_name": "General", "description": "General positive news"}
    ]

    for topic_data in topics_to_create:
        # Check if topic already exists
        existing = Topic.query.get(topic_data["name"])
        if not existing:
            # Create emoji icon path from topic name
            icon_hex = None
            from src.aggregator import topic_icon_map, fallback_icons

            if topic_data["name"] in topic_icon_map:
                icon_hex = topic_icon_map[topic_data["name"]]
            elif topic_data["name"] in fallback_icons:
                icon_hex = fallback_icons[topic_data["name"]]

            icon_path = f"/openmoji/color/svg/{icon_hex}.svg" if icon_hex else None

            # Create new topic
            new_topic = Topic(
                name=topic_data["name"],
                display_name=topic_data["display_name"],
                description=topic_data["description"],
                icon_path=icon_path
            )
            db.session.add(new_topic)

    db.session.commit()
