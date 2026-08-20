from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_user, logout_user, login_required, current_user
from database import db, Admin, UserSession, ScrapingTask, SystemLog, Settings
from utils import LogManager, ExcelExporter
import bcrypt
import json
import os

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    total_sessions = UserSession.query.count()
    active_sessions = UserSession.query.filter_by(is_active=True).count()
    total_tasks = ScrapingTask.query.count()
    completed_tasks = ScrapingTask.query.filter_by(status='completed').count()
    running_tasks = ScrapingTask.query.filter_by(status='running').count()
    
    # Calculate stats
    all_completed = ScrapingTask.query.all()
    total_scraped = sum(t.members_scraped for t in all_completed)
    total_added = sum(t.members_added for t in all_completed)
    
    recent_tasks = ScrapingTask.query.order_by(ScrapingTask.created_at.desc()).limit(5).all()
    recent_logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(5).all()
    
    return render_template(
        'dashboard.html',
        total_sessions=total_sessions,
        active_sessions=active_sessions,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        running_tasks=running_tasks,
        total_scraped=total_scraped,
        total_added=total_added,
        recent_tasks=recent_tasks,
        recent_logs=recent_logs
    )

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        if admin and bcrypt.checkpw(password.encode('utf-8'), admin.password_hash.encode('utf-8')):
            login_user(admin)
            LogManager.log('info', f"Admin {admin.username} logged in", admin_id=admin.id)
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            
    return render_template('login.html')

@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/tasks')
@login_required
def tasks():
    all_tasks = ScrapingTask.query.order_by(ScrapingTask.created_at.desc()).all()
    active_sessions = UserSession.query.filter_by(is_active=True).all()
    return render_template('tasks.html', tasks=all_tasks, sessions=active_sessions)

@admin_bp.route('/sessions')
@login_required
def sessions():
    all_sessions = UserSession.query.order_by(UserSession.created_at.desc()).all()
    return render_template('sessions.html', sessions=all_sessions)

@admin_bp.route('/logs')
@login_required
def logs():
    all_logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(200).all()
    return render_template('logs.html', logs=all_logs)

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        for key in request.form:
            setting = Settings.query.filter_by(setting_key=key).first()
            if setting:
                setting.setting_value = request.form[key]
            else:
                setting = Settings(setting_key=key, setting_value=request.form[key])
                db.session.add(setting)
        db.session.commit()
        flash('Settings saved successfully', 'success')
        return redirect(url_for('admin.settings'))
        
    all_settings = {s.setting_key: s.setting_value for s in Settings.query.all()}
    return render_template('settings.html', settings=all_settings)

@admin_bp.route('/export/<int:task_id>')
@login_required
def export_task(task_id):
    task = ScrapingTask.query.get_or_404(task_id)
    # Generate dummy/cached export if members saved or create report
    members_data = [
        {'Task ID': task.id, 'Source Group': task.source_group_link, 'Target Group': task.target_group_link,
         'Scraped': task.members_scraped, 'Added': task.members_added, 'Failed': task.members_failed, 'Status': task.status}
    ]
    filename = f"task_{task_id}_report.xlsx"
    filepath = os.path.join(os.getcwd(), filename)
    ExcelExporter.export_members_to_excel(members_data, filepath)
    return send_file(filepath, as_attachment=True)
