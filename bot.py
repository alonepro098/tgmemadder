import asyncio
import logging
import os
import json
from datetime import datetime

from telethon import TelegramClient, events, Button, errors
from telethon.sessions import StringSession

from config import Config
from database import db, UserSession, ScrapingTask, SystemLog, Settings
from telegram_api import TelegramAPI
from utils import TaskManager, LogManager, ExcelExporter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# State storage for multi-step conversations
USER_STATES = {}

def get_db_app():
    from app import create_app
    return create_app()

app = get_db_app()

def get_main_menu_buttons():
    return [
        [Button.inline("📱 Sessions", b"menu_sessions"), Button.inline("🚀 New Task", b"menu_new_task")],
        [Button.inline("📊 Task Status", b"menu_status"), Button.inline("📥 Export Excel", b"menu_export")],
        [Button.inline("📋 System Logs", b"menu_logs"), Button.inline("⚙️ Settings", b"menu_settings")]
    ]

async def start_bot():
    if not Config.BOT_TOKEN:
        print("[!] ERROR: BOT_TOKEN is missing in .env file! Please set BOT_TOKEN.")
        return

    bot = TelegramClient('bot_session', Config.API_ID, Config.API_HASH)
    await bot.start(bot_token=Config.BOT_TOKEN)
    print("🤖 Telegram Member Adder Bot is online and listening!")

    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        sender = await event.get_sender()
        welcome_text = (
            f"👋 **Welcome {sender.first_name} to Telegram Member Adder Bot!**\n\n"
            f"Power-packed Telegram group member scraper and auto-adder tool.\n"
            f"Select an option from the menu below to get started:"
        )
        USER_STATES[event.chat_id] = {}
        await event.respond(welcome_text, buttons=get_main_menu_buttons())

    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        chat_id = event.chat_id
        data = event.data

        if data == b"menu_main":
            USER_STATES[chat_id] = {}
            await event.edit("⚡ **Main Menu**\nSelect an option below:", buttons=get_main_menu_buttons())

        elif data == b"menu_sessions":
            with app.app_context():
                sessions = UserSession.query.all()
                text = "📱 **Registered Telegram Sessions**\n\n"
                if not sessions:
                    text += "No active Telegram sessions found."
                else:
                    for s in sessions:
                        status = "✅ Active" if s.is_active else "❌ Inactive"
                        text += f"• **{s.phone_number}** ({status}) - ID: {s.id}\n"

                buttons = [
                    [Button.inline("➕ Add Session (Phone OTP)", b"session_add_otp")],
                    [Button.inline("🔑 Add String Session", b"session_add_string")],
                    [Button.inline("🔙 Back to Menu", b"menu_main")]
                ]
                await event.edit(text, buttons=buttons)

        elif data == b"session_add_otp":
            USER_STATES[chat_id] = {'step': 'WAITING_PHONE'}
            await event.edit(
                "📱 **Add Telegram Session via Phone OTP**\n\n"
                "Please send your Telegram phone number with country code (e.g. `+919876543210`):",
                buttons=[[Button.inline("❌ Cancel", b"menu_main")]]
            )

        elif data == b"session_add_string":
            USER_STATES[chat_id] = {'step': 'WAITING_STRING_PHONE'}
            await event.edit(
                "🔑 **Add Telethon String Session**\n\n"
                "Please send phone number first (e.g. `+919876543210`):",
                buttons=[[Button.inline("❌ Cancel", b"menu_main")]]
            )

        elif data == b"menu_new_task":
            with app.app_context():
                sessions = UserSession.query.filter_by(is_active=True).all()
                if not sessions:
                    await event.edit(
                        "⚠️ **No active Telegram sessions!**\n"
                        "Please add a Telegram session first before creating a task.",
                        buttons=[[Button.inline("➕ Add Session", b"session_add_otp")], [Button.inline("🔙 Back", b"menu_main")]]
                    )
                    return
                
                buttons = []
                for s in sessions:
                    buttons.append([Button.inline(f"📱 {s.phone_number}", f"select_sess_{s.id}".encode())])
                buttons.append([Button.inline("❌ Cancel", b"menu_main")])

                await event.edit("🚀 **New Task: Step 1/4**\nSelect Telegram Session to use for scraping/adding:", buttons=buttons)

        elif data.startswith(b"select_sess_"):
            sess_id = int(data.decode().split("_")[-1])
            USER_STATES[chat_id] = {'step': 'WAITING_SOURCE_LINK', 'session_id': sess_id}
            await event.edit(
                "🚀 **New Task: Step 2/4**\n\n"
                "Send the **Source Group/Channel Link or Username** (e.g., `@sourcegroup` or `https://t.me/sourcegroup`):",
                buttons=[[Button.inline("❌ Cancel", b"menu_main")]]
            )

        elif data == b"menu_status":
            with app.app_context():
                tasks = ScrapingTask.query.order_by(ScrapingTask.created_at.desc()).limit(5).all()
                if not tasks:
                    await event.edit("📊 **Task Status**\n\nNo tasks found.", buttons=[[Button.inline("🔙 Back", b"menu_main")]])
                    return

                text = "📊 **Recent Tasks Status**\n\n"
                buttons = []
                for t in tasks:
                    text += (
                        f"• **Task #{t.id}**: {t.name}\n"
                        f"  Status: `{t.status}` | Progress: `{t.progress}%`\n"
                        f"  Scraped: `{t.members_scraped}` | Added: `{t.members_added}` | Failed: `{t.members_failed}`\n\n"
                    )
                    if t.status in ['running', 'pending']:
                        buttons.append([Button.inline(f"🛑 Cancel Task #{t.id}", f"cancel_task_{t.id}".encode())])
                
                buttons.append([Button.inline("🔄 Refresh", b"menu_status")])
                buttons.append([Button.inline("🔙 Back to Menu", b"menu_main")])
                await event.edit(text, buttons=buttons)

        elif data.startswith(b"cancel_task_"):
            task_id = int(data.decode().split("_")[-1])
            with app.app_context():
                t = ScrapingTask.query.get(task_id)
                if t:
                    t.status = 'cancelled'
                    db.session.commit()
            await event.answer("Task cancelled!", alert=True)
            await event.edit("Task cancelled successfully.", buttons=[[Button.inline("🔙 Back", b"menu_status")]])

        elif data == b"menu_export":
            with app.app_context():
                tasks = ScrapingTask.query.filter(ScrapingTask.members_scraped > 0).all()
                if not tasks:
                    await event.edit("📥 **Export Excel**\n\nNo completed task records found to export.", buttons=[[Button.inline("🔙 Back", b"menu_main")]])
                    return

                buttons = []
                for t in tasks:
                    buttons.append([Button.inline(f"📄 Task #{t.id} ({t.members_scraped} members)", f"do_export_{t.id}".encode())])
                buttons.append([Button.inline("🔙 Back", b"menu_main")])
                await event.edit("📥 **Select Task to Export Excel Report:**", buttons=buttons)

        elif data.startswith(b"do_export_"):
            task_id = int(data.decode().split("_")[-1])
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
                    await bot.send_file(chat_id, filepath, caption=f"📊 **Excel Report for Task #{t.id}**")
                    await event.answer("File sent!", alert=True)

        elif data == b"menu_logs":
            with app.app_context():
                logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(8).all()
                text = "📋 **Recent System Logs**\n\n"
                for l in logs:
                    text += f"• `{l.created_at.strftime('%H:%M:%S')}` **[{l.log_type.upper()}]** {l.message}\n"
                await event.edit(text, buttons=[[Button.inline("🔄 Refresh", b"menu_logs")], [Button.inline("🔙 Back", b"menu_main")]])

        elif data == b"menu_settings":
            with app.app_context():
                st = {s.setting_key: s.setting_value for s in Settings.query.all()}
                text = (
                    "⚙️ **System Settings**\n\n"
                    f"• **Default Delay**: `{st.get('default_delay', '3')}`s\n"
                    f"• **Max Members**: `{st.get('max_members', '1000')}`\n"
                    f"• **Safe Mode**: `{st.get('safe_mode', 'true')}`\n"
                )
                await event.edit(text, buttons=[[Button.inline("🔙 Back to Menu", b"menu_main")]])

    @bot.on(events.NewMessage)
    async def message_handler(event):
        if event.text.startswith('/'):
            return
        
        chat_id = event.chat_id
        state = USER_STATES.get(chat_id, {})
        step = state.get('step')
        text = event.text.strip()

        if step == 'WAITING_PHONE':
            USER_STATES[chat_id]['phone'] = text
            await event.respond("⏳ Sending Telegram verification code...")
            try:
                tg = TelegramAPI()
                res = await tg.send_code_request(text)
                USER_STATES[chat_id]['phone_code_hash'] = res['phone_code_hash']
                USER_STATES[chat_id]['temp_session'] = res['session_string']
                USER_STATES[chat_id]['step'] = 'WAITING_OTP'
                await event.respond("📩 **OTP Sent!** Please enter the verification code received on Telegram:")
            except Exception as e:
                await event.respond(f"❌ Error sending code: {e}", buttons=[[Button.inline("🔙 Main Menu", b"menu_main")]])

        elif step == 'WAITING_OTP':
            phone = USER_STATES[chat_id]['phone']
            pch = USER_STATES[chat_id]['phone_code_hash']
            ts = USER_STATES[chat_id]['temp_session']
            await event.respond("⏳ Verifying OTP...")
            try:
                tg = TelegramAPI()
                res = await tg.sign_in_with_code(phone, pch, text, ts)
                if res.get('status') == 'success':
                    with app.app_context():
                        sess = UserSession(phone_number=phone, session_string=res['session_string'], is_active=True)
                        db.session.add(sess)
                        db.session.commit()
                    USER_STATES[chat_id] = {}
                    await event.respond("✅ **Session added successfully!**", buttons=get_main_menu_buttons())
                elif res.get('status') == 'password_needed':
                    USER_STATES[chat_id]['step'] = 'WAITING_2FA'
                    await event.respond("🔒 **2FA Password Required!** Please enter your Telegram 2FA password:")
            except Exception as e:
                await event.respond(f"❌ Verification failed: {e}", buttons=[[Button.inline("🔙 Main Menu", b"menu_main")]])

        elif step == 'WAITING_STRING_PHONE':
            USER_STATES[chat_id]['phone'] = text
            USER_STATES[chat_id]['step'] = 'WAITING_STRING'
            await event.respond("🔑 Now send the Telethon **Session String**:")

        elif step == 'WAITING_STRING':
            phone = USER_STATES[chat_id]['phone']
            with app.app_context():
                sess = UserSession(phone_number=phone, session_string=text, is_active=True)
                db.session.add(sess)
                db.session.commit()
            USER_STATES[chat_id] = {}
            await event.respond("✅ **String session saved!**", buttons=get_main_menu_buttons())

        elif step == 'WAITING_SOURCE_LINK':
            USER_STATES[chat_id]['source_link'] = text
            USER_STATES[chat_id]['step'] = 'WAITING_TARGET_LINK'
            await event.respond("🚀 **New Task: Step 3/4**\nSend the **Target Group/Channel Link or Username**:")

        elif step == 'WAITING_TARGET_LINK':
            USER_STATES[chat_id]['target_link'] = text
            USER_STATES[chat_id]['step'] = 'WAITING_MAX_MEMBERS'
            await event.respond("🚀 **New Task: Step 4/4**\nSend **Max Members to Scrape** (e.g., `500`):")

        elif step == 'WAITING_MAX_MEMBERS':
            try:
                max_m = int(text)
            except ValueError:
                max_m = 500

            session_id = USER_STATES[chat_id]['session_id']
            source = USER_STATES[chat_id]['source_link']
            target = USER_STATES[chat_id]['target_link']

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

            USER_STATES[chat_id] = {}
            await event.respond(
                f"🚀 **Task #{task_id} Created & Started!**\n"
                f"• Source: `{source}`\n"
                f"• Target: `{target}`\n"
                f"• Max Members: `{max_m}`\n\n"
                f"Use **Task Status** button to monitor live progress.",
                buttons=get_main_menu_buttons()
            )

            # Start background processing
            asyncio.create_task(run_background_task(task_id))

    await bot.run_until_disconnected()

async def run_background_task(task_id):
    await asyncio.to_thread(TaskManager.process_task, task_id)

if __name__ == '__main__':
    asyncio.run(start_bot())
