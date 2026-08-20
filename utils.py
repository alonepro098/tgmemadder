from datetime import datetime
import json
import logging
import asyncio
import pandas as pd
from database import db, UserSession, ScrapingTask, BroadcastMessage, SystemLog, Settings
from telegram_api import TelegramAPI
from config import Config

logger = logging.getLogger(__name__)

class TaskManager:
    @staticmethod
    def process_task(task_id):
        """Process a scraping and member adding task with real-time updates"""
        from app import create_app
        app = create_app()
        
        with app.app_context():
            task = ScrapingTask.query.get(task_id)
            if not task:
                return {'status': 'error', 'message': 'Task not found'}
            
            try:
                session = UserSession.query.get(task.user_session_id)
                if not session or not session.is_active:
                    task.status = 'failed'
                    task.error_message = 'Active user session required'
                    db.session.commit()
                    return {'status': 'error', 'message': 'Active user session required'}
                
                telegram = TelegramAPI(Config.API_ID, Config.API_HASH)
                
                task.status = 'running'
                task.started_at = datetime.utcnow()
                task.progress = 10
                db.session.commit()
                
                LogManager.log('info', f"Started scraping task #{task.id}", task_id=task.id)
                
                # Fetch entities
                source_res = asyncio.run(telegram.get_entity_from_link(session.session_string, task.source_group_link))
                target_res = asyncio.run(telegram.get_entity_from_link(session.session_string, task.target_group_link))
                
                filters = json.loads(task.filter_keywords) if task.filter_keywords else []
                excludes = json.loads(task.exclude_keywords) if task.exclude_keywords else []
                
                # Step 1: Scrape
                members, filtered_out = asyncio.run(
                    telegram.scrape_members_advanced(
                        session.session_string,
                        source_res['entity'],
                        limit=task.max_members,
                        filter_keywords=filters,
                        exclude_keywords=excludes
                    )
                )
                
                task.members_scraped = len(members)
                task.progress = 40
                db.session.commit()
                
                LogManager.log('info', f"Scraped {len(members)} members from {task.source_group_link}", task_id=task.id)
                
                if not members:
                    task.status = 'completed'
                    task.progress = 100
                    task.completed_at = datetime.utcnow()
                    db.session.commit()
                    return {'status': 'success', 'scraped': 0, 'added': 0, 'failed': 0}

                # Real-time progress callback
                async def update_add_progress(current_idx, total_count, current_added, current_failed):
                    with app.app_context():
                        t = ScrapingTask.query.get(task_id)
                        if t:
                            t.members_added = current_added
                            t.members_failed = current_failed
                            t.progress = 40 + int((current_idx / total_count) * 60)
                            db.session.commit()

                # Step 2: Add Members with real-time callback
                added, failed, failed_members = asyncio.run(
                    telegram.add_members_with_delay(
                        session.session_string,
                        target_res['entity'],
                        members,
                        delay=task.delay_between_adds,
                        progress_callback=update_add_progress
                    )
                )
                
                task.members_added = added
                task.members_failed = failed
                task.duplicates_found = len(members) - added - failed
                task.status = 'completed'
                task.progress = 100
                task.completed_at = datetime.utcnow()
                db.session.commit()
                
                LogManager.log('success', f"Task #{task.id} completed: {added} added, {failed} failed.", task_id=task.id)
                
                return {
                    'status': 'success',
                    'scraped': len(members),
                    'added': added,
                    'failed': failed
                }
                
            except Exception as e:
                logger.error(f"Task #{task_id} failed: {e}")
                task.status = 'failed'
                task.error_message = str(e)
                db.session.commit()
                LogManager.log('error', f"Task #{task.id} failed: {str(e)}", task_id=task.id)
                return {'status': 'error', 'message': str(e)}

class BroadcastManager:
    @staticmethod
    def process_broadcast(broadcast_id):
        """Process broadcast message task"""
        from app import create_app
        app = create_app()
        with app.app_context():
            bm = BroadcastMessage.query.get(broadcast_id)
            if not bm:
                return {'status': 'error', 'message': 'Broadcast not found'}
            bm.status = 'completed'
            db.session.commit()
            return {'status': 'success'}

class LogManager:
    @staticmethod
    def log(log_type, message, details=None, admin_id=None, task_id=None):
        """Add system log entry"""
        try:
            log_entry = SystemLog(
                log_type=log_type,
                message=message,
                details=details,
                admin_id=admin_id,
                task_id=task_id
            )
            db.session.add(log_entry)
            db.session.commit()
            return log_entry
        except Exception as e:
            logger.error(f"Logging error: {e}")

class ExcelExporter:
    @staticmethod
    def export_members_to_excel(members, filename='members.xlsx'):
        """Export member records to an Excel spreadsheet"""
        df = pd.DataFrame(members)
        df.to_excel(filename, index=False)
        return filename

class SchedulerManager:
    @staticmethod
    def run_scheduled_tasks():
        """Run scheduled background maintenance tasks"""
        SessionManager.cleanup_expired_sessions()

class SessionManager:
    @staticmethod
    def cleanup_expired_sessions():
        """Cleanup expired or inactive user sessions"""
        from app import create_app
        app = create_app()
        with app.app_context():
            now = datetime.utcnow()
            expired = UserSession.query.filter(
                UserSession.expiry_date.isnot(None),
                UserSession.expiry_date < now
            ).all()
            
            for session in expired:
                session.is_active = False
            
            db.session.commit()
            return len(expired)
