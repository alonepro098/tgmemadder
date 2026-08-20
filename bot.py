import sys
import os
import logging
import asyncio
from datetime import datetime

# Force UTF-8 stdout encoding for Windows console compatibility
sys.stdout.reconfigure(encoding='utf-8')

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

from config import Config
from database import db, UserSession, ScrapingTask, SystemLog, Settings
from telegram_api import TelegramAPI
from utils import TaskManager, LogManager, ExcelExporter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Conversation states
(
    WAITING_PHONE,
    WAITING_OTP,
    WAITING_2FA,
    WAITING_STRING_PHONE,
    WAITING_STRING,
    WAITING_SOURCE_LINK,
    WAITING_TARGET_LINK,
    WAITING_MAX_MEMBERS,
) = range(8)

def get_db_app():
    from app import create_app
    return create_app()

app = get_db_app()

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 Sessions", callback_data="menu_sessions"), InlineKeyboardButton("🚀 New Task", callback_data="menu_new_task")],
        [InlineKeyboardButton("📊 Task Status", callback_data="menu_status"), InlineKeyboardButton("📥 Export Excel", callback_data="menu_export")],
        [InlineKeyboardButton("📋 System Logs", callback_data="menu_logs"), InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def escape_markdown(text):
    """Safely sanitize text for Markdown parsing"""
    if not text:
        return ""
    for char in ['_', '*', '`', '[']:
        text = text.replace(char, f'\\{char}')
    return text

async def safe_edit_message(query, text, reply_markup=None):
    """Safely edit query message handling Markdown parse errors and unmodified errors"""
    try:
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
    except Exception as e:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except Exception:
            pass

async def render_sessions_menu(query):
    with app.app_context():
        sessions = UserSession.query.all()
        text = "📱 **Registered Telegram Sessions**\n\n"
        keyboard = []
        if not sessions:
            text += "No active Telegram sessions found."
        else:
            for s in sessions:
                status = "✅ Active" if s.is_active else "❌ Inactive"
                text += f"• **{s.phone_number}** ({status}) - ID: `{s.id}`\n"
                keyboard.append([InlineKeyboardButton(f"🗑 Remove Session {s.phone_number}", callback_data=f"delete_session_{s.id}")])

        keyboard.append([InlineKeyboardButton("➕ Add Session (Phone OTP)", callback_data="session_add_otp")])
        keyboard.append([InlineKeyboardButton("🔑 Add String Session", callback_data="session_add_string")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_main")])
        await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    first_name = escape_markdown(user.first_name)
    welcome_text = (
        f"👋 **Welcome {first_name} to Telegram Member Adder Bot!**\n\n"
        f"Power-packed Telegram group member scraper and auto-adder tool.\n"
        f"Select an option from the menu below to get started:"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())
    elif update.callback_query:
        await safe_edit_message(update.callback_query, welcome_text, reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_main":
        context.user_data.clear()
        await safe_edit_message(query, "⚡ **Main Menu**\nSelect an option below:", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    elif data == "menu_sessions":
        await render_sessions_menu(query)
        return ConversationHandler.END

    elif data.startswith("delete_session_"):
        sess_id = int(data.split("_")[-1])
        with app.app_context():
            ScrapingTask.query.filter_by(user_session_id=sess_id).delete()
            sess = UserSession.query.get(sess_id)
            if sess:
                phone_num = sess.phone_number
                db.session.delete(sess)
                db.session.commit()
                await query.answer(f"Session {phone_num} removed!", show_alert=True)
            else:
                await query.answer("Session not found!", show_alert=True)
        
        await render_sessions_menu(query)
        return ConversationHandler.END

    elif data == "session_add_otp":
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="menu_main")]]
        await safe_edit_message(
            query,
            "📱 **Add Telegram Session via Phone OTP**\n\n"
            "Please send your Telegram phone number with country code (e.g. `+919876543210`):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_PHONE

    elif data == "session_add_string":
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="menu_main")]]
        await safe_edit_message(
            query,
            "🔑 **Add Telethon String Session**\n\n"
            "Please send phone number first (e.g. `+919876543210`):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_STRING_PHONE

    elif data == "menu_new_task":
        with app.app_context():
            sessions = UserSession.query.filter_by(is_active=True).all()
            if not sessions:
                keyboard = [[InlineKeyboardButton("➕ Add Session", callback_data="session_add_otp")], [InlineKeyboardButton("🔙 Back", callback_data="menu_main")]]
                await safe_edit_message(
                    query,
                    "⚠️ **No active Telegram sessions!**\n"
                    "Please add a Telegram session first before creating a task.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return ConversationHandler.END

            keyboard = []
            for s in sessions:
                keyboard.append([InlineKeyboardButton(f"📱 {s.phone_number}", callback_data=f"select_sess_{s.id}")])
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="menu_main")])

            await safe_edit_message(query, "🚀 **New Task: Step 1/4**\nSelect Telegram Session to use for scraping/adding:", reply_markup=InlineKeyboardMarkup(keyboard))
            return ConversationHandler.END

    elif data.startswith("select_sess_"):
        sess_id = int(data.split("_")[-1])
        context.user_data['session_id'] = sess_id
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="menu_main")]]
        await safe_edit_message(
            query,
            "🚀 **New Task: Step 2/4**\n\n"
            "Send the **Source Group/Channel Link or Username** (e.g., `@sourcegroup` or `https://t.me/sourcegroup`):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WAITING_SOURCE_LINK

    elif data == "menu_status":
        with app.app_context():
            tasks = ScrapingTask.query.order_by(ScrapingTask.created_at.desc()).limit(5).all()
            if not tasks:
                await safe_edit_message(query, "📊 **Task Status**\n\nNo tasks found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_main")]]))
                return ConversationHandler.END

            text = "📊 **Recent Tasks Status**\n\n"
            keyboard = []
            for t in tasks:
                t_name = escape_markdown(t.name)
                text += (
                    f"• **Task #{t.id}**: {t_name}\n"
                    f"  Status: `{t.status}` | Progress: `{t.progress}%`\n"
                    f"  Scraped: `{t.members_scraped}` | Added: `{t.members_added}` | Failed: `{t.members_failed}`\n\n"
                )
                if t.status in ['running', 'pending']:
                    keyboard.append([InlineKeyboardButton(f"🛑 Cancel Task #{t.id}", callback_data=f"cancel_task_{t.id}")])
            
            keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="menu_status")])
            keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_main")])
            await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
            return ConversationHandler.END

    elif data.startswith("cancel_task_"):
        task_id = int(data.split("_")[-1])
        with app.app_context():
            t = ScrapingTask.query.get(task_id)
            if t:
                t.status = 'cancelled'
                db.session.commit()
        await query.answer("Task cancelled!")
        await safe_edit_message(query, "Task cancelled successfully.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_status")]]))
        return ConversationHandler.END

    elif data == "menu_export":
        with app.app_context():
            tasks = ScrapingTask.query.filter(ScrapingTask.members_scraped > 0).all()
            if not tasks:
                await safe_edit_message(query, "📥 **Export Excel**\n\nNo completed task records found to export.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_main")]]))
                return ConversationHandler.END

            keyboard = []
            for t in tasks:
                keyboard.append([InlineKeyboardButton(f"📄 Task #{t.id} ({t.members_scraped} members)", callback_data=f"do_export_{t.id}")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
            await safe_edit_message(query, "📥 **Select Task to Export Excel Report:**", reply_markup=InlineKeyboardMarkup(keyboard))
            return ConversationHandler.END

    elif data.startswith("do_export_"):
        task_id = int(data.split("_")[-1])
        with app.app_context():
            t = ScrapingTask.query.get(task_id)
            if t:
                report_data = [{
                    'Task ID': t.id,
                    'Task Name': t.name,
                    'Source Link': t.source_group_link,
                    'Target Link': t.target_group_link,
                    'Scraped': t.members_scraped,
                    'Added': t.members_added,
                    'Failed': t.members_failed,
                    'Status': t.status
                }]
                filename = f"task_{t.id}_report.xlsx"
                filepath = os.path.join(os.getcwd(), filename)
                ExcelExporter.export_members_to_excel(report_data, filepath)
                with open(filepath, 'rb') as doc:
                    await context.bot.send_document(chat_id=update.effective_chat.id, document=doc, caption=f"📊 **Excel Report for Task #{t.id}**", parse_mode='Markdown')
                await query.answer("File sent!")
        return ConversationHandler.END

    elif data == "menu_logs":
        with app.app_context():
            logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(8).all()
            text = "📋 **Recent System Logs**\n\n"
            for l in logs:
                msg = escape_markdown(l.message)
                text += f"• `{l.created_at.strftime('%H:%M:%S')}` **[{l.log_type.upper()}]** {msg}\n"
            keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="menu_logs")], [InlineKeyboardButton("🔙 Back", callback_data="menu_main")]]
            await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
            return ConversationHandler.END

    elif data == "menu_settings":
        with app.app_context():
            st = {s.setting_key: s.setting_value for s in Settings.query.all()}
            text = (
                "⚙️ **System Settings**\n\n"
                f"• **Default Delay**: `{st.get('default_delay', '3')}`s\n"
                f"• **Max Members**: `{st.get('max_members', '1000')}`\n"
                f"• **Safe Mode**: `{st.get('safe_mode', 'true')}`\n"
            )
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_main")]]
            await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
            return ConversationHandler.END

# OTP Handlers
async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data['phone'] = phone
    await update.message.reply_text("⏳ Sending Telegram verification code...")
    try:
        tg = TelegramAPI()
        res = await tg.send_code_request(phone)
        context.user_data['phone_code_hash'] = res['phone_code_hash']
        context.user_data['temp_session'] = res['session_string']
        await update.message.reply_text("📩 **OTP Sent!** Please enter the verification code received on Telegram:", parse_mode='Markdown')
        return WAITING_OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending code: {e}", reply_markup=get_main_keyboard())
        return ConversationHandler.END

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp = update.message.text.strip()
    phone = context.user_data['phone']
    pch = context.user_data['phone_code_hash']
    ts = context.user_data['temp_session']
    await update.message.reply_text("⏳ Verifying OTP...")
    try:
        tg = TelegramAPI()
        res = await tg.sign_in_with_code(phone, pch, otp, ts)
        
        if res.get('status') == 'success':
            with app.app_context():
                sess = UserSession.query.filter_by(phone_number=phone).first()
                if not sess:
                    sess = UserSession(phone_number=phone, session_string=res['session_string'], is_active=True)
                    db.session.add(sess)
                else:
                    sess.session_string = res['session_string']
                    sess.is_active = True
                db.session.commit()
            await update.message.reply_text("✅ **Session added successfully!**", parse_mode='Markdown', reply_markup=get_main_keyboard())
            return ConversationHandler.END
            
        elif res.get('status') == 'password_needed':
            context.user_data['temp_session'] = res['session_string']
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="menu_main")]]
            await update.message.reply_text(
                "🔒 **Two-Step Verification (2FA) is Enabled!**\n\n"
                "Please enter your Telegram 2FA Password below:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return WAITING_2FA
            
    except Exception as e:
        await update.message.reply_text(f"❌ Verification failed: {e}", reply_markup=get_main_keyboard())
        return ConversationHandler.END

async def handle_2fa_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    phone = context.user_data['phone']
    ts = context.user_data['temp_session']
    await update.message.reply_text("⏳ Verifying 2FA Password...")
    try:
        tg = TelegramAPI()
        res = await tg.sign_in_with_password(password, ts)
        if res.get('status') == 'success':
            with app.app_context():
                sess = UserSession.query.filter_by(phone_number=phone).first()
                if not sess:
                    sess = UserSession(phone_number=phone, session_string=res['session_string'], is_active=True)
                    db.session.add(sess)
                else:
                    sess.session_string = res['session_string']
                    sess.is_active = True
                db.session.commit()
            await update.message.reply_text("✅ **Session added successfully with 2FA!**", parse_mode='Markdown', reply_markup=get_main_keyboard())
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ 2FA Verification failed: {e}", reply_markup=get_main_keyboard())
        return ConversationHandler.END

# String Session Handlers
async def handle_string_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text.strip()
    await update.message.reply_text("🔑 Now send the Telethon **Session String**:", parse_mode='Markdown')
    return WAITING_STRING

async def handle_string_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_str = update.message.text.strip()
    phone = context.user_data['phone']
    with app.app_context():
        sess = UserSession.query.filter_by(phone_number=phone).first()
        if not sess:
            sess = UserSession(phone_number=phone, session_string=session_str, is_active=True)
            db.session.add(sess)
        else:
            sess.session_string = session_str
            sess.is_active = True
        db.session.commit()
    await update.message.reply_text("✅ **String session saved!**", parse_mode='Markdown', reply_markup=get_main_keyboard())
    return ConversationHandler.END

# Task Creation Handlers
async def handle_source_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['source_link'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="menu_main")]]
    await update.message.reply_text("🚀 **New Task: Step 3/4**\nSend the **Target Group/Channel Link or Username**:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_TARGET_LINK

async def handle_target_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['target_link'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="menu_main")]]
    await update.message.reply_text("🚀 **New Task: Step 4/4**\nSend **Max Members to Scrape** (e.g., `500`):", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    return WAITING_MAX_MEMBERS

async def handle_max_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        max_m = int(update.message.text.strip())
    except ValueError:
        max_m = 500

    session_id = context.user_data['session_id']
    source = context.user_data['source_link']
    target = context.user_data['target_link']

    with app.app_context():
        task = ScrapingTask(
            name=f"Task {source[:10]} -> {target[:10]}",
            source_group_link=source,
            target_group_link=target,
            user_session_id=session_id,
            max_members=max_m,
            delay_between_adds=3,
            status='pending'
        )
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    await update.message.reply_text(
        f"🚀 **Task #{task_id} Created & Started!**\n"
        f"• Source: `{source}`\n"
        f"• Target: `{target}`\n"
        f"• Max Members: `{max_m}`\n\n"
        f"Use **Task Status** button to monitor live progress.",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

    asyncio.create_task(run_background_task(task_id))
    return ConversationHandler.END

async def run_background_task(task_id):
    await asyncio.to_thread(TaskManager.process_task, task_id)

def main():
    if not Config.BOT_TOKEN:
        print("[!] ERROR: BOT_TOKEN missing in .env!")
        return

    print("🚀 Starting Telegram Bot...")
    req = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0)
    application = ApplicationBuilder().token(Config.BOT_TOKEN).request(req).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(menu_callback),
        ],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            WAITING_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_otp)],
            WAITING_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_password)],
            WAITING_STRING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_string_phone)],
            WAITING_STRING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_string_session)],
            WAITING_SOURCE_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_source_link)],
            WAITING_TARGET_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_target_link)],
            WAITING_MAX_MEMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_max_members)],
        },
        fallbacks=[CallbackQueryHandler(menu_callback)],
        per_message=False,
    )

    application.add_handler(conv_handler)
    print("🤖 Telegram Member Adder Bot is online and listening!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
