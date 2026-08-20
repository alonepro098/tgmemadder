from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_caching import Cache
from flask_cors import CORS
from database import db, Admin, UserSession, ScrapingTask, BroadcastMessage, Group, SystemLog, Settings
from config import Config
from datetime import datetime
import bcrypt
import logging
from celery import Celery
import os

# Initialize extensions
login_manager = LoginManager()
migrate = Migrate()
cache = Cache(config={'CACHE_TYPE': 'simple'})
cors = CORS()

# Initialize Celery
celery = Celery(__name__, broker=Config.REDIS_URL)
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'admin.login'
    migrate.init_app(app, db)
    cache.init_app(app)
    cors.init_app(app)
    
    # Celery config
    celery.conf.update(app.config)
    
    # Import and register blueprints
    from admin_routes import admin_bp
    from api_routes import api_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    @app.route('/')
    def index():
        return redirect(url_for('admin.dashboard'))
    
    # Create tables & default admin
    with app.app_context():
        db.create_all()
        create_default_admin()
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('base.html', content="<div class='glass-card text-center p-5'><h2>404 - Page Not Found</h2><a href='/admin/dashboard' class='btn btn-primary mt-3'>Go to Dashboard</a></div>"), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('base.html', content="<div class='glass-card text-center p-5'><h2>500 - Server Error</h2><a href='/admin/dashboard' class='btn btn-primary mt-3'>Go to Dashboard</a></div>"), 500
    
    return app

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

def create_default_admin():
    """Create default admin user if none exists"""
    admin = Admin.query.filter_by(username=Config.ADMIN_USERNAME).first()
    if not admin:
        hashed = bcrypt.hashpw(Config.ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt())
        admin = Admin(
            username=Config.ADMIN_USERNAME,
            email=Config.ADMIN_EMAIL,
            password_hash=hashed.decode('utf-8'),
            is_super_admin=True
        )
        db.session.add(admin)
        db.session.commit()
        
        # Create default settings
        default_settings = {
            'default_delay': '3',
            'max_members': '1000',
            'auto_join': 'true',
            'safe_mode': 'true',
            'log_level': 'info',
            'max_retries': '3',
            'timeout': '300',
            'batch_size': '100'
        }
        for key, value in default_settings.items():
            setting = Settings.query.filter_by(setting_key=key).first()
            if not setting:
                setting = Settings(
                    setting_key=key,
                    setting_value=value,
                    setting_type='string',
                    description=f'Default {key}'
                )
                db.session.add(setting)
        db.session.commit()

# Celery tasks
@celery.task(bind=True)
def process_scrape_task(self, task_id):
    """Process scrape and add task"""
    from utils import TaskManager
    return TaskManager.process_task(task_id)

@celery.task(bind=True)
def process_broadcast_task(self, broadcast_id):
    """Process broadcast task"""
    from utils import BroadcastManager
    return BroadcastManager.process_broadcast(broadcast_id)

@celery.task
def scheduled_scrape():
    """Scheduled scraping task"""
    from utils import SchedulerManager
    return SchedulerManager.run_scheduled_tasks()

@celery.task
def cleanup_sessions():
    """Cleanup expired sessions"""
    from utils import SessionManager
    return SessionManager.cleanup_expired_sessions()

if __name__ == '__main__':
    app = create_app()
    print("🚀 Starting Telegram Member Adder Server at http://127.0.0.1:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
