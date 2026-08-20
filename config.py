import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'tg-mem-adder-secret-key-2026-super-secure')
    
    # Database configuration (PostgreSQL or fallback SQLite)
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///telegram_advanced.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis configuration
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    
    # Telegram API Credentials
    API_ID = int(os.environ.get('API_ID', 0)) if os.environ.get('API_ID', '').isdigit() else 0
    API_HASH = os.environ.get('API_HASH', '')
    BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
    
    # Default Admin Credentials
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    
    # Storage settings
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
