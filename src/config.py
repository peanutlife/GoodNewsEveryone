import os
import secrets
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()


class Config:
    """Base configuration."""
    # Flask
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

    # Application settings
    CACHE_DURATION_SECONDS = int(os.environ.get('CACHE_DURATION_SECONDS', 900))
    POSITIVE_THRESHOLD = 0.50

    # Database
    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))

    # Get DATABASE_URL from environment (Render provides this)
    DATABASE_URL = os.environ.get('DATABASE_URL')

    if DATABASE_URL:
        # Render uses postgres:// but SQLAlchemy needs postgresql://
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

        # Important: Don't add sslmode to the URL itself
        # We'll handle SSL in connect_args instead
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        # Local development - use PostgreSQL
        db_name = os.environ.get('DB_NAME', 'brightside_dev')
        db_user = os.environ.get('DB_USER', os.environ.get('USER'))
        db_password = os.environ.get('DB_PASSWORD', '')
        db_host = os.environ.get('DB_HOST', 'localhost')
        db_port = os.environ.get('DB_PORT', '5432')

        SQLALCHEMY_DATABASE_URI = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # SQLAlchemy settings
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Connection pool settings - SSL configured here
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
        'connect_args': {
            'connect_timeout': 10,
            'sslmode': 'require',  # This is the key SSL setting
        }
    }

    # Admin
    ADMIN_USER = os.environ.get('ADMIN_USER')
    ADMIN_PASS = os.environ.get('ADMIN_PASS')

    # API Keys
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

    @classmethod
    def init_app(cls, app):
        """Initialize application configuration."""
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        app.config.from_object(cls)

        if not cls.ADMIN_USER or not cls.ADMIN_PASS:
            app.logger.warning("Admin username or password not set!")

        if not cls.OPENAI_API_KEY:
            app.logger.warning("OpenAI API key not set!")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

    # Override SSL for local development (no SSL needed locally)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'connect_args': {
            'connect_timeout': 5,
        }
    }


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {}


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False

    # Production SSL settings - more explicit
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
        'connect_args': {
            'connect_timeout': 10,
            'sslmode': 'require',
            'sslrootcert': None,  # Don't verify certificate
        }
    }

    @classmethod
    def init_app(cls, app):
        Config.init_app(app)

        if not cls.SECRET_KEY or cls.SECRET_KEY == secrets.token_hex(32):
            app.logger.error("SECRET_KEY not set!")

        if cls.ADMIN_USER == 'admin' or not cls.ADMIN_PASS:
            app.logger.error("Insecure admin credentials!")

        # Log database connection info (sanitized)
        if cls.DATABASE_URL:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(cls.SQLALCHEMY_DATABASE_URI)
                safe_uri = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}{parsed.path}"
                app.logger.info(f"Production database: {safe_uri}")
            except:
                pass


# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}