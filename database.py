from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class Admin(UserMixin, db.Model):
    __tablename__ = 'admins'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    def __repr__(self):
        return f'<Admin {self.username}>'

class UserSession(db.Model):
    __tablename__ = 'user_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(30), unique=True, nullable=False)
    session_string = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    daily_adds_count = db.Column(db.Integer, default=0)
    last_used = db.Column(db.DateTime)
    expiry_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tasks = db.relationship('ScrapingTask', backref='user_session', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'phone_number': self.phone_number,
            'is_active': self.is_active,
            'daily_adds_count': self.daily_adds_count,
            'last_used': self.last_used.strftime('%Y-%m-%d %H:%M:%S') if self.last_used else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }

class ScrapingTask(db.Model):
    __tablename__ = 'scraping_tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default='Scrape Task')
    source_group_link = db.Column(db.String(255), nullable=False)
    target_group_link = db.Column(db.String(255), nullable=False)
    user_session_id = db.Column(db.Integer, db.ForeignKey('user_sessions.id'), nullable=False)
    max_members = db.Column(db.Integer, default=500)
    filter_keywords = db.Column(db.Text)  # JSON string of filter keywords
    exclude_keywords = db.Column(db.Text)  # JSON string of exclude keywords
    delay_between_adds = db.Column(db.Integer, default=3)  # Delay in seconds
    
    status = db.Column(db.String(20), default='pending')  # pending, running, completed, failed, cancelled
    progress = db.Column(db.Integer, default=0)  # 0 to 100
    
    members_scraped = db.Column(db.Integer, default=0)
    members_added = db.Column(db.Integer, default=0)
    members_failed = db.Column(db.Integer, default=0)
    duplicates_found = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'source_group_link': self.source_group_link,
            'target_group_link': self.target_group_link,
            'user_session_id': self.user_session_id,
            'max_members': self.max_members,
            'delay_between_adds': self.delay_between_adds,
            'status': self.status,
            'progress': self.progress,
            'members_scraped': self.members_scraped,
            'members_added': self.members_added,
            'members_failed': self.members_failed,
            'duplicates_found': self.duplicates_found,
            'error_message': self.error_message,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else None,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None
        }

class BroadcastMessage(db.Model):
    __tablename__ = 'broadcast_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    target_group_link = db.Column(db.String(255), nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Group(db.Model):
    __tablename__ = 'groups'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    username = db.Column(db.String(100))
    entity_id = db.Column(db.BigInteger)
    access_hash = db.Column(db.BigInteger)
    member_count = db.Column(db.Integer, default=0)
    group_type = db.Column(db.String(50))  # supergroup, channel, group
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    log_type = db.Column(db.String(50), default='info')  # info, warning, error, success
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    admin_id = db.Column(db.Integer, db.ForeignKey('admins.id'), nullable=True)
    task_id = db.Column(db.Integer, db.ForeignKey('scraping_tasks.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'log_type': self.log_type,
            'message': self.message,
            'details': self.details,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class Settings(db.Model):
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text, nullable=False)
    setting_type = db.Column(db.String(20), default='string')  # string, int, bool, json
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
