from datetime import datetime
import json
import logging
from database import db, UserSession, ScrapingTask, BroadcastMessage, SystemLog
from telegram_api import TelegramAPI
from config import Config
import pandas as pd
from openpyxl import Workbook
import asyncio

logger = logging.getLogger(__name__)

class TaskManager:
    @staticmethod
    def process_task(task_id):
        """Process a scraping task"""
        from app import create_app
        app = create_app()
        
        with app.app_context():
            task = ScrapingTask.query.get(task_id)
            if not task:
                return {'status': 'error', 'message': 'Task not found'}
            
            try:
                telegram = TelegramAPI(Config.API_ID, Config.API_HASH)
                session = UserSession.query.get(task.user_session_id)
                
                task.status = 'running'
                task.started_at = datetime.utcnow()
                db.session.commit()
                
                # Get entities
                source_info = telegram.get_entity_from_link(session.session_string, task.source_group_link)
                target_info = telegram.get_entity_from_link(session.session_string, task.target_group_link)
                
                # Parse filters
                filters = json.loads(task.filter_keywords) if task.filter_keywords else []
                excludes = json.loads(task.exclude_keywords) if task.exclude_keywords else []
                
                # Scrape members
                members, filtered = asyncio.run(
                    telegram.scrape_members_advanced(
                        session.session_string,
                        source_info['entity'],
                        limit=task.max_members,
                        filter_keywords=filters,
                        exclude_keywords=excludes
                    )
                )
                
                task.members_scraped = len(members)
                task.progress = 30
                db.session.commit()
                
                # Add members
                added, failed, failed_members = asyncio.run(
                    telegram.add_members_with_delay(
                        session.session_string,
                        target_info['entity'],
                        members,
                        delay=task.delay_between_adds
                    )
                )
                
                # Update task
                task.members_added = added
                task.members_failed = failed
                task.duplicates_found = len(members) - added - failed
                task.status = 'completed'
                task.progress = 100
                task.completed_at = datetime.utcnow()
                db.session.commit()
                
                return {
                    'status': 'success',
                    'scraped': len(members),
                    'added': added,
                    'failed': failed
                }
                
            except Exception as e:
                task.status = 'failed'
                task.error_message = str(e)
                db.session.commit()
                return {'status': 'error', 'message': str(e)}

class LogManager:
    @staticmethod
    def log(log_type, message, details=None, admin_id=None, task_id=None):
        """Add system log entry"""
        log = SystemLog(
            log_type=log_type,
            message=message,
            details=details,
            admin_id=admin_id,
            task_id=task_id
        )
        db.session.add(log)
        db.session.commit()
        return log

class ExcelExporter:
    @staticmethod
    def export_members_to_excel(members, filename='members.xlsx'):
        """Export members to Excel"""
        df = pd.DataFrame(members)
        df.to_excel(filename, index=False)
        return filename

class SchedulerManager:
    @staticmethod
    def run_scheduled_tasks():
        """Run scheduled tasks"""
        # Implementation for scheduled tasks
        pass

class SessionManager:
    @staticmethod
    def cleanup_expired_sessions():
        """Cleanup expired sessions"""
        expired = UserSession.query.filter(
            UserSession.expiry_date < datetime.utcnow()
        ).all()
        
        for session in expired:
            session.is_active = False
        
        db.session.commit()
        return len(expired)
