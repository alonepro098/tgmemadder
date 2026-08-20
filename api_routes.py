from flask import Blueprint, request, jsonify
from flask_login import login_required
from database import db, UserSession, ScrapingTask, SystemLog, Settings
from telegram_api import TelegramAPI
from utils import TaskManager, LogManager
import asyncio
import json
import threading

api_bp = Blueprint('api', __name__)

@api_bp.route('/sessions/request_code', methods=['POST'])
@login_required
def request_code():
    data = request.json or {}
    phone = data.get('phone_number')
    if not phone:
        return jsonify({'status': 'error', 'message': 'Phone number is required'}), 400
        
    try:
        tg = TelegramAPI()
        res = asyncio.run(tg.send_code_request(phone))
        return jsonify(res)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@api_bp.route('/sessions/login_code', methods=['POST'])
@login_required
def login_code():
    data = request.json or {}
    phone = data.get('phone_number')
    phone_code_hash = data.get('phone_code_hash')
    code = data.get('code')
    temp_session = data.get('session_string')
    
    if not all([phone, phone_code_hash, code, temp_session]):
        return jsonify({'status': 'error', 'message': 'Missing parameters'}), 400
        
    try:
        tg = TelegramAPI()
        res = asyncio.run(tg.sign_in_with_code(phone, phone_code_hash, code, temp_session))
        
        if res.get('status') == 'success':
            session_entry = UserSession(
                phone_number=phone,
                session_string=res['session_string'],
                is_active=True
            )
            db.session.add(session_entry)
            db.session.commit()
            LogManager.log('success', f"Added new Telegram session for phone {phone}")
            
        return jsonify(res)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@api_bp.route('/sessions/add_string', methods=['POST'])
@login_required
def add_string_session():
    data = request.json or {}
    phone = data.get('phone_number')
    session_str = data.get('session_string')
    
    if not phone or not session_str:
        return jsonify({'status': 'error', 'message': 'Phone number and session string are required'}), 400
        
    try:
        session_entry = UserSession.query.filter_by(phone_number=phone).first()
        if not session_entry:
            session_entry = UserSession(phone_number=phone, session_string=session_str, is_active=True)
            db.session.add(session_entry)
        else:
            session_entry.session_string = session_str
            session_entry.is_active = True
            
        db.session.commit()
        LogManager.log('success', f"Session string saved for {phone}")
        return jsonify({'status': 'success', 'message': 'Session added successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@api_bp.route('/sessions/<int:session_id>/delete', methods=['POST'])
@login_required
def delete_session(session_id):
    sess = UserSession.query.get_or_404(session_id)
    db.session.delete(sess)
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Session deleted'})

@api_bp.route('/tasks/create', methods=['POST'])
@login_required
def create_task():
    data = request.json or {}
    name = data.get('name', 'Scrape & Add Task')
    source = data.get('source_group_link')
    target = data.get('target_group_link')
    session_id = data.get('user_session_id')
    max_members = int(data.get('max_members', 500))
    delay = int(data.get('delay_between_adds', 3))
    filters = data.get('filter_keywords', [])
    excludes = data.get('exclude_keywords', [])
    
    if not source or not target or not session_id:
        return jsonify({'status': 'error', 'message': 'Source group, target group, and user session are required'}), 400
        
    task = ScrapingTask(
        name=name,
        source_group_link=source,
        target_group_link=target,
        user_session_id=session_id,
        max_members=max_members,
        delay_between_adds=delay,
        filter_keywords=json.dumps(filters) if isinstance(filters, list) else filters,
        exclude_keywords=json.dumps(excludes) if isinstance(excludes, list) else excludes,
        status='pending'
    )
    db.session.add(task)
    db.session.commit()
    
    # Try Celery task or run background thread fallback
    try:
        from app import process_scrape_task
        process_scrape_task.delay(task.id)
    except Exception:
        # Fallback to threading if Celery/Redis is not running
        thread = threading.Thread(target=TaskManager.process_task, args=(task.id,))
        thread.daemon = True
        thread.start()
        
    return jsonify({'status': 'success', 'task_id': task.id, 'message': 'Task created and started'})

@api_bp.route('/tasks/<int:task_id>/status', methods=['GET'])
@login_required
def task_status(task_id):
    task = ScrapingTask.query.get_or_404(task_id)
    return jsonify(task.to_dict())

@api_bp.route('/tasks/<int:task_id>/cancel', methods=['POST'])
@login_required
def cancel_task(task_id):
    task = ScrapingTask.query.get_or_404(task_id)
    task.status = 'cancelled'
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Task cancelled'})
