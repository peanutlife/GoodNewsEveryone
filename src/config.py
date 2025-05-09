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
    POSITIVE_THRESHOLD = 0.80
    
    # Database
    DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(DATA_DIR, os.environ.get('DATABASE_PATH', 'brightside.db'))}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Admin
    ADMIN_USER = os.environ.get('ADMIN_USER')
    ADMIN_PASS = os.environ.get('ADMIN_PASS')
    
    # API Keys
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    
    # Ensure required directories exist
    @classmethod
    def init_app(cls, app):
        """Initialize application configuration."""
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        
        # Setup app configuration
        app.config.from_object(cls)
        
        # Check for critical configurations
        if not cls.ADMIN_USER or not cls.ADMIN_PASS:
            app.logger.warning("Admin username or password not set! Using defaults is highly insecure.")
        
        if not cls.OPENAI_API_KEY:
            app.logger.warning("OpenAI API key not set! Some features may not work properly.")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        
        # Production-specific setup
        if not cls.SECRET_KEY or cls.SECRET_KEY == secrets.token_hex(32):
            app.logger.error("SECRET_KEY not set! Using a random key which will change on restart.")
            
        if cls.ADMIN_USER == 'admin' or not cls.ADMIN_PASS:
            app.logger.error("Insecure admin credentials detected in production!")


# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
