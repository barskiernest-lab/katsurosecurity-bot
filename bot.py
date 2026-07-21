import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import sqlite3
import logging
import csv
import io
import re
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    Message, CallbackQuery
)
from pyrogram.errors import FloodWait

API_ID = 36097445
API_HASH = "e34bc9a1990aa50b6f7d70dc57eacc15"
BOT_TOKEN = "8974338004:AAG5GpQhPJholUAgTF629NhZQfQ-T1HyBys"
ADMIN_USERNAMES = ["Xomka132"]
ADMIN_USER_IDS = []
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scammers.db")
SESSION_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "katsuro_user")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    for table_sql in [
        """CREATE TABLE IF NOT EXISTS scammers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, first_name TEXT,
            reason TEXT, added_by INTEGER, added_by_name TEXT, date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER, reporter_name TEXT,
            target_user_id INTEGER, target_username TEXT, target_name TEXT,
            reason TEXT, status TEXT DEFAULT 'pending', date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY, username TEXT, activated_date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, sub_type TEXT DEFAULT 'basic',
            start_date TEXT, end_date TEXT, active INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY, chat_title TEXT,
            scam_check INTEGER DEFAULT 1, welcome INTEGER DEFAULT 1,
            welcome_text TEXT DEFAULT 'Добро пожаловать!',
            log_enabled INTEGER DEFAULT 1, log_chat_id INTEGER DEFAULT 0,
            auto_reply INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS message_log (
            message_id INTEGER, chat_id INTEGER, user_id INTEGER,
            username TEXT, first_name TEXT, text TEXT, date TEXT,
            PRIMARY KEY (message_id, chat_id)
        )""",
        """CREATE TABLE IF NOT EXISTS auto_responder (
            chat_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0,
            delay_minutes INTEGER DEFAULT 60,
            response_text TEXT DEFAULT 'Автоматический ответ!'
        )""",
        """CREATE TABLE IF NOT EXISTS votes (
            poll_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            message_id INTEGER,
            target_username TEXT,
            target_user_id INTEGER,
            target_name TEXT,
            reason TEXT,
            yes_count INTEGER DEFAULT 0,
            no_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_by INTEGER,
            date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS vote_voters (
            poll_id INTEGER,
            user_id INTEGER,
            vote TEXT,
            PRIMARY KEY (poll_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, message_id INTEGER, chat_id INTEGER,
            target_username TEXT, reason TEXT, added INTEGER DEFAULT 0,
            date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY, username TEXT,
            first_name TEXT, last_active TEXT, date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS private_autoresponder (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 0,
            delay_seconds INTEGER DEFAULT 5,
            response_text TEXT DEFAULT 'Бот временно не отвечает. Попробуйте позже.'
        )""",
        """CREATE TABLE IF NOT EXISTS user_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, target_user_id INTEGER, target_username TEXT,
            active INTEGER DEFAULT 1, date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, target_user_id INTEGER, target_username TEXT,
            added_by_name TEXT, date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, checked_username TEXT, result TEXT, date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY, badge TEXT DEFAULT 'user',
            custom_status TEXT DEFAULT '', warns INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS user_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id INTEGER, target_username TEXT,
            tag TEXT, set_by INTEGER, set_by_name TEXT, date TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE, days INTEGER DEFAULT 7,
            used_by INTEGER, used_date TEXT, created_by TEXT, date TEXT
        )""",
    ]:
        c.execute(table_sql)
    conn.commit()
    conn.close()


def is_admin(user_id, username=None):
    if user_id in ADMIN_USER_IDS:
        return True
    if username and username in ADMIN_USERNAMES:
        return True
    return False


user_states = {}


def set_state(user_id, state, data=None):
    user_states[user_id] = {"state": state, "data": data or {}}


def get_state(user_id):
    return user_states.get(user_id)


def clear_state(user_id):
    user_states.pop(user_id, None)


def has_active_sub(user_id, username=None):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if username:
        c.execute("SELECT * FROM subscriptions WHERE (user_id=? OR username=?) AND active=1 AND end_date>?", (user_id, username, now))
    else:
        c.execute("SELECT * FROM subscriptions WHERE user_id=? AND active=1 AND end_date>?", (user_id, now))
    row = c.fetchone()
    conn.close()
    return row is not None


def sub_required(user):
    if is_admin(user.id, user.username):
        return False
    if not has_active_sub(user.id, getattr(user, 'username', None)):
        return True
    return False


def get_group_settings(chat_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,))
        row = c.fetchone()
    conn.close()
    return row


def update_group_setting(chat_id, key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE group_settings SET {key}=? WHERE chat_id=?", (value, chat_id))
    conn.commit()
    conn.close()


# ── LOG ALL MESSAGES ──
@app.on_message(filters.group & ~filters.service, group=-1)
async def log_messages(client, message: Message):
    if not message.from_user:
        return
    user = message.from_user
    chat = message.chat
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO message_log (message_id, chat_id, user_id, username, first_name, text, date) VALUES (?,?,?,?,?,?,?)",
        (message.id, chat.id, user.id, user.username or "", user.first_name or "",
         message.text or message.caption or "[медиа]",
         datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
    )
    conn.commit()
    conn.close()


# ── TRACK EDITS ──
@app.on_edited_message(filters.group)
async def track_edits(client, message: Message):
    if not message.from_user or not message.chat:
        return
    user = message.from_user
    chat = message.chat
    gs = get_group_settings(chat.id)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT text FROM message_log WHERE message_id=? AND chat_id=?", (message.id, chat.id))
    old = c.fetchone()
    old_text = old["text"] if old else "(нет в логе)"
    new_text = message.text or message.caption or "[медиа]"

    c.execute(
        "INSERT OR REPLACE INTO message_log (message_id, chat_id, user_id, username, first_name, text, date) VALUES (?,?,?,?,?,?,?)",
        (message.id, chat.id, user.id, user.username or "", user.first_name or "",
         new_text, datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
    )
    conn.commit()
    conn.close()

    uname = f"@{user.username}" if user.username else (user.first_name or "Неизвестно")
    text = (
        f"✏️ **СООБЩЕНИЕ ОТРЕДАКТИРОВАНО**\n\n"
        f"👤 {uname} (ID: `{user.id}`)\n"
        f"💬 Чат: {chat.title}\n\n"
        f"📝 **Было:**\n{old_text}\n\n"
        f"📝 **Стало:**\n{new_text}"
    )

    target = chat.id
    if gs and gs["log_chat_id"]:
        target = gs["log_chat_id"]
    try:
        await client.send_message(target, text[:4000])
    except Exception:
        pass

    for admin_id in ADMIN_USER_IDS:
        if admin_id == target:
            continue
        try:
            await client.send_message(admin_id, text[:4000])
        except Exception:
            pass


# ── TRACK DELETED MESSAGES ──
@app.on_deleted_messages(filters.group)
async def track_deletions(client, messages):
    for message in messages:
        if not message.chat:
            continue
        chat = message.chat
        gs = get_group_settings(chat.id)

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM message_log WHERE message_id=? AND chat_id=?", (message.id, chat.id))
        old = c.fetchone()
        conn.close()

        if old:
            who = old["username"] or old["first_name"] or "Неизвестно"
            text_content = old["text"] or "[медиа]"

            text = (
                f"🗑 **СООБЩЕНИЕ УДАЛЕНО**\n\n"
                f"👤 Кто написал: @{old['username']} ({old['first_name']}) (ID: `{old['user_id']}`)\n"
                f"💬 Чат: {chat.title}\n\n"
                f"📝 **Текст:**\n{text_content}"
            )
        else:
            text = (
                f"🗑 **СООБЩЕНИЕ УДАЛЕНО**\n\n"
                f"💬 Чат: {chat.title}\n"
                f"🆔 Message ID: `{message.id}`\n"
                f"(не было в логе — удалено до запуска бота)"
            )

        target = chat.id
        if gs and gs["log_chat_id"]:
            target = gs["log_chat_id"]
        try:
            await client.send_message(target, text[:4000])
        except Exception:
            pass

        for admin_id in ADMIN_USER_IDS:
            if admin_id == target:
                continue
            try:
                await client.send_message(admin_id, text[:4000])
            except Exception:
                pass


# ── NEW MEMBERS CHECK ──
@app.on_message(filters.new_chat_members & filters.group)
async def check_new_members(client, message: Message):
    chat = message.chat
    gs = get_group_settings(chat.id)

    for member in message.new_chat_members:
        if member.is_bot:
            continue

        if gs["welcome"]:
            try:
                await message.reply(
                    f"👋 Добро пожаловать, {member.first_name}!\n"
                    f"Я KATSUROSECURITY — проверяю участников на скам."
                )
            except Exception:
                pass

        if gs["scam_check"]:
            conn = get_db()
            c = conn.cursor()
            uname = member.username or ""
            scam = None
            if uname:
                c.execute("SELECT * FROM scammers WHERE username=?", (uname,))
                scam = c.fetchone()
            if not scam:
                c.execute("SELECT * FROM scammers WHERE user_id=?", (member.id,))
                scam = c.fetchone()
            conn.close()

            if scam:
                su = f"@{scam['username']}" if scam["username"] else f"ID:{scam['user_id']}"
                try:
                    await message.reply(
                        f"🚨 **ВНИМАНИЕ! СКАМЕР!**\n\n"
                        f"👤 {su} ({scam['first_name']})\n"
                        f"📝 {scam['reason']}\n"
                        f"👮 {scam['added_by_name']}\n"
                        f"📅 {scam['date']}"
                    )
                except Exception:
                    pass


# ── PRIVATE: START ──
@app.on_message(filters.private & filters.command("start"))
async def cmd_start(client, message: Message):
    user = message.from_user
    conn = get_db()
    c = conn.cursor()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    c.execute(
        "INSERT OR REPLACE INTO bot_users (user_id, username, first_name, last_active, date) VALUES (?,?,?,?,?)",
        (user.id, user.username or "", user.first_name or "", now, now))
    conn.commit()
    if is_admin(user.id, user.username) and user.id not in ADMIN_USER_IDS:
        ADMIN_USER_IDS.append(user.id)
    now_fmt = datetime.now().strftime("%Y-%m-%d %H:%M")
    uname = user.username or ""
    c.execute("SELECT * FROM subscriptions WHERE (user_id=? OR username=?) AND active=1 AND end_date>?",
              (user.id, uname, now_fmt))
    sub = c.fetchone()
    conn.close()

    if not sub and not is_admin(user.id, user.username):
        kb = [
            [InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="info_detail")],
        ]
        await message.reply(
            "🔒 **Доступ ограничен**\n\n"
            "Для использования бота нужна подписка.\n\n"
            "📌 **Что умеет бот:**\n"
            "• 🔍 Проверка на скам\n"
            "• 🚨 Жалобы на мошенников\n"
            "• 📋 База скамеров\n"
            "• 🔍 Обратный поиск\n"
            "• 🔔 Оповещения\n"
            "• 🏷 Метки (админ)\n"
            "• 🤖 Автоответчик\n"
            "• 📢 Рассылка\n\n"
            "💎 **Тарифы:**\n"
            "• 1 день — бесплатно (пробный)\n"
            "• 7 дней\n"
            "• 30 дней\n"
            "• 90 дней\n\n"
            "Напиши @Xomka132 для покупки",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    kb = [
        [InlineKeyboardButton("🔍 Проверить", callback_data="check"),
         InlineKeyboardButton("🚨 Жалоба", callback_data="report")],
        [InlineKeyboardButton("📋 База скамеров", callback_data="user_base"),
         InlineKeyboardButton("🔍 Поиск", callback_data="search_menu")],
        [InlineKeyboardButton("🔔 Оповещения", callback_data="alerts_menu"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("📝 Мои жалобы", callback_data="my_reports"),
         InlineKeyboardButton("👤 Профиль", callback_data="my_profile")],
        [InlineKeyboardButton("🤖 Автоответчик", callback_data="user_autoresp"),
         InlineKeyboardButton("ℹ️ Инфо", callback_data="info_detail")],
        [InlineKeyboardButton("⭐ Premium", callback_data="premium_menu"),
         InlineKeyboardButton("📋 Подписка", callback_data="my_sub")],
    ]
    if is_admin(user.id, user.username):
        kb.append([InlineKeyboardButton("⚙️ Админ", callback_data="admin_panel")])

    badge_map = {"vip": "💎 VIP", "premium": "⭐ Premium", "moderator": "🛡 Мод", "user": ""}
    conn2 = get_db()
    c2 = conn2.cursor()
    c2.execute("SELECT badge FROM user_profiles WHERE user_id=?", (user.id,))
    bp = c2.fetchone()
    conn2.close()
    badge = badge_map.get(bp["badge"], "") if bp else ""
    admin_badge = " 👑" if is_admin(user.id, user.username) else ""

    await message.reply(
        f"🛡 **KATSUROSECURITY**{admin_badge}{badge}\n\n"
        f"Привет, {user.first_name}!\n"
        f"База скамеров. Проверяй, жалуйся, защищайся.\n\n"
        f"/check — проверить | /report — жалоба\n"
        f"/base — база | /alert — оповещения\n"
        f"/premium — статус | /myid — ID",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ── CALLBACKS ──
@app.on_callback_query()
async def callbacks(client, cb: CallbackQuery):
    user = cb.from_user
    data = cb.data

    if data == "back_main":
        kb = [
            [InlineKeyboardButton("🔍 Проверить", callback_data="check"),
             InlineKeyboardButton("🚨 Жалоба", callback_data="report")],
            [InlineKeyboardButton("📋 База скамеров", callback_data="user_base"),
             InlineKeyboardButton("🔍 Поиск", callback_data="search_menu")],
            [InlineKeyboardButton("🔔 Оповещения", callback_data="alerts_menu"),
             InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("📝 Мои жалобы", callback_data="my_reports"),
             InlineKeyboardButton("👤 Профиль", callback_data="my_profile")],
            [InlineKeyboardButton("🤖 Автоответчик", callback_data="user_autoresp"),
             InlineKeyboardButton("ℹ️ Инфо", callback_data="info_detail")],
            [InlineKeyboardButton("⭐ Premium", callback_data="premium_menu"),
             InlineKeyboardButton("📋 Подписка", callback_data="my_sub")],
        ]
        if is_admin(user.id, user.username):
            kb.append([InlineKeyboardButton("⚙️ Админ", callback_data="admin_panel")])
        await cb.edit_message_text("Главное меню:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "check":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        set_state(user.id, "user_check")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("🔍 Введите @username или ID для проверки:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "report":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        set_state(user.id, "user_report_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("🚨 Введите @username мошенника:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "premium_menu":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM premium_users WHERE user_id=?", (user.id,))
        is_premium = c.fetchone()
        conn.close()
        status = "✅ Активен" if is_premium else "❌ Не активен"
        kb = [[InlineKeyboardButton("✅ Активировать", callback_data="activate_premium")],
              [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
        await cb.edit_message_text(
            f"⭐ **KATSURO Premium**\n\n"
            f"Статус: {status}\n\n"
            f"🎁 **Привилегии:**\n"
            f"• 🔔 Оповещения о скамерах\n"
            f"• 📊 Расширенная статистика\n"
            f"• ⚡ Приоритетная проверка\n"
            f"• 💎 VIP значок в профиле\n"
            f"• 🎨 Кастомный статус\n"
            f"• 📢 Участие в голосованиях\n"
            f"• 🚫 Нет ограничений на жалобы",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "activate_premium":
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO premium_users (user_id, username, activated_date) VALUES (?,?,?)",
                  (user.id, user.username or user.first_name, datetime.now().strftime("%d.%m.%Y %H:%M")))
        c.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (user.id,))
        c.execute("UPDATE user_profiles SET badge='premium' WHERE user_id=?", (user.id,))
        conn.commit(); conn.close()
        await cb.edit_message_text(
            "⭐ **Premium активирован!**\n\n"
            "Теперь у вас есть:\n"
            "• 🔔 Оповещения\n"
            "• 📊 Расширенная статистика\n"
            "• 💎 VIP значок\n\n"
            "/alert @user — подписаться\n"
            "/mystats — статистика")

    elif data == "stats":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM scammers"); scam = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM complaints WHERE status='pending'"); pend = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM complaints"); tot = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM subscriptions WHERE active=1"); subs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM group_settings"); groups = c.fetchone()[0]
        conn.close()
        await cb.edit_message_text(
            f"📊 **Статистика**\n\n🔴 Скамеров: {scam}\n⏳ Жалоб: {pend}\n"
            f"📋 Всего: {tot}\n💎 Подписок: {subs}\n👥 Групп: {groups}")

    elif data == "my_sub":
        conn = get_db()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        uname = user.username or ""
        c.execute("SELECT * FROM subscriptions WHERE (user_id=? OR username=?) AND active=1 AND end_date>?", (user.id, uname, now))
        sub = c.fetchone(); conn.close()
        if sub:
            await cb.edit_message_text(
                f"📋 **Подписка**\n\nТип: {sub['sub_type']}\n"
                f"С: {sub['start_date']}\nДо: {sub['end_date']}\n✅ Активна")
        else:
            await cb.edit_message_text("❌ Нет подписки. Напиши @Xomka132")

    elif data == "admin_panel":
        if not is_admin(user.id, user.username):
            await cb.edit_message_text("⛔ Нет доступа."); return
        kb = [
            [InlineKeyboardButton("➕ Скамер", callback_data="admin_add"),
             InlineKeyboardButton("➖ Скамер", callback_data="admin_remove")],
            [InlineKeyboardButton("🏷 Метки", callback_data="admin_tags"),
             InlineKeyboardButton("📋 База", callback_data="admin_list")],
            [InlineKeyboardButton("📩 Жалобы", callback_data="admin_complaints")],
            [InlineKeyboardButton("💎 Подписки", callback_data="admin_subs")],
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
             InlineKeyboardButton("🎟 Промокоды", callback_data="admin_promos")],
            [InlineKeyboardButton("⚠️ Преды", callback_data="admin_warns")],
            [InlineKeyboardButton("🤖 Автоответчик", callback_data="admin_autoresp")],
            [InlineKeyboardButton("👥 Группы", callback_data="admin_groups")],
            [InlineKeyboardButton("🔄 Синхронизация", callback_data="sync_menu")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await cb.edit_message_text("⚙️ **Админ-панель**", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_add":
        set_state(user.id, "addscam_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("➕ Введите @username скамера:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "admin_remove":
        set_state(user.id, "removescam_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("➖ Введите @username для удаления:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "admin_broadcast":
        set_state(user.id, "broadcast_text")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("📢 Введите текст рассылки:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_tags":
        kb = [
            [InlineKeyboardButton("🔴 Мошенник", callback_data="admintag_мошенник"),
             InlineKeyboardButton("🟡 Подозреваемый", callback_data="admintag_подозреваемый")],
            [InlineKeyboardButton("🟢 Проверенный", callback_data="admintag_проверенный"),
             InlineKeyboardButton("⚪ Чисто", callback_data="admintag_чисто")],
            [InlineKeyboardButton("🔴 Скамер", callback_data="admintag_скамер"),
             InlineKeyboardButton("🟡 Под подозрением", callback_data="admintag_под подозрением")],
            [InlineKeyboardButton("📋 Все метки", callback_data="admin_all_tags")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        ]
        await cb.edit_message_text(
            "🏷 **Метки (только админ)**\n\n"
            "Выберите метку, затем:\n"
            "/tag @user метка\n"
            "/untag @user — убрать\n"
            "/tags @user — посмотреть",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("admintag_"):
        tag = data.replace("admintag_", "")
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
        emoji = tag_emojis.get(tag, "⚪")
        set_state(user.id, "tag_user", {"tag": tag})
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text(
            f"{emoji} **Метка: {tag}**\n\n"
            f"Введите @username:",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_all_tags":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM user_tags ORDER BY id DESC LIMIT 30")
        rows = c.fetchall(); conn.close()
        kb = []
        if not rows:
            kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_tags")])
            await cb.edit_message_text("🏷 Нет меток.", reply_markup=InlineKeyboardMarkup(kb))
            return
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
        for r in rows:
            emoji = tag_emojis.get(r['tag'], "⚪")
            label = f"{emoji} @{r['target_username']} — {r['tag']}"
            kb.append([InlineKeyboardButton(label, callback_data=f"taginfo_{r['id']}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_tags")])
        await cb.edit_message_text("🏷 **Все метки:**", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("taginfo_"):
        tid = int(data.split("_")[1])
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM user_tags WHERE id=?", (tid,))
        r = c.fetchone(); conn.close()
        if not r:
            await cb.answer("❌ Не найдена.", show_alert=True); return
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
        emoji = tag_emojis.get(r['tag'], "⚪")
        kb = [
            [InlineKeyboardButton("🗑 Удалить метку", callback_data=f"removetag_{r['id']}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_all_tags")],
        ]
        await cb.edit_message_text(
            f"{emoji} **Метка #{r['id']}**\n\n"
            f"👤 @{r['target_username']}\n"
            f"🏷 Метка: {r['tag']}\n"
            f"👮 Поставил: {r['set_by_name']}\n"
            f"📅 Дата: {r['date']}",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("removetag_"):
        tid = int(data.replace("removetag_", ""))
        conn = get_db(); c = conn.cursor()
        c.execute("DELETE FROM user_tags WHERE id=?", (tid,))
        d = c.rowcount; conn.commit(); conn.close()
        if d:
            kb = [[InlineKeyboardButton("🔙 К списку", callback_data="admin_all_tags")]]
            await cb.edit_message_text("🗑 Метка удалена.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await cb.answer("❌ Не найдена.", show_alert=True)

    elif data == "admin_warns":
        kb = [
            [InlineKeyboardButton("⚠️ Выдать пред", callback_data="do_warn")],
            [InlineKeyboardButton("🚫 Забанить", callback_data="do_ban"),
             InlineKeyboardButton("✅ Разбанить", callback_data="do_unban")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        ]
        await cb.edit_message_text(
            "⚠️ **Модерация**\n\n"
            "3 преда = автоматический бан\n\n"
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "do_warn":
        set_state(user.id, "warn_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("⚠️ Введите user_id для выдачи преда:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "do_ban":
        set_state(user.id, "ban_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("🚫 Введите @username для бана:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "do_unban":
        set_state(user.id, "unban_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("✅ Введите @username для разбана:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_list":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM scammers"); total = c.fetchone()[0]
        c.execute("SELECT * FROM scammers ORDER BY id DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        if not rows:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await cb.edit_message_text("📋 База пуста.", reply_markup=InlineKeyboardMarkup(kb)); return
        text = f"📋 **База скамеров** ({total} записей)\n\nВыберите запись:"
        kb = []
        for r in rows:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            label = f"🚨 {u} — {r['reason'][:40]}"
            kb.append([InlineKeyboardButton(label, callback_data=f"scam_{r['id']}")])
        nav = []
        if total > 10:
            nav.append(InlineKeyboardButton("▶️ Далее", callback_data="base_page_1"))
        nav.append(InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        kb.append(nav)
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_complaints":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE status='pending' ORDER BY id DESC LIMIT 20")
        rows = c.fetchall(); conn.close()
        if not rows:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await cb.edit_message_text("📩 Нет жалоб.", reply_markup=InlineKeyboardMarkup(kb)); return
        kb = []
        for r in rows:
            u = f"@{r['target_username']}" if r['target_username'] else f"ID:{r['target_user_id']}"
            label = f"📩 #{r['id']} → {u} ({r['reason'][:30]})"
            kb.append([InlineKeyboardButton(label, callback_data=f"complaint_{r['id']}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
        await cb.edit_message_text("📩 **Жалобы на модерации:**", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("complaint_"):
        cid = int(data.split("_")[1])
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE id=?", (cid,))
        r = c.fetchone(); conn.close()
        if not r:
            await cb.answer("❌ Не найдена.", show_alert=True); return
        u = f"@{r['target_username']}" if r['target_username'] else f"ID:{r['target_user_id']}"
        kb = [
            [InlineKeyboardButton("✅ Одобрить", callback_data=f"accept_{r['id']}"),
             InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{r['id']}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_complaints")],
        ]
        await cb.edit_message_text(
            f"📩 **Жалоба #{r['id']}**\n\n"
            f"👤 **На:** {u} ({r['target_name']})\n"
            f"👮 **От:** {r['reporter_name']}\n"
            f"📝 **Причина:** {r['reason']}\n"
            f"📅 **Дата:** {r['date']}\n"
            f"📊 **Статус:** ⏳ Ожидает",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("accept_"):
        cid = int(data.replace("accept_", ""))
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE id=? AND status='pending'", (cid,))
        comp = c.fetchone()
        if not comp:
            conn.close(); await cb.answer("❌ Уже обработана.", show_alert=True); return
        uname = comp['target_username']
        c.execute("UPDATE complaints SET status='accepted' WHERE id=?", (cid,))
        if uname:
            c.execute("SELECT * FROM scammers WHERE username=?", (uname,))
            if not c.fetchone():
                c.execute("INSERT INTO scammers (user_id, username, first_name, reason, added_by, added_by_name, date) VALUES (?,?,?,?,?,?,?)",
                          (comp['target_user_id'] or 0, uname, comp['target_name'] or "", comp['reason'],
                           comp['reporter_id'], comp['reporter_name'], datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 К жалобам", callback_data="admin_complaints")]]
        await cb.edit_message_text(f"✅ Жалоба #{cid} одобрена.\n@{uname} добавлен в базу.", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("reject_"):
        cid = int(data.replace("reject_", ""))
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE complaints SET status='rejected' WHERE id=? AND status='pending'", (cid,))
        d = c.rowcount; conn.commit(); conn.close()
        if d:
            kb = [[InlineKeyboardButton("🔙 К жалобам", callback_data="admin_complaints")]]
            await cb.edit_message_text(f"❌ Жалоба #{cid} отклонена.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await cb.answer("❌ Уже обработана.", show_alert=True)

    elif data == "admin_subs":
        kb = [
            [InlineKeyboardButton("💎 Выдать подписку", callback_data="do_givesub"),
             InlineKeyboardButton("🚫 Отозвать", callback_data="do_rmsub")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        ]
        await cb.edit_message_text("💎 **Подписки**\n\nВыберите действие:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "do_givesub":
        set_state(user.id, "givesub_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("💎 Введите @username для выдачи подписки:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "do_rmsub":
        set_state(user.id, "rmsub_user")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("🚫 Введите @username для отзыва подписки:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_autoresp":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
        row = c.fetchone(); conn.close()
        status = "✅" if row and row['enabled'] else "❌"
        delay = row['delay_minutes'] if row else 60
        text_r = row['response_text'] if row else "Автоответ..."
        kb = [[InlineKeyboardButton("Вкл/Выкл", callback_data="autoresp_toggle")],
              [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await cb.edit_message_text(
            f"🤖 **Автоответчик**\n\n"
            f"Статус: {status}\nЗадержка: {delay} мин\nТекст: {text_r}\n\n"
            f"⚠️ Для работы нужен **Telegram Business** в настройках бота.\n"
            f"Включи: @BotFather → /mybots → Bot Settings → Telegram Business\n\n"
            f"Настройка:\n"
            f"/autosetdelay 60\n/autosettext текст",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "autoresp_toggle":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
        row = c.fetchone()
        new_state = 0 if (row and row['enabled']) else 1
        if row:
            c.execute("UPDATE auto_responder SET enabled=? WHERE chat_id=?", (new_state, user.id))
        else:
            c.execute("INSERT INTO auto_responder (chat_id, enabled) VALUES (?,?)", (user.id, new_state))
        conn.commit(); conn.close()
        await cb.edit_message_text(f"🤖 Автоответчик {'вкл' if new_state else 'выкл'}.")

    elif data == "admin_groups":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM group_settings")
        rows = c.fetchall(); conn.close()
        if not rows:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await cb.edit_message_text("Нет групп.", reply_markup=InlineKeyboardMarkup(kb)); return
        kb = []
        for r in rows:
            title = r['chat_title'] or str(r['chat_id'])
            sc = "✅" if r['scam_check'] else "❌"
            w = "✅" if r['welcome'] else "❌"
            l = "✅" if r['log_enabled'] else "❌"
            label = f"👥 {title} (С:{sc} П:{w} Л:{l})"
            kb.append([InlineKeyboardButton(label, callback_data=f"group_{r['chat_id']}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
        await cb.edit_message_text("👥 **Группы бота:**", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("group_"):
        chat_id = int(data.replace("group_", ""))
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,))
        r = c.fetchone(); conn.close()
        if not r:
            await cb.answer("❌ Группа не найдена.", show_alert=True); return
        title = r['chat_title'] or str(r['chat_id'])
        sc = "✅ Вкл" if r['scam_check'] else "Выкл"
        w = "✅ Вкл" if r['welcome'] else "Выкл"
        l = "✅ Вкл" if r['log_enabled'] else "Выкл"
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_groups")]]
        await cb.edit_message_text(
            f"👥 **{title}**\n\n"
            f"🔍 Проверка на скам: {sc}\n"
            f"👋 Приветствие: {w}\n"
            f"📝 Логирование: {l}\n\n"
            f"ID: `{r['chat_id']}`",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_promos":
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM promo_codes ORDER BY id DESC LIMIT 20")
        rows = c.fetchall(); conn.close()
        kb = [
            [InlineKeyboardButton("➕ Создать промик", callback_data="promo_create")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        ]
        if rows:
            text = "🎟 **Промокоды:**\n\n"
            for r in rows:
                used = f"✅ → user {r['used_by']}" if r['used_by'] else "🟢 не использован"
                text += f"`{r['code']}` — {r['days']}д | {used}\n"
        else:
            text = "🎟 **Промокоды**\n\nНет промокодов."
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "promo_create":
        kb = [
            [InlineKeyboardButton("1 день", callback_data="promo_dur_1"), InlineKeyboardButton("7 дней", callback_data="promo_dur_7")],
            [InlineKeyboardButton("30 дней", callback_data="promo_dur_30"), InlineKeyboardButton("90 дней", callback_data="promo_dur_90")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")],
        ]
        await cb.edit_message_text("🎟 На сколько дней создать промик?", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("promo_dur_"):
        days = int(data.replace("promo_dur_", ""))
        import string, random
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO promo_codes (code, days, created_by, date) VALUES (?,?,?,?)",
                  (code, days, user.username or user.first_name, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Промокоды", callback_data="admin_promos")]]
        await cb.edit_message_text(
            f"🎟 **Промокод создан!**\n\n"
            f"Код: `{code}`\n"
            f"Дней: {days}\n\n"
            f"Отправь пользователю для активации:\n"
            f"/activate {code}",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "user_base":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM scammers"); total = c.fetchone()[0]
        c.execute("SELECT * FROM scammers ORDER BY id DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        if not rows:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await cb.edit_message_text("📋 База пуста.", reply_markup=InlineKeyboardMarkup(kb)); return
        text = f"📋 **База скамеров** ({total} записей)\n\nВыберите запись:"
        kb = []
        for r in rows:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            label = f"🚨 {u} — {r['reason'][:40]}"
            kb.append([InlineKeyboardButton(label, callback_data=f"scam_{r['id']}")])
        nav = []
        if total > 10:
            nav.append(InlineKeyboardButton("▶️ Далее", callback_data="base_page_1"))
        nav.append(InlineKeyboardButton("🔙 Назад", callback_data="back_main"))
        kb.append(nav)
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("base_page_"):
        page = int(data.split("_")[-1])
        per_page = 10
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM scammers"); total = c.fetchone()[0]
        offset = page * per_page
        c.execute("SELECT * FROM scammers ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset))
        rows = c.fetchall(); conn.close()
        if not rows:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="user_base")]]
            await cb.edit_message_text("📋 Больше нет записей.", reply_markup=InlineKeyboardMarkup(kb)); return
        text = f"📋 **База скамеров** — стр. {page+1}/{(total+per_page-1)//per_page}"
        kb = []
        for r in rows:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            label = f"🚨 {u} — {r['reason'][:40]}"
            kb.append([InlineKeyboardButton(label, callback_data=f"scam_{r['id']}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"base_page_{page-1}"))
        if offset + per_page < total:
            nav.append(InlineKeyboardButton("▶️ Далее", callback_data=f"base_page_{page+1}"))
        nav.append(InlineKeyboardButton("🔙 В меню", callback_data="back_main"))
        kb.append(nav)
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("scam_"):
        scam_id = int(data.split("_")[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM scammers WHERE id=?", (scam_id,))
        r = c.fetchone()
        if not r:
            conn.close()
            await cb.answer("❌ Запись не найдена.", show_alert=True); return
        u = f"@{r['username']}" if r['username'] else "нет"
        uid = r['user_id'] if r['user_id'] else "нет"
        fname = r['first_name'] if r['first_name'] else "нет"
        added = r['added_by_name'] if r['added_by_name'] else "система"
        c.execute("SELECT COUNT(*) FROM complaints WHERE target_username=?", (r['username'],))
        complaints = c.fetchone()[0] if r['username'] else 0
        c.execute("SELECT tag FROM user_tags WHERE target_username=?", (r['username'],))
        tags = [t['tag'] for t in c.fetchall()] if r['username'] else []
        conn.close()
        tags_str = ", ".join(tags) if tags else "нет"
        username_line = f"@{r['username']}" if r['username'] else "нет"
        text = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 **СКАМЕР #{r['id']}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 **Имя:** {fname}\n"
            f"🔗 **Username:** {username_line}\n"
            f"🆔 **ID:** {uid}\n"
            f"📝 **Причина:** {r['reason']}\n"
            f"📅 **Дата:** {r['date']}\n"
            f"👮 **Добавил:** {added}\n"
            f"💬 **Жалоб:** {complaints}\n"
            f"🏷 **Метки:** {tags_str}"
        )
        kb = []
        if is_admin(user.id, user.username):
            kb.append([InlineKeyboardButton("🗑 Удалить из базы", callback_data=f"delbase_{r['id']}")])
        kb.append([InlineKeyboardButton("🔙 Назад", callback_data="user_base")])
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("delbase_"):
        if not is_admin(user.id, user.username):
            await cb.answer("⛔ Нет доступа.", show_alert=True); return
        scam_id = int(data.replace("delbase_", ""))
        conn = get_db(); c = conn.cursor()
        c.execute("DELETE FROM scammers WHERE id=?", (scam_id,))
        d = c.rowcount; conn.commit(); conn.close()
        if d:
            kb = [[InlineKeyboardButton("🔙 К базе", callback_data="user_base")]]
            await cb.edit_message_text("✅ Запись удалена из базы.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await cb.answer("❌ Не найдена.", show_alert=True)

    elif data == "my_profile":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM user_profiles WHERE user_id=?", (user.id,))
        prof = c.fetchone()
        c.execute("SELECT COUNT(*) FROM complaints WHERE reporter_id=?", (user.id,))
        reports = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM complaints WHERE reporter_id=? AND status='accepted'", (user.id,))
        accepted = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM check_history WHERE user_id=?", (user.id,))
        checks = c.fetchone()[0]
        conn.close()

        badge_map = {"vip": "💎 VIP", "premium": "⭐ Premium", "moderator": "🛡 Модератор", "user": "👤 Пользователь"}
        badge = badge_map.get(prof["badge"], "👤 Пользователь") if prof else "👤 Пользователь"
        status = prof["custom_status"] if prof and prof["custom_status"] else "Нет статуса"
        warns = prof["warns"] if prof else 0

        text = (
            f"👤 **Мой профиль**\n\n"
            f"🆔 ID: `{user.id}`\n"
            f"📛 @{user.username or 'нет'}\n"
            f"🏷 {badge}\n"
            f"📝 {status}\n\n"
            f"📊 **Статистика:**\n"
            f"• Жалоб подано: {reports}\n"
            f"• Одобрено: {accepted}\n"
            f"• Проверок: {checks}\n"
            f"• Преды: {warns}/3"
        )
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "my_reports":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE reporter_id=? ORDER BY id DESC LIMIT 15", (user.id,))
        rows = c.fetchall(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
        if not rows:
            await cb.edit_message_text("📝 Нет жалоб.", reply_markup=InlineKeyboardMarkup(kb))
            return
        text = "📝 **Мои жалобы:**\n\n"
        for r in rows:
            status_map = {"pending": "⏳ Ожидает", "accepted": "✅ Принята", "rejected": "❌ Отклонена"}
            s = status_map.get(r['status'], r['status'])
            u = f"@{r['target_username']}" if r['target_username'] else f"ID:{r['target_user_id']}"
            text += f"#{r['id']} → {u}\n  {s} | {r['date']}\n\n"
        await cb.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(kb))

    elif data == "user_autoresp":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM private_autoresponder WHERE id=1")
        ar = c.fetchone(); conn.close()
        status = "✅ Вкл" if ar and ar['enabled'] else "❌ Выкл"
        delay = ar['delay_seconds'] if ar else 5
        text_r = ar['response_text'] if ar else "..."
        kb = [
            [InlineKeyboardButton("Вкл/Выкл", callback_data="user_autoresp_toggle")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
        ]
        await cb.edit_message_text(
            f"🤖 **Автоответчик личных сообщений**\n\n"
            f"Статус: {status}\n"
            f"Задержка: {delay} сек\n"
            f"Текст: {text_r}\n\n"
            f"⚠️ Для работы нужен **Telegram Business**.\n"
            f"Включи: @BotFather → /mybots → Bot Settings → Telegram Business\n\n"
            f"Настройка:\n"
            f"/autosetprivate delay 10\n"
            f"/autosetprivate text Текст",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "user_autoresp_toggle":
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO private_autoresponder (id) VALUES (1)")
        c.execute("SELECT enabled FROM private_autoresponder WHERE id=1")
        row = c.fetchone()
        new_state = 0 if (row and row['enabled']) else 1
        c.execute("UPDATE private_autoresponder SET enabled=? WHERE id=1", (new_state,))
        conn.commit(); conn.close()
        await cb.answer(f"Автоответчик {'вкл' if new_state else 'выкл'}!")
        await cb.edit_message_text(f"🤖 Автоответчик {'ВКЛ' if new_state else 'ВЫКЛ'}.")

    elif data == "buy_sub":
        await cb.edit_message_text(
            "💎 **Купить подписку**\n\n"
            "Тарифы:\n"
            "• 1 день — бесплатно (пробный)\n"
            "• 7 дней\n"
            "• 30 дней\n"
            "• 90 дней\n\n"
            "Напиши @Xomka132 для покупки.\n"
            "Укажи свой @username и желаемый тариф.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Написать админу", url="https://t.me/Xomka132")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
            ]))

    elif data == "info_detail":
        kb = [
            [InlineKeyboardButton("👥 Пользователям", callback_data="info_user")],
            [InlineKeyboardButton("⚙️ Админам", callback_data="info_admin")],
            [InlineKeyboardButton("🔄 Синхронизация", callback_data="info_sync")],
            [InlineKeyboardButton("🤖 Автоответчик", callback_data="info_auto")],
            [InlineKeyboardButton("📋 Подписка", callback_data="info_sub")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await cb.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🛡 **KATSUROSECURITY**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Бот для борьбы с мошенниками в Telegram.\n\n"
            "📌 **Возможности:**\n"
            "• Проверка пользователей на скам\n"
            "• Жалобы на мошенников с модерацией\n"
            "• База скамеров с расширенным поиском\n"
            "• Обратный поиск (телефон, username, ID)\n"
            "• Метки пользователей\n"
            "• Оповещения о проверках\n"
            "• Голосование в группах\n"
            "• Автоответчик в личные сообщения\n"
            "• Синхронизация с каналами\n"
            "• Автоматическая проверка новых участников\n"
            "• Отслеживание редактирования и удаления сообщений\n\n"
            "Выберите раздел:",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "info_user":
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="info_detail")]]
        await cb.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👤 **Для пользователей**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "━━━ **ОСНОВНЫЕ КОМАНДЫ** ━━━\n\n"
            "🔍 `/check @user` — проверить пользователя на скам.\n"
            "Работает с @username, числовым ID или реплаем.\n"
            "Пример: `/check @scammer123`\n\n"
            "🚨 `/report @user причина` — подать жалобу.\n"
            "Жалоба уходит на модерацию.\n"
            "Пример: `/report @scammer123 обманул на 5000₽`\n\n"
            "📋 `/base` — просмотреть базу скамеров.\n"
            "Показывает список всех известных мошенников.\n\n"
            "🔍 `/search слово` — расширенный поиск.\n"
            "Примеры:\n"
            "• `/search мошенник` — по имени/описанию\n"
            "• `/search recent7` — жалобы за 7 дней\n"
            "• `/search recent30` — за 30 дней\n"
            "• `/search top5` — топ-5 скамеров\n"
            "• `/search top10` — топ-10\n\n"
            "🕵️ `/reverse` — обратный поиск.\n"
            "Ищет по номеру телефона, username или Telegram ID.\n"
            "Показывает: инфо из БД + профиль + метки.\n\n"
            "━━━ **СТАТИСТИКА И ЖАЛОБЫ** ━━━\n\n"
            "📊 `/mystats` — ваша статистика:\n"
            "• Сколько жалоб подано\n"
            "• Сколько одобрено\n"
            "• Сколько проверок\n"
            "• Количество оповещений\n\n"
            "📝 `/myreports` — список ваших жалоб.\n"
            "Показывает статус каждой:⏳ на модерации, ✅ одобрено, ❌ отклонено.\n\n"
            "━━━ **ОПОВЕЩЕНИЯ** ━━━\n\n"
            "🔔 `/alert @user` — подписаться на оповещения.\n"
            "Бот уведомит, когда подписанный пользователь будет проверен.\n"
            "Отключить: `/alert off @user`\n\n"
            "━━━ **ПРОФИЛЬ** ━━━\n\n"
            "👤 `/myid` — ваш Telegram ID.\n"
            "Профиль содержит: статус, метку,.warns.\n"
            "Premium получает VIP-значок и расширенную статистику.",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "info_admin":
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="info_detail")]]
        await cb.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ **Для администраторов**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "━━━ **УПРАВЛЕНИЕ БАЗОЙ** ━━━\n\n"
            "➕ `/addscam @user причина` — добавить в базу скамеров.\n"
            "Пример: `/addscam @thief обманул на 10000₽`\n\n"
            "➖ `/removescam @user` — удалить из базы.\n\n"
            "📥 `/accept ID` — одобрить жалобу.\n"
            "Жалоба автоматически добавляет скамера в базу.\n\n"
            "📤 `/reject ID` — отклонить жалобу.\n\n"
            "📋 `/export` — выгрузка базы в CSV.\n"
            "Отправляет файл со всеми скамерами.\n\n"
            "━━━ **МЕТКИ** ━━━\n\n"
            "🏷 `/tag @user метка` — поставить метку.\n"
            "Доступные:\n"
            "• мошенник\n"
            "• подозреваемый\n"
            "• проверенный\n"
            "• скамер\n"
            "• чисто\n"
            "• под подозрением\n\n"
            "🗑 `/untag @user` — убрать все метки.\n"
            "📋 `/tags @user` — посмотреть все метки.\n\n"
            "━━━ **МОДЕРАЦИЯ** ━━━\n\n"
            "🚫 `/ban @user` — забанить (блокирует доступ к боту).\n"
            "✅ `/unban @user` — разбанить.\n"
            "⚠️ `/warn user_id` — выдать предупреждение.\n"
            "При 3-х варнах — автоматический бан.\n\n"
            "━━━ **ПОДПИСКИ** ━━━\n\n"
            "💎 `/givesub @user 30d` — выдать подписку.\n"
            "Тарифы: `1d`, `7d`, `30d`, `90d`\n"
            "🚫 `/rmsub @user` — отозвать подписку.\n\n"
            "━━━ **РАССЫЛКА** ━━━\n\n"
            "📣 `/broadcast текст` — рассылка всем пользователям.\n"
            "Просто напишите текст или прикрепите фото.\n"
            "📋 `/broadcast stats` — статистика пользователей.\n"
            "Бот покажет: всего, активных, с подпиской.\n\n"
            "━━━ **ГРУППЫ** ━━━\n\n"
            "📋 `/grouplist` — список групп бота.\n"
            "📝 `/setlog on|off|id` — логирование сообщений.\n"
            "При включении бот сохраняет все сообщения в БД.",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "info_sync":
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="info_detail")]]
        await cb.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔄 **Синхронизация**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Бот автоматически синхронизируется с каналами:\n\n"
            "📢 **Канал @ScamB_MN_proof**\n"
            "• Парсит пересланные сообщения\n"
            "• Извлекает username и ID мошенников\n"
            "• Автоматически добавляет в базу\n"
            "• Избегает дубликатов\n\n"
            "━━━ **Команды** ━━━\n\n"
            "🔄 `/sync scan` — запустить парсинг.\n"
            "Бот проверит последние сообщения в канале.\n\n"
            "🔄 `/sync status` — статус синхронизации.\n"
            "Показывает: когда было последнее обновление.\n\n"
            "━━━ **Как это работает** ━━━\n\n"
            "1. Админ добавляет бота как админа в канал\n"
            "2. Бот автоматически парсит новые сообщения\n"
            "3. Извлекает ID и @usernames\n"
            "4. Добавляет в базу скамеров\n"
            "5. Пропускает уже существующие записи\n\n"
            "Также работает с пересланными сообщениями —\n"
            "просто перешлите сообщение из канала боту.",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "info_auto":
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="info_detail")]]
        await cb.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 **Автоответчик**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Автоматически отвечает на сообщения в личку.\n\n"
            "━━━ **Настройка** ━━━\n\n"
            "Включить/выключить:\n"
            "• `/autosetprivate on` — включить\n"
            "• `/autosetprivate off` — выключить\n\n"
            "Задержка (в секундах):\n"
            "• `/autosetprivate delay 10` — 10 секунд\n"
            "• `/autosetprivate delay 60` — 1 минута\n"
            "• `/autosetprivate delay 0` — без задержки\n\n"
            "Текст ответа:\n"
            "• `/autosetprivate text Привет! Я бот.`\n\n"
            "━━━ **Пример** ━━━\n\n"
            "```\n"
            "/autosetprivate on\n"
            "/autosetprivate delay 5\n"
            "/autosetprivate text Здравствуйте! Я KATSURO Bot. Чем могу помочь?\n"
            "```\n\n"
            "Бот будет отвечать через 5 секунд после сообщения.\n\n"
            "━━━ **Как работает** ━━━\n\n"
            "1. Пользователь пишет в личку\n"
            "2. Бот ждёт установленную задержку\n"
            "3. Отправляет настроенный текст\n"
            "4. Работает 24/7 пока включён",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "info_sub":
        kb = [
            [InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")],
            [InlineKeyboardButton("🔙 Назад", callback_data="info_detail")],
        ]
        await cb.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💎 **Подписка**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Для полного доступа к боту нужна подписка.\n\n"
            "━━━ **Тарифы** ━━━\n\n"
            "🎁 **Пробный** — 1 день (бесплатно)\n"
            "Попробуйте бота перед покупкой.\n\n"
            "📅 **7 дней** — короткий тест\n"
            "Идеально для ознакомления.\n\n"
            "📅 **30 дней** — стандарт\n"
            "Полный доступ на месяц.\n\n"
            "📅 **90 дней** — экономия\n"
            "Выгодная цена за квартал.\n\n"
            "━━━ **Что даёт подписка** ━━━\n\n"
            "✅ Проверка пользователей\n"
            "✅ Подача жалоб\n"
            "✅ Просмотр базы скамеров\n"
            "✅ Расширенный поиск\n"
            "✅ Обратный поиск\n"
            "✅ Оповещения\n"
            "✅ Метки\n"
            "✅ Статистика\n"
            "✅ Автоответчик\n"
            "✅ Синхронизация\n\n"
            "━━━ **Как купить** ━━━\n\n"
            "Нажмите кнопку «Купить подписку».\n"
            "Опишите тариф → админ выдаст доступ.\n\n"
            "📋 `/mysub` — проверить статус подписки.",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "search_menu":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        kb = [
            [InlineKeyboardButton("🔍 По имени/ID", callback_data="search_by_name")],
            [InlineKeyboardButton("🕵️ Обратный поиск", callback_data="reverse_menu")],
            [InlineKeyboardButton("📅 За 7 дней", callback_data="search_7d"),
             InlineKeyboardButton("📅 За 30 дней", callback_data="search_30d")],
            [InlineKeyboardButton("🏆 Топ 5", callback_data="search_top5"),
             InlineKeyboardButton("🏆 Топ 10", callback_data="search_top10")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await cb.edit_message_text(
            "🔍 **Расширенный поиск**\n\n"
            "Выберите тип поиска или введите:\n/search слово",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "reverse_menu":
        kb = [
            [InlineKeyboardButton("📱 По номеру телефона", callback_data="reverse_phone")],
            [InlineKeyboardButton("👤 По юзернейму", callback_data="reverse_username")],
            [InlineKeyboardButton("🆔 По Telegram ID", callback_data="reverse_id")],
            [InlineKeyboardButton("🔙 Назад", callback_data="search_menu")],
        ]
        await cb.edit_message_text(
            "🕵️ **Обратный поиск**\n\n"
            "Найди человека по:\n"
            "• Номеру телефона\n"
            "• Юзернейму\n"
            "• Telegram ID\n\n"
            "Бот покажет профиль и проверит базу скамеров",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "reverse_phone":
        set_state(user.id, "user_reverse_phone")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("📱 **Поиск по номеру**\n\nВведите номер телефона:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "reverse_username":
        set_state(user.id, "user_reverse_username")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("👤 **Поиск по юзернейму**\n\nВведите @username:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "reverse_id":
        set_state(user.id, "user_reverse_id")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("🆔 **Поиск по ID**\n\nВведите Telegram ID:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "search_by_name":
        await cb.edit_message_text("🔍 Введите: /search имя_или_ID")

    elif data == "search_7d":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM scammers ORDER BY id DESC")
        all_rows = c.fetchall(); conn.close()
        cutoff = datetime.now() - timedelta(days=7)
        rows = []
        for r in all_rows:
            try:
                d = datetime.strptime(r['date'], "%d.%m.%Y %H:%M")
                if d >= cutoff:
                    rows.append(r)
            except Exception:
                pass
        if not rows:
            await cb.edit_message_text("🔍 За 7 дней: ничего не найдено.")
            return
        text = f"📅 **За 7 дней:** {len(rows)} записей\n\n"
        for r in rows[:15]:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            text += f"• {u} — {r['reason'][:60]}\n"
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="search_menu")]]
        await cb.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(kb))

    elif data == "search_30d":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM scammers ORDER BY id DESC")
        all_rows = c.fetchall(); conn.close()
        cutoff = datetime.now() - timedelta(days=30)
        rows = []
        for r in all_rows:
            try:
                d = datetime.strptime(r['date'], "%d.%m.%Y %H:%M")
                if d >= cutoff:
                    rows.append(r)
            except Exception:
                pass
        if not rows:
            await cb.edit_message_text("🔍 За 30 дней: ничего не найдено.")
            return
        text = f"📅 **За 30 дней:** {len(rows)} записей\n\n"
        for r in rows[:15]:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            text += f"• {u} — {r['reason'][:60]}\n"
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="search_menu")]]
        await cb.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(kb))

    elif data == "search_top5":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT username, COUNT(*) as cnt FROM scammers GROUP BY username ORDER BY cnt DESC LIMIT 5")
        rows = c.fetchall(); conn.close()
        if not rows:
            await cb.edit_message_text("🏆 Пока пусто."); return
        text = "🏆 **Топ 5 скамеров:**\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, r in enumerate(rows):
            text += f"{medals[i]} @{r['username']} — {r['cnt']} записей\n"
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="search_menu")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "search_top10":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT username, COUNT(*) as cnt FROM scammers GROUP BY username ORDER BY cnt DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        if not rows:
            await cb.edit_message_text("🏆 Пока пусто."); return
        text = "🏆 **Топ 10 скамеров:**\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, r in enumerate(rows):
            text += f"{medals[i]} @{r['username']} — {r['cnt']} записей\n"
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="search_menu")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "tags_menu":
        kb = [
            [InlineKeyboardButton("🔴 Мошенник", callback_data="quicktag_мошенник"),
             InlineKeyboardButton("🟡 Подозреваемый", callback_data="quicktag_подозреваемый")],
            [InlineKeyboardButton("🟢 Проверенный", callback_data="quicktag_проверенный"),
             InlineKeyboardButton("⚪ Чисто", callback_data="quicktag_чисто")],
            [InlineKeyboardButton("📋 Мои метки", callback_data="my_tags")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await cb.edit_message_text(
            "🏷 **Метки пользователей**\n\n"
            "Выберите метку, затем перешлите сообщение пользователя\n"
            "или напишите: /tag @user метка",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("quicktag_"):
        tag = data.replace("quicktag_", "")
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢"}
        emoji = tag_emojis.get(tag, "⚪")
        await cb.edit_message_text(
            f"{emoji} **Метка: {tag}**\n\n"
            f"Напишите: /tag @username {tag}\n"
            f"Или перешлите сообщение пользователя и напишите:\n"
            f"/tag {tag}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="tags_menu")]
            ]))

    elif data == "my_tags":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT target_username, tag FROM user_tags ORDER BY id DESC LIMIT 20")
        rows = c.fetchall(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="tags_menu")]]
        if not rows:
            await cb.edit_message_text("🏷 Нет меток.", reply_markup=InlineKeyboardMarkup(kb))
            return
        text = "🏷 **Все метки:**\n\n"
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢"}
        for r in rows:
            emoji = tag_emojis.get(r['tag'], "⚪")
            text += f"{emoji} @{r['target_username']} — {r['tag']}\n"
        await cb.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(kb))

    elif data == "sync_menu":
        kb = [
            [InlineKeyboardButton("📥 Синхронизировать", callback_data="sync_do")],
            [InlineKeyboardButton("📊 Статус", callback_data="sync_status_btn")],
            [InlineKeyboardButton("📡 Канал", callback_data="sync_channel_btn")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await cb.edit_message_text(
            "🔄 **Синхронизация**\n\n"
            "Перешлите сообщение из @ScamB_MN_proof боту",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "sync_do":
        await cb.edit_message_text("📥 Перешлите сообщение из канала и напишите /sync scan")

    elif data == "sync_status_btn":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT source, COUNT(*) as cnt, SUM(added) as added_cnt FROM sync_log GROUP BY source")
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM scammers WHERE added_by_name LIKE '%Синхронизация%'")
        sync_total = c.fetchone()[0]; conn.close()
        text = "📊 **Статус синхронизации:**\n\n"
        text += f"Всего: **{sync_total}**\n\n"
        if rows:
            for r in rows:
                text += f"• {r['source']}: {r['cnt']} сообщений, {r['added_cnt'] or 0} добавлено\n"
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="sync_menu")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "sync_channel_btn":
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="sync_menu")]]
        await cb.edit_message_text(
            "📡 **Канальная синхронизация**\n\n"
            "1. Добавьте @GG_chawq_bot админом в @ScamB_MN_proof\n"
            "2. Бот автопарсит новые посты",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "alerts_menu":
        if sub_required(user):
            kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
            await cb.edit_message_text("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM user_alerts WHERE user_id=? AND active=1", (user.id,))
        rows = c.fetchall(); conn.close()
        kb = [
            [InlineKeyboardButton("➕ Добавить", callback_data="alert_add")],
            [InlineKeyboardButton("📋 Мои оповещения", callback_data="my_alerts_list")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        if rows:
            text = f"🔔 **Оповещения** ({len(rows)} активных)\n\n"
            for r in rows:
                text += f"• @{r['target_username']}\n"
        else:
            text = "🔔 **Оповещения**\n\nНет активных оповещений.\n\nСледите за проверками!"
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "alert_add":
        set_state(user.id, "user_alert_add")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text(
            "🔔 **Добавить оповещение**\n\nВведите @username:",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data == "my_alerts_list":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM user_alerts WHERE user_id=? AND active=1", (user.id,))
        rows = c.fetchall(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="alerts_menu")]]
        if not rows:
            await cb.edit_message_text("🔔 Нет оповещений.", reply_markup=InlineKeyboardMarkup(kb))
            return
        text = "🔔 **Мои оповещения:**\n\n"
        for r in rows:
            text += f"• @{r['target_username']}\n"
        kb2 = [[InlineKeyboardButton("❌ Отключить", callback_data="alert_off_prompt")],
               [InlineKeyboardButton("🔙 Назад", callback_data="alerts_menu")]]
        await cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb2))

    elif data == "cancel_state":
        clear_state(user.id)
        kb = [
            [InlineKeyboardButton("🔍 Проверить", callback_data="check"),
             InlineKeyboardButton("🚨 Жалоба", callback_data="report")],
            [InlineKeyboardButton("📋 База скамеров", callback_data="user_base"),
             InlineKeyboardButton("🔍 Поиск", callback_data="search_menu")],
            [InlineKeyboardButton("🔔 Оповещения", callback_data="alerts_menu"),
             InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("📝 Мои жалобы", callback_data="my_reports"),
             InlineKeyboardButton("👤 Профиль", callback_data="my_profile")],
            [InlineKeyboardButton("🤖 Автоответчик", callback_data="user_autoresp"),
             InlineKeyboardButton("ℹ️ Инфо", callback_data="info_detail")],
            [InlineKeyboardButton("⭐ Premium", callback_data="premium_menu"),
             InlineKeyboardButton("📋 Подписка", callback_data="my_sub")],
        ]
        if is_admin(user.id, user.username):
            kb.append([InlineKeyboardButton("⚙️ Админ", callback_data="admin_panel")])
        await cb.edit_message_text("Главное меню:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "alert_off_prompt":
        set_state(user.id, "user_alert_off")
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await cb.edit_message_text("🔔 Введите @username для отключения оповещения:", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "broadcast_confirm":
        state_info = get_state(user.id)
        if not state_info or state_info["state"] != "broadcast_pending":
            await cb.answer("❌ Истёкло время.", show_alert=True); return
        btext = state_info["data"]["text"]
        clear_state(user.id)
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM bot_users")
        users = c.fetchall(); conn.close()
        sent = 0; failed = 0
        for u in users:
            try:
                await client.send_message(u['user_id'], f"📢 **Рассылка:**\n\n{btext}")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await cb.edit_message_text(f"📢 **Рассылка завершена!**\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("givedur_"):
        days = int(data.replace("givedur_", ""))
        state_info = get_state(user.id)
        if not state_info or state_info["state"] != "givesub_tarif":
            await cb.answer("❌ Истёкло время.", show_alert=True); return
        uname = state_info["data"]["username"]
        clear_state(user.id)
        tarif = f"{days}d"
        s = datetime.now(); e = s + timedelta(days=days)
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
        row = c.fetchone()
        uid = row['user_id'] if row else 0
        c.execute("INSERT INTO subscriptions (user_id, username, sub_type, start_date, end_date, active) VALUES (?,?,?,?,?,?)",
                  (uid, uname, tarif, s.strftime("%Y-%m-%d %H:%M"), e.strftime("%Y-%m-%d %H:%M"), 1))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await cb.edit_message_text(f"💎 Подписка {tarif} выдана @{uname}\nДо: {e.strftime('%d.%m.%Y')}", reply_markup=InlineKeyboardMarkup(kb))
        if uid:
            try:
                await client.send_message(uid, f"💎 **Вам выдана подписка!**\n\nТип: {tarif}\nДо: {e.strftime('%d.%m.%Y')}\n\nПолный доступ к боту открыт!")
            except Exception:
                pass

    elif data.startswith("quickcheck_"):
        uname = data.replace("quickcheck_", "")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM scammers WHERE username=?", (uname,))
        row = c.fetchone(); conn.close()
        if row:
            u = f"@{row['username']}" if row['username'] else f"ID:{row['user_id']}"
            await cb.message.reply(
                f"🚨 **СКАМЕР**\n\n👤 {u} ({row['first_name']})\n"
                f"📝 {row['reason']}\n👮 {row['added_by_name']}\n📅 {row['date']}")
        else:
            await cb.message.reply(f"✅ @{uname} — чисто.")
        await cb.answer()

    elif data.startswith("quickreport_"):
        uname = data.replace("quickreport_", "")
        await cb.message.reply(f"🚨 Напишите: /report @{uname} причина")
        await cb.answer()


# ── COMMANDS ──
@app.on_message(filters.private & filters.command("check"))
async def cmd_check(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    args = message.command
    if len(args) < 2:
        if message.reply_to_message:
            target = message.reply_to_message.from_user
        else:
            await message.reply("🔍 /check @username | /check ID | реплай: /check")
            return
    else:
        arg = args[1].lstrip("@")
        conn = get_db()
        c = conn.cursor()
        row = None
        if arg.isdigit():
            c.execute("SELECT * FROM scammers WHERE user_id=?", (int(arg),))
            row = c.fetchone()
        if not row:
            c.execute("SELECT * FROM scammers WHERE username=?", (arg,))
            row = c.fetchone()

        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        result = "scammer" if row else "clean"
        c.execute("INSERT INTO check_history (user_id, checked_username, result, date) VALUES (?,?,?,?)",
                  (user.id, arg, result, now))

        if row:
            c.execute("SELECT user_id FROM user_alerts WHERE target_username=? AND active=1", (arg,))
            alert_users = c.fetchall()
            for au in alert_users:
                try:
                    uid = au["user_id"]
                    u = f"@{row['username']}" if row['username'] else f"ID:{row['user_id']}"
                    await client.send_message(uid,
                        f"🔔 **ОПОВЕЩЕНИЕ**\n\n"
                        f"Пользователь {u} проверен и оказывается **СКАМЕРОМ**!\n"
                        f"📝 {row['reason']}\n📅 {row['date']}")
                except Exception:
                    pass
        conn.commit(); conn.close()

        if row:
            u = f"@{row['username']}" if row['username'] else f"ID: {row['user_id']}"

            tag_conn = get_db()
            tc = tag_conn.cursor()
            tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                          "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
            tc.execute("SELECT tag FROM user_tags WHERE target_username=?", (arg,))
            tags = tc.fetchall()
            tag_conn.close()
            tag_line = ""
            if tags:
                tag_line = "\n🏷 " + " ".join(f"{tag_emojis.get(t['tag'], '⚪')} {t['tag']}" for t in tags)

            await message.reply(
                f"🚨 **СКАМЕР**\n\n👤 {u} ({row['first_name']})\n"
                f"📝 {row['reason']}\n👮 {row['added_by_name']}\n📅 {row['date']}{tag_line}")
        else:
            tag_conn = get_db()
            tc = tag_conn.cursor()
            tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                          "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
            tc.execute("SELECT tag FROM user_tags WHERE target_username=?", (arg,))
            tags = tc.fetchall()
            tag_conn.close()
            tag_line = ""
            if tags:
                tag_line = "\n🏷 " + " ".join(f"{tag_emojis.get(t['tag'], '⚪')} {t['tag']}" for t in tags)
            await message.reply(f"✅ @{arg} — чисто.{tag_line}")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM scammers WHERE user_id=?", (target.id,))
    row = c.fetchone()
    if not row and target.username:
        c.execute("SELECT * FROM scammers WHERE username=?", (target.username,))
        row = c.fetchone()

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    result = "scammer" if row else "clean"
    checked_name = f"@{target.username}" if target.username else f"ID:{target.id}"
    c.execute("INSERT INTO check_history (user_id, checked_username, result, date) VALUES (?,?,?,?)",
              (user.id, checked_name, result, now))

    if row:
        c.execute("SELECT user_id FROM user_alerts WHERE target_username=? AND active=1", (target.username or "",))
        alert_users = c.fetchall()
        for au in alert_users:
            try:
                uid = au["user_id"]
                u = f"@{row['username']}" if row['username'] else f"ID:{row['user_id']}"
                await client.send_message(uid,
                    f"🔔 **ОПОВЕЩЕНИЕ**\n\n"
                    f"Пользователь {u} проверен и оказывается **СКАМЕРОМ**!\n"
                    f"📝 {row['reason']}\n📅 {row['date']}")
            except Exception:
                pass
    conn.commit(); conn.close()

    if row:
        u = f"@{row['username']}" if row['username'] else f"ID: {row['user_id']}"

        tag_conn = get_db()
        tc = tag_conn.cursor()
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
        tc.execute("SELECT tag FROM user_tags WHERE target_username=?", (target.username or "",))
        tags = tc.fetchall()
        tag_conn.close()
        tag_line = ""
        if tags:
            tag_line = "\n🏷 " + " ".join(f"{tag_emojis.get(t['tag'], '⚪')} {t['tag']}" for t in tags)

        await message.reply(
            f"🚨 **СКАМЕР**\n\n👤 {u} ({row['first_name']})\n"
            f"📝 {row['reason']}\n👮 {row['added_by_name']}\n📅 {row['date']}{tag_line}")
    else:
        uname = f"@{target.username}" if target.username else f"ID: {target.id}"
        await message.reply(f"✅ {uname} — чисто.")


@app.on_message(filters.private & filters.command("report"))
async def cmd_report(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    args = message.command
    if len(args) < 2 and not message.reply_to_message:
        await message.reply("🚨 /report @username причина | реплай: /report причина")
        return
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        reason = " ".join(args[1:]) if len(args) > 1 else "Не указана"
    else:
        target = None
        uname = args[1].lstrip("@")
        reason = " ".join(args[2:]) if len(args) > 2 else "Не указана"

    reporter = message.from_user
    tid = target.id if target else 0
    tun = (target.username if target else uname) or ""
    tn = (target.first_name if target else uname) or ""

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO complaints (reporter_id,reporter_name,target_user_id,target_username,target_name,reason,date) VALUES (?,?,?,?,?,?,?)",
        (reporter.id, reporter.username or reporter.first_name, tid, tun, tn, reason,
         datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    await message.reply(f"✅ Жалоба на @{tun} отправлена. Админ рассмотрит.")


@app.on_message(filters.private & filters.command("addscam"))
async def cmd_addscam(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        await message.reply("⛔ Только админ."); return
    args = message.command
    if len(args) < 2 and not message.reply_to_message:
        await message.reply("➕ /addscam @username причина"); return

    if message.reply_to_message:
        target = message.reply_to_message.from_user
        reason = " ".join(args[1:]) if len(args) > 1 else "Без описания"
        tid, tun, tn = target.id, target.username or "", target.first_name or ""
    else:
        tun = args[1].lstrip("@")
        reason = " ".join(args[2:]) if len(args) > 2 else "Без описания"
        tid, tn = 0, tun

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO scammers (user_id,username,first_name,reason,added_by,added_by_name,date) VALUES (?,?,?,?,?,?,?)",
        (tid, tun, tn, reason, user.id, f"@{user.username}" if user.username else user.first_name,
         datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    await message.reply(f"🔴 Скамер @{tun} добавлен. Причина: {reason}")


@app.on_message(filters.private & filters.command("removescam"))
async def cmd_removescam(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    arg = message.command[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM scammers WHERE username=?", (arg,))
    d = c.rowcount
    if not d and arg.isdigit():
        c.execute("DELETE FROM scammers WHERE user_id=?", (int(arg),))
        d = c.rowcount
    conn.commit(); conn.close()
    await message.reply(f"✅ @{arg} удалён." if d else f"❌ @{arg} не найден.")


@app.on_message(filters.private & filters.command("accept"))
async def cmd_accept(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    try:
        cid = int(message.command[1])
    except ValueError:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints WHERE id=? AND status='pending'", (cid,))
    row = c.fetchone()
    if not row:
        conn.close(); await message.reply("❌ Не найдена."); return
    c.execute(
        "INSERT INTO scammers (user_id,username,first_name,reason,added_by,added_by_name,date) VALUES (?,?,?,?,?,?,?)",
        (row['target_user_id'], row['target_username'], row['target_name'],
         f"Жалоба #{cid}: {row['reason']}", user.id,
         f"@{user.username}" if user.username else user.first_name,
         datetime.now().strftime("%d.%m.%Y %H:%M")))
    c.execute("UPDATE complaints SET status='accepted' WHERE id=?", (cid,))
    conn.commit(); conn.close()

    try:
        await client.send_message(row["reporter_id"],
            f"✅ **Ваша жалоба #{cid} одобрена!**\n\n"
            f"👤 @{row['target_username']} добавлен в базу скамеров.\n"
            f"Спасибо за помощь!")
    except Exception:
        pass

    await message.reply(f"✅ Жалоба #{cid} одобрена. @{row['target_username']} в базе.")


@app.on_message(filters.private & filters.command("reject"))
async def cmd_reject(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    try:
        cid = int(message.command[1])
    except ValueError:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints WHERE id=? AND status='pending'", (cid,))
    row = c.fetchone()
    c.execute("UPDATE complaints SET status='rejected' WHERE id=? AND status='pending'", (cid,))
    d = c.rowcount; conn.commit(); conn.close()

    if row:
        try:
            await client.send_message(row["reporter_id"],
                f"❌ **Ваша жалоба #{cid} отклонена.**\n\n"
                f"👤 @{row['target_username']}\n"
                f"Админ решил, что оснований недостаточно.")
        except Exception:
            pass

    await message.reply(f"❌ Жалоба #{cid} отклонена." if d else "❌ Не найдена.")


@app.on_message(filters.private & filters.command("ban"))
async def cmd_ban(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    arg = message.command[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    try:
        uid = int(arg)
    except ValueError:
        c.execute("SELECT user_id FROM scammers WHERE username=?", (arg,))
        row = c.fetchone()
        uid = row['user_id'] if row else None
    if uid:
        c.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (uid,))
        conn.commit(); conn.close()
        await message.reply(f"🚫 {arg} забанен.")
    else:
        conn.close(); await message.reply(f"❌ {arg} не найден. /ban ID")


@app.on_message(filters.private & filters.command("unban"))
async def cmd_unban(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    arg = message.command[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM banned WHERE user_id=?", (int(arg),))
    except ValueError:
        c.execute("SELECT user_id FROM scammers WHERE username=?", (arg,))
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM banned WHERE user_id=?", (row['user_id'],))
    conn.commit(); conn.close()
    await message.reply("✅ Разбан.")


@app.on_message(filters.private & filters.command("givesub"))
async def cmd_givesub(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 3:
        await message.reply("💎 /givesub @username 30d"); return
    uname = message.command[1].lstrip("@")
    tarif = message.command[2].lower()
    days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
    if tarif not in days_map:
        await message.reply("Тарифы: 1d, 7d, 30d, 90d"); return
    days = days_map[tarif]
    s = datetime.now(); e = s + timedelta(days=days)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
    row = c.fetchone()
    uid = row['user_id'] if row else 0
    c.execute(
        "INSERT INTO subscriptions (user_id,username,sub_type,start_date,end_date,active) VALUES (?,?,?,?,?,?)",
        (uid, uname, tarif, s.strftime("%Y-%m-%d %H:%M"), e.strftime("%Y-%m-%d %H:%M"), 1))
    conn.commit(); conn.close()
    await message.reply(f"💎 Подписка {tarif} выдана @{uname} (ID:{uid})\nДо: {e.strftime('%d.%m.%Y')}")
    if uid:
        try:
            await client.send_message(uid, f"💎 **Вам выдана подписка!**\n\nТип: {tarif}\nДо: {e.strftime('%d.%m.%Y')}\n\nПолный доступ к боту открыт!")
        except Exception:
            pass


@app.on_message(filters.private & filters.command("rmsub"))
async def cmd_rmsub(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    uname = message.command[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE subscriptions SET active=0 WHERE username=?", (uname,))
    conn.commit(); conn.close()
    await message.reply(f"💎 Подписка @{uname} отозвана.")


@app.on_message(filters.private & filters.command("premium"))
async def cmd_premium(client, message: Message):
    user = message.from_user
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM premium_users WHERE user_id=?", (user.id,))
    prof = c.fetchone()
    c.execute("SELECT * FROM user_profiles WHERE user_id=?", (user.id,))
    up = c.fetchone(); conn.close()
    badge = up['badge'] if up else "user"
    pstatus = "✅ Активен" if prof else "❌ Не активен"
    await message.reply(
        f"⭐ **KATSURO Premium**\n\n"
        f"Статус: {pstatus}\n"
        f"Профиль: {badge}\n\n"
        f"🎁 Привилегии:\n"
        f"• 🔔 Оповещения о скамерах\n"
        f"• 📊 Расширенная статистика\n"
        f"• 💎 VIP значок\n"
        f"• 🎨 Кастомный статус\n\n"
        f"Активация: /start → ⭐ Premium")


@app.on_message(filters.private & filters.command("myid"))
async def cmd_myid(client, message: Message):
    user = message.from_user
    admin = " 👑" if is_admin(user.id, user.username) else ""
    text = f"🆔 `{user.id}`\n"
    if user.username:
        text += f"👤 @{user.username}\n"
    text += f"📛 {user.first_name}{admin}"
    await message.reply(text)


@app.on_message(filters.private & filters.command("autosetdelay"))
async def cmd_autodelay(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    try:
        delay = int(message.command[1])
    except ValueError:
        await message.reply("Числом!"); return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE auto_responder SET delay_minutes=? WHERE chat_id=?", (delay, user.id))
    else:
        c.execute("INSERT INTO auto_responder (chat_id, delay_minutes) VALUES (?,?)", (user.id, delay))
    conn.commit(); conn.close()
    await message.reply(f"⏱ Задержка: {delay} мин")


@app.on_message(filters.private & filters.command("autosettext"))
async def cmd_autotext(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    text = " ".join(message.command[1:])
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE auto_responder SET response_text=? WHERE chat_id=?", (text, user.id))
    else:
        c.execute("INSERT INTO auto_responder (chat_id, response_text) VALUES (?,?)", (user.id, text))
    conn.commit(); conn.close()
    await message.reply(f"✅ Текст: {text}")


@app.on_message(filters.private & filters.command("setlog"))
async def cmd_setlog(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        await message.reply(
            "⚙️ /setlog on|off\n/setlog id -100... — перенаправить логи")
        return
    arg = message.command[1].lower()
    conn = get_db()
    c = conn.cursor()
    if arg == "on":
        c.execute("UPDATE group_settings SET log_enabled=1")
        conn.commit(); conn.close()
        await message.reply("✅ Логи включены.")
    elif arg == "off":
        c.execute("UPDATE group_settings SET log_enabled=0")
        conn.commit(); conn.close()
        await message.reply("❌ Логи выключены.")
    elif arg == "id" and len(message.command) > 2:
        try:
            cid = int(message.command[2])
            c.execute("UPDATE group_settings SET log_chat_id=?", (cid,))
            conn.commit(); conn.close()
            await message.reply(f"📝 Логи -> {cid}")
        except ValueError:
            conn.close(); await message.reply("ID числом!")
    else:
        conn.close(); await message.reply("/setlog on|off|id ChatID")


@app.on_message(filters.private & filters.command("grouplist"))
async def cmd_grouplist(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM group_settings")
    rows = c.fetchall(); conn.close()
    if not rows:
        await message.reply("Нет групп."); return
    text = "👥 **Группы:**\n\n"
    for r in rows:
        sc = "✅" if r['scam_check'] else "❌"
        w = "✅" if r['welcome'] else "❌"
        l = "✅" if r['log_enabled'] else "❌"
        text += f"• {r['chat_title'] or r['chat_id']}\n  Скам:{sc} Привет:{w} Логи:{l}\n"
    await message.reply(text[:4000])


# ── ГОЛОСОВАНИЕ (inline buttons) ──
@app.on_message(filters.group & filters.command("vote"))
async def cmd_vote(client, message: Message):
    args = message.command
    if len(args) < 3:
        await message.reply("🗳 /vote @username причина")
        return

    uname = args[1].lstrip("@")
    reason = " ".join(args[2:])
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO votes (poll_id, chat_id, message_id, target_username, reason, created_by, date) VALUES (?,?,?,?,?,?,?)",
        (0, message.chat.id, 0, uname, reason, message.from_user.id, now))
    poll_id = c.lastrowid
    conn.commit(); conn.close()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Да (0)", callback_data=f"vote_yes_{poll_id}"),
            InlineKeyboardButton(f"❌ Нет (0)", callback_data=f"vote_no_{poll_id}"),
        ]
    ])

    msg = await message.reply(
        f"🚨 **ГОЛОСОВАНИЕ**\n\n"
        f"👤 @{uname}\n"
        f"📝 Причина: {reason}\n\n"
        f"✅ Да: **0** | ❌ Нет: **0**\n\n"
        f"Голосуйте кнопками ниже!",
        reply_markup=keyboard
    )

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE votes SET message_id=? WHERE poll_id=?", (msg.id, poll_id))
    conn.commit(); conn.close()


@app.on_callback_query(filters.regex(r"^vote_(yes|no)_(\d+)$"), group=-1)
async def handle_vote(client, cb: CallbackQuery):
    await cb.stop_propagation()
    data = cb.data.split("_")
    choice = data[1]
    poll_id = int(data[2])
    user_id = cb.from_user.id

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM votes WHERE poll_id=?", (poll_id,))
    vote = c.fetchone()
    if not vote or vote["status"] != "active":
        conn.close()
        await cb.answer("Голосование завершено!", show_alert=True)
        return

    c.execute("SELECT * FROM vote_voters WHERE poll_id=? AND user_id=?", (poll_id, user_id))
    existing = c.fetchone()

    if existing:
        old_choice = existing["vote"]
        if old_choice == choice:
            conn.close()
            await cb.answer("Вы уже так голосовали!", show_alert=True)
            return
        c.execute("UPDATE vote_voters SET vote=? WHERE poll_id=? AND user_id=?", (choice, poll_id, user_id))
        if choice == "yes":
            c.execute("UPDATE votes SET yes_count=yes_count+1, no_count=no_count-1 WHERE poll_id=?", (poll_id,))
        else:
            c.execute("UPDATE votes SET no_count=no_count+1, yes_count=yes_count-1 WHERE poll_id=?", (poll_id,))
    else:
        c.execute("INSERT INTO vote_voters (poll_id, user_id, vote) VALUES (?,?,?)", (poll_id, user_id, choice))
        if choice == "yes":
            c.execute("UPDATE votes SET yes_count=yes_count+1 WHERE poll_id=?", (poll_id,))
        else:
            c.execute("UPDATE votes SET no_count=no_count+1 WHERE poll_id=?", (poll_id,))

    c.execute("SELECT * FROM votes WHERE poll_id=?", (poll_id,))
    vote = c.fetchone()
    conn.commit(); conn.close()

    total = vote["yes_count"] + vote["no_count"]
    voter_name = cb.from_user.first_name or "Аноним"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Да ({vote['yes_count']})", callback_data=f"vote_yes_{poll_id}"),
            InlineKeyboardButton(f"❌ Нет ({vote['no_count']})", callback_data=f"vote_no_{poll_id}"),
        ]
    ])

    try:
        await cb.message.edit_text(
            f"🚨 **ГОЛОСОВАНИЕ**\n\n"
            f"👤 @{vote['target_username']}\n"
            f"📝 Причина: {vote['reason']}\n\n"
            f"✅ Да: **{vote['yes_count']}** | ❌ Нет: **{vote['no_count']}**\n"
            f"👥 Всего: {total} голосов\n\n"
            f"Голосуйте кнопками ниже!",
            reply_markup=keyboard
        )
    except Exception:
        pass

    await cb.answer(f"✅ {voter_name}: {'Да' if choice == 'yes' else 'Нет'}")

    if total >= 5 and vote["status"] == "active":
        conn = get_db()
        c = conn.cursor()
        uname = vote["target_username"]

        if vote["yes_count"] > vote["no_count"]:
            c.execute("UPDATE votes SET status='passed' WHERE poll_id=?", (poll_id,))
            c.execute(
                "INSERT INTO scammers (user_id, username, first_name, reason, added_by, added_by_name, date) VALUES (?,?,?,?,?,?,?)",
                (vote["target_user_id"] or 0, uname, uname,
                 f"Голосование ({vote['yes_count']}/{total}): {vote['reason']}",
                 vote["created_by"], "Голосование",
                 datetime.now().strftime("%d.%m.%Y %H:%M")))
            result_text = "🔴 **РЕШЕНИЕ: СКАМЕР ДОБАВЛЕН В БАЗУ**"
        elif vote["no_count"] > vote["yes_count"]:
            c.execute("UPDATE votes SET status='rejected' WHERE poll_id=?", (poll_id,))
            result_text = "✅ **РЕШЕНИЕ: НЕ СКАМЕР**"
        else:
            result_text = "⚖️ **РЕШЕНИЕ: НИЧЬЯ — НЕ ДОБАВЛЕН**"

        conn.commit(); conn.close()

        try:
            await cb.message.edit_text(
                f"🚨 **ИТОГ ГОЛОСОВАНИЯ**\n\n"
                f"👤 @{uname}\n"
                f"📝 Причина: {vote['reason']}\n\n"
                f"✅ Да: **{vote['yes_count']}** | ❌ Нет: **{vote['no_count']}**\n"
                f"👥 Всего: {total} голосов\n\n"
                f"{result_text}"
            )
        except Exception:
            pass


# ── РАСШИРЕННЫЙ ПОИСК ──
@app.on_message(filters.private & filters.command("search"))
async def cmd_search(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    args = message.command
    if len(args) < 2:
        await message.reply(
            "🔍 **Расширенный поиск**\n\n"
            "/search слово — поиск по имени/причине\n"
            "/search recent7 — последние 7 дней\n"
            "/search recent30 — последние 30 дней\n"
            "/search top5 — топ 5 по жалобам\n"
            "/search id 123 — поиск по ID"
        )
        return

    query = " ".join(args[1:])
    conn = get_db()
    c = conn.cursor()

    if query.startswith("recent"):
        try:
            days = int(query.replace("recent", ""))
        except ValueError:
            days = 7
        c.execute("SELECT * FROM scammers ORDER BY id DESC")
        all_rows = c.fetchall()
        cutoff = datetime.now() - timedelta(days=days)
        rows = []
        for r in all_rows:
            try:
                d = datetime.strptime(r['date'], "%d.%m.%Y %H:%M")
                if d >= cutoff:
                    rows.append(r)
            except Exception:
                pass
        header = f"📋 Найдено за {days} дней: {len(rows)}\n\n"
    elif query.startswith("top"):
        try:
            n = int(query.replace("top", ""))
        except ValueError:
            n = 5
        c.execute("SELECT username, COUNT(*) as cnt FROM scammers GROUP BY username ORDER BY cnt DESC LIMIT ?", (n,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await message.reply("🔍 Ничего не найдено."); return
        text = f"🏆 **Топ {n} скамеров:**\n\n"
        for r in rows:
            text += f"• @{r['username']} — {r['cnt']} записей\n"
        await message.reply(text); return
    elif query.startswith("id"):
        try:
            uid = int(args[2]) if len(args) > 2 else 0
        except ValueError:
            await message.reply("ID числом!"); conn.close(); return
        c.execute("SELECT * FROM scammers WHERE user_id=?", (uid,))
        rows = c.fetchall()
    else:
        q = f"%{query}%"
        c.execute("SELECT * FROM scammers WHERE username LIKE ? OR first_name LIKE ? OR reason LIKE ? ORDER BY id DESC",
                  (q, q, q))
        rows = c.fetchall()

    conn.close()

    if not rows:
        await message.reply("🔍 Ничего не найдено.")
        return

    text = f"🔍 **Результаты:** ({len(rows)} шт.)\n\n"
    for r in rows[:20]:
        u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
        text += f"• {u} ({r['first_name']}) — {r['reason']}\n  📅 {r['date']}\n\n"
    if len(rows) > 20:
        text += f"... и ещё {len(rows)-20}"
    await message.reply(text[:4000])


# ── ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ ──
@app.on_message(filters.private & filters.command("reverse"))
async def cmd_reverse(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    args = message.command
    if len(args) < 2:
        await message.reply(
            "🕵️ **Обратный поиск**\n\n"
            "/reverse @username\n"
            "/reverse +79161234567\n"
            "/reverse 123456789 (ID)\n\n"
            "Найдёт профиль в Telegram и проверит базу скамеров"
        )
        return

    query = args[1]
    await message.reply("🔍 Ищу...")

    target_user = None
    search_type = ""

    try:
        if query.startswith("+") or (query.isdigit() and len(query) >= 10):
            search_type = "📱 Телефон"
            try:
                target_user = await client.get_users(query)
            except Exception:
                pass

        elif query.lstrip("@").isdigit():
            search_type = "🆔 Telegram ID"
            uid = int(query.lstrip("@"))
            try:
                target_user = await client.get_users(uid)
            except Exception:
                pass

        else:
            search_type = "👤 Юзернейм"
            uname = query.lstrip("@")
            try:
                target_user = await client.get_users(uname)
            except Exception:
                pass

    except Exception as e:
        await message.reply(f"❌ Ошибка поиска: {str(e)[:100]}")
        return

    if not target_user:
        await message.reply(
            f"🕵️ **Результат**\n\n"
            f"Тип поиска: {search_type}\n"
            f"Запрос: `{query}`\n\n"
            f"❌ Пользователь не найден.\n\n"
            f"Возможные причины:\n"
            f"• Юзернейм неправильный\n"
            f"• Телефон не привязан к Telegram\n"
            f"• ID не существует\n"
            f"• Пользователь скрыл аккаунт"
        )
        return

    uid = target_user.id
    uname = target_user.username or "нет"
    fname = target_user.first_name or "?"
    lname = target_user.last_name or ""
    phone = getattr(target_user, "phone_number", None) or "скрыт"
    is_bot = "🤖 Да" if target_user.is_bot else "👤 Нет"
    is_premium = "⭐ Premium" if getattr(target_user, "is_premium", False) else ""

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM scammers WHERE user_id=? OR username=?", (uid, uname))
    scam = c.fetchone()

    c.execute("SELECT tag FROM user_tags WHERE target_username=?", (uname,))
    tags = c.fetchall()

    c.execute("SELECT * FROM user_alerts WHERE target_user_id=?", (uid,))
    alerts = c.fetchall()

    tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                  "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}

    conn.close()

    text = (
        f"🕵️ **Обратный поиск** — {search_type}\n\n"
        f"👤 **{fname} {lname}**\n"
        f"📛 @{uname}\n"
        f"🆔 `{uid}`\n"
        f"📱 Телефон: {phone}\n"
        f"🤖 Бот: {is_bot}\n"
    )
    if is_premium:
        text += f"💎 {is_premium}\n"

    if scam:
        text += f"\n🚨 **В БАЗЕ СКАМЕРОВ!**\n"
        text += f"📝 {scam['reason']}\n"
        text += f"👮 {scam['added_by_name']}\n"
        text += f"📅 {scam['date']}\n"

    if tags:
        text += "\n🏷 Метки: " + " ".join(
            f"{tag_emojis.get(t['tag'], '⚪')} {t['tag']}" for t in tags)

    if alerts:
        text += f"\n🔔 За ним следят: {len(alerts)} чел."

    kb = [
        [InlineKeyboardButton("🔍 Проверить в базе", callback_data=f"quickcheck_{uname}")],
        [InlineKeyboardButton("🚨 Пожаловаться", callback_data=f"quickreport_{uname}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="search_menu")],
    ]
    await message.reply(text, reply_markup=InlineKeyboardMarkup(kb))


@app.on_message(filters.private & filters.command("base"))
async def cmd_base(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM scammers"); total = c.fetchone()[0]
    c.execute("SELECT * FROM scammers ORDER BY id DESC LIMIT 15")
    rows = c.fetchall(); conn.close()
    if not rows:
        await message.reply("📋 База пуста."); return
    text = f"📋 **База скамеров** ({total} записей)\n\n"
    for r in rows:
        u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
        text += f"• {u} — {r['reason'][:80]}\n  📅 {r['date']}\n\n"
    await message.reply(text[:4000])


@app.on_message(filters.private & filters.command("alert"))
async def cmd_alert(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    args = message.command
    if len(args) < 2:
        await message.reply(
            "🔔 **Оповещения**\n\n"
            "/alert @user — следить\n"
            "/alert off @user — отключить\n"
            "Когда проверят этого юзера — вы узнаете"
        )
        return

    if args[1].lower() == "off" and len(args) > 2:
        uname = args[2].lstrip("@")
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE user_alerts SET active=0 WHERE user_id=? AND target_username=?",
                  (user.id, uname))
        d = c.rowcount; conn.commit(); conn.close()
        await message.reply(f"🔔 Оповещение @{uname} отключено." if d else "❌ Не найдено.")
        return

    uname = args[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_alerts WHERE user_id=? AND target_username=? AND active=1",
              (user.id, uname))
    if c.fetchone():
        conn.close(); await message.reply(f"🔔 Уже следите за @{uname}."); return
    c.execute("INSERT INTO user_alerts (user_id, target_username, date) VALUES (?,?,?)",
              (user.id, uname, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    await message.reply(f"🔔 Теперь следите за @{uname}! Уведомление при проверке.")


@app.on_message(filters.private & filters.command("mystats"))
async def cmd_mystats(client, message: Message):
    user = message.from_user
    if sub_required(user):
        kb = [[InlineKeyboardButton("📋 Купить подписку", callback_data="buy_sub")]]
        await message.reply("🔒 Нужна подписка!", reply_markup=InlineKeyboardMarkup(kb))
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM complaints WHERE reporter_id=?", (user.id,))
    reports = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM complaints WHERE reporter_id=? AND status='accepted'", (user.id,))
    accepted = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM check_history WHERE user_id=?", (user.id,))
    checks = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_alerts WHERE user_id=? AND active=1", (user.id,))
    alerts = c.fetchone()[0]
    conn.close()

    await message.reply(
        f"📊 **Моя статистика**\n\n"
        f"🚨 Жалоб подано: {reports}\n"
        f"✅ Одобрено: {accepted}\n"
        f"🔍 Проверок: {checks}\n"
        f"🔔 Оповещений: {alerts}"
    )




@app.on_message(filters.private & filters.command("warn"))
async def cmd_warn(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username) or len(message.command) < 2:
        return
    try:
        uid = int(message.command[1])
    except ValueError:
        uname = message.command[1].lstrip("@")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
        r = c.fetchone(); conn.close()
        if not r:
            await message.reply("❌ Пользователь не найден."); return
        uid = r["user_id"]

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (uid,))
    c.execute("UPDATE user_profiles SET warns=warns+1 WHERE user_id=?", (uid,))
    c.execute("SELECT warns FROM user_profiles WHERE user_id=?", (uid,))
    p = c.fetchone()
    warns = p["warns"] if p else 0

    if warns >= 3:
        c.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (uid,))
        c.execute("DELETE FROM user_profiles WHERE user_id=?", (uid,))
        conn.commit(); conn.close()
        await message.reply(f"🚫 Пользователь {uid} получил 3 преда — заблокирован.")
    else:
        conn.commit(); conn.close()
        await message.reply(f"⚠️ Пользователь {uid}: пред {warns}/3")


# ── ИНФО И МЕТКИ ──
@app.on_message(filters.private & filters.command("info"))
async def cmd_info(client, message: Message):
    kb = [
        [InlineKeyboardButton("👥 Пользователям", callback_data="info_user")],
        [InlineKeyboardButton("⚙️ Админам", callback_data="info_admin")],
        [InlineKeyboardButton("🔄 Синхронизация", callback_data="info_sync")],
        [InlineKeyboardButton("🤖 Автоответчик", callback_data="info_auto")],
        [InlineKeyboardButton("📋 Подписка", callback_data="info_sub")],
    ]
    await message.reply(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛡 **KATSUROSECURITY**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Бот для борьбы с мошенниками в Telegram.\n\n"
        "📌 **Возможности:**\n"
        "• Проверка пользователей на скам\n"
        "• Жалобы на мошенников с модерацией\n"
        "• База скамеров с расширенным поиском\n"
        "• Обратный поиск (телефон, username, ID)\n"
        "• Метки пользователей\n"
        "• Оповещения о проверках\n"
        "• Голосование в группах\n"
        "• Автоответчик в личные сообщения\n"
        "• Синхронизация с каналами\n"
        "• Автоматическая проверка новых участников\n"
        "• Отслеживание редактирования и удаления сообщений\n\n"
        "Выберите раздел:",
        reply_markup=InlineKeyboardMarkup(kb))


@app.on_message(filters.private & filters.command("tag"))
async def cmd_tag(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        await message.reply("⛔ Только админ может ставить метки.")
        return
    args = message.command
    valid_tags = {"мошенник", "подозреваемый", "проверенный", "скамер", "чисто", "под подозрением"}

    if len(args) < 3:
        await message.reply(
            "🏷 **Метки пользователей**\n\n"
            "/tag @user метка\n\n"
            f"Доступные метки:\n" + "\n".join(f"• {t}" for t in sorted(valid_tags))
        )
        return

    uname = args[1].lstrip("@")
    tag = " ".join(args[2:]).lower()

    if tag not in valid_tags:
        await message.reply(f"❌ Неизвестная метка. Доступные:\n" + "\n".join(f"• {t}" for t in sorted(valid_tags)))
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_tags (target_username, tag, set_by, set_by_name, date) VALUES (?,?,?,?,?)",
        (uname, tag, user.id,
         f"@{user.username}" if user.username else user.first_name,
         datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    await message.reply(f"🏷 Метка «{tag}» поставлена @{uname}")


@app.on_message(filters.private & filters.command("untag"))
async def cmd_untag(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        await message.reply("⛔ Только админ."); return
    args = message.command
    if len(args) < 2:
        await message.reply("🏷 /untag @user — убрать все метки")
        return

    uname = args[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM user_tags WHERE target_username=?", (uname,))
    d = c.rowcount; conn.commit(); conn.close()
    await message.reply(f"🏷 Все метки @{uname} удалены." if d else f"❌ У @{uname} нет меток.")


@app.on_message(filters.private & filters.command("tags"))
async def cmd_tags(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        await message.reply("⛔ Только админ."); return
    args = message.command
    if len(args) < 2:
        await message.reply("🏷 /tags @user — посмотреть метки")
        return

    uname = args[1].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_tags WHERE target_username=? ORDER BY id DESC", (uname,))
    rows = c.fetchall(); conn.close()

    if not rows:
        await message.reply(f"🏷 У @{uname} нет меток.")
        return

    tag_emojis = {
        "мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
        "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"
    }

    text = f"🏷 **Метки @{uname}:**\n\n"
    for r in rows:
        emoji = tag_emojis.get(r['tag'], "⚪")
        text += f"{emoji} {r['tag']} — {r['set_by_name']} ({r['date']})\n"
    await message.reply(text)


@app.on_message(filters.private & filters.command("activate"))
async def cmd_activate(client, message: Message):
    user = message.from_user
    args = message.command
    if len(args) < 2:
        await message.reply("🎟 /activate КОД — активировать промокод")
        return
    code = args[1].upper()
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM promo_codes WHERE code=? AND used_by IS NULL", (code,))
    promo = c.fetchone()
    if not promo:
        conn.close()
        await message.reply("❌ Промокод не найден или уже использован.")
        return
    days = promo['days']
    s = datetime.now(); e = s + timedelta(days=days)
    c.execute("INSERT INTO subscriptions (user_id, username, sub_type, start_date, end_date, active) VALUES (?,?,?,?,?,?)",
              (user.id, user.username or "", f"promo_{days}d", s.strftime("%Y-%m-%d %H:%M"), e.strftime("%Y-%m-%d %H:%M"), 1))
    c.execute("UPDATE promo_codes SET used_by=?, used_date=? WHERE id=?",
              (user.id, datetime.now().strftime("%d.%m.%Y %H:%M"), promo['id']))
    conn.commit(); conn.close()
    await message.reply(
        f"✅ **Промокод активирован!**\n\n"
        f"🎟 Код: `{code}`\n"
        f"📅 Дней: {days}\n"
        f"⏰ До: {e.strftime('%d.%m.%Y')}\n\n"
        f"Полный доступ к боту открыт!")


@app.on_message(filters.private & filters.command("mysub"))
async def cmd_mysub(client, message: Message):
    user = message.from_user
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    uname = user.username or ""
    c.execute("SELECT * FROM subscriptions WHERE (user_id=? OR username=?) AND active=1 AND end_date>?", (user.id, uname, now))
    sub = c.fetchone(); conn.close()
    if sub:
        await message.reply(
            f"📋 **Подписка**\n\n"
            f"Тип: {sub['sub_type']}\n"
            f"С: {sub['start_date']}\n"
            f"До: {sub['end_date']}\n✅ Активна")
    else:
        await message.reply("❌ Нет подписки. Напиши @Xomka132")


# ── СИНХРОНИЗАЦИЯ ──

CHANNEL_IDS = {
    "ScamB_MN_proof": -1003952833340,
    "SCAMB_MN_BOT": 8782912630,
}


KNOWN_BOTS = {"SCAMB_MN_BOT", "ScamB_MN_proof", "GG_chawq_bot", "KATSUROSECURITI"}

def parse_scammer_from_text(text, source="unknown"):
    results = []
    if not text:
        return results

    all_ids = re.findall(r"\b(\d{5,})\b", text)
    seen = set()
    for uid in all_ids:
        uid_int = int(uid)
        if uid_int not in seen:
            seen.add(uid_int)
            results.append({"user_id": uid_int, "username": None, "reason": text[:200]})

    return results


def add_scammer_from_sync(username, user_id, reason, source, reporter="Синхронизация"):
    if not username and not user_id:
        return False
    conn = get_db()
    c = conn.cursor()

    if user_id:
        c.execute("SELECT * FROM scammers WHERE user_id=?", (user_id,))
        if c.fetchone():
            conn.close()
            return False

    if username:
        c.execute("SELECT * FROM scammers WHERE username=?", (username,))
        if c.fetchone():
            conn.close()
            return False

    c.execute(
        "INSERT INTO scammers (user_id, username, first_name, reason, added_by, added_by_name, date) VALUES (?,?,?,?,?,?,?)",
        (user_id or 0, username or "", username or "", reason or "Нет описания",
         0, f"{reporter} [{source}]",
         datetime.now().strftime("%d.%m.%Y %H:%M")))

    c.execute(
        "INSERT INTO sync_log (source, target_username, reason, added, date) VALUES (?,?,?,?,?)",
        (source, username or "", reason or "", 1, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    return True


async def resolve_username(client, user_id):
    try:
        user = await client.get_users(user_id)
        return user.username or user.first_name or str(user_id)
    except Exception:
        return None


@app.on_message(filters.private & filters.command("sync"))
async def cmd_sync(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        await message.reply("❌ Только для админов."); return

    args = message.command
    if len(args) < 2:
        await message.reply(
            "🔄 **Синхронизация**\n\n"
            "/sync scan — парсит пересланные сообщения\n"
            "/sync status — статус синхронизации\n"
            "/sync channel — парсит пост канала (нужны права админа)\n\n"
            "💡 Перешлите сообщения из канала @ScamB_MN_proof боту и напишите /sync scan"
        )
        return

    subcmd = args[1].lower()

    if subcmd == "status":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT source, COUNT(*) as cnt, SUM(added) as added_cnt FROM sync_log GROUP BY source")
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM scammers WHERE added_by_name LIKE '%Синхронизация%'")
        sync_total = c.fetchone()[0]
        conn.close()

        text = "🔄 **Статус синхронизации:**\n\n"
        text += f"📊 Всего из синхронизации: **{sync_total}**\n\n"
        if rows:
            for r in rows:
                text += f"• {r['source']}: {r['cnt']} сообщений, {r['added_cnt'] or 0} добавлено\n"
        else:
            text += "Пока нет данных.\n"
        text += f"\n💡 Источники: @ScamB_MN_proof, @SCAMB_MN_BOT"
        await message.reply(text)
        return

    if subcmd == "scan":
        if not message.forward_from_chat and not message.reply_to_message:
            await message.reply(
                "📨 Перешлите сообщения из канала @ScamB_MN_proof боту\n"
                "и напишите /sync scan (ответом на пересланное)"
            )
            return

        target_msg = message.reply_to_message if message.reply_to_message else message
        text = target_msg.text or target_msg.caption or ""
        forward_from = target_msg.forward_from_chat

        source = "unknown"
        if forward_from:
            source = forward_from.username or forward_from.title or "unknown"

        scammers = parse_scammer_from_text(text, source)

        if not scammers:
            await message.reply("🔍 Не удалось распознать скамеров в этом сообщении.\n\nПопробуйте переслать другое.")
            return

        for s in scammers:
            uid = s.get("user_id")
            if uid and not s.get("username"):
                resolved = await resolve_username(client, uid)
                if resolved:
                    s["username"] = resolved

        added = 0
        skipped = 0
        for s in scammers:
            if add_scammer_from_sync(s.get("username"), s.get("user_id"),
                                     s.get("reason", ""), source,
                                     s.get("reporter", "Пересылка")):
                added += 1
            else:
                skipped += 1

        result = f"🔄 **Синхронизация завершена!**\n\n"
        result += f"Источник: {source}\n"
        result += f"✅ Добавлено: {added}\n"
        if skipped:
            result += f"⏭ Пропущено (уже в базе): {skipped}\n"
        result += "\n"
        for s in scammers:
            uid = s.get("user_id", "?")
            uname = s.get("username", "?")
            result += f"• ID:{uid} @{uname} — {s.get('reason', 'Без описания')[:100]}\n"
        await message.reply(result[:4000])
        return

    if subcmd == "channel":
        await message.reply(
            "📡 **Канальная синхронизация**\n\n"
            "Чтобы бот автоматически парсил новые посты из @ScamB_MN_proof:\n\n"
            "1. Добавьте @GG_chawq_bot админом в канал @ScamB_MN_proof\n"
            "2. Бот начнёт автоматически парсить новые посты\n\n"
            "💡 Пока не добавили — используйте /sync scan (пересылка)"
        )
        return

    await message.reply("Неизвестная команда. /sync scan|status|channel")


@app.on_message(filters.forwarded & filters.private)
async def handle_forwarded(client, message: Message):
    await message.stop_propagation()
    user = message.from_user
    if not is_admin(user.id, user.username):
        return

    forward_from = message.forward_from_chat
    text = message.text or message.caption or ""

    if not text:
        return

    source = "unknown"
    if forward_from:
        source = forward_from.username or forward_from.title or "unknown"

    scammers = parse_scammer_from_text(text, source)
    if not scammers:
        return

    for s in scammers:
        uid = s.get("user_id")
        if uid and not s.get("username"):
            resolved = await resolve_username(client, uid)
            if resolved:
                s["username"] = resolved

    added = 0
    for s in scammers:
        if add_scammer_from_sync(s.get("username"), s.get("user_id"),
                                 s.get("reason", ""), source,
                                 s.get("reporter", "Пересылка")):
            added += 1

    if added > 0:
        lines = []
        for s in scammers:
            uid = s.get("user_id", "?")
            uname = s.get("username", "?")
            lines.append(f"ID:{uid} @{uname}")
        await message.reply(
            f"🔄 Авто-синхронизация: добавлено **{added}** скамеров из @{source}\n"
            + "\n".join(lines)
        )


@app.on_message(filters.channel)
async def handle_channel_post(client, post):
    chat_id = post.chat.id
    if chat_id != CHANNEL_IDS.get("ScamB_MN_proof"):
        return

    text = post.text or post.caption or ""
    if not text:
        return

    scammers = parse_scammer_from_text(text, "ScamB_MN_proof")

    for s in scammers:
        uid = s.get("user_id")
        if uid and not s.get("username"):
            resolved = await resolve_username(client, uid)
            if resolved:
                s["username"] = resolved

    added = 0
    for s in scammers:
        if add_scammer_from_sync(s.get("username"), s.get("user_id"),
                                 s.get("reason", ""), "ScamB_MN_proof",
                                 s.get("reporter", "Канал")):
            added += 1

    if added > 0 and post.chat.has_protected_content is False:
        try:
            await client.send_message(
                chat_id,
                f"✅ KATSUROSECURITY: синхронизировано {added} скамеров из поста"
            )
        except Exception:
            pass


# ── ЭКСПОРТ БАЗЫ ──
@app.on_message(filters.private & filters.command("export"))
async def cmd_export(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM scammers ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await message.reply("📋 База пуста."); return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "User ID", "Username", "Имя", "Причина", "Добавил", "Дата"])
    for r in rows:
        writer.writerow([r['id'], r['user_id'], r['username'], r['first_name'],
                         r['reason'], r['added_by_name'], r['date']])

    csv_bytes = output.getvalue().encode('utf-8-sig')
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scammers_export.csv")
    with open(file_path, "wb") as f:
        f.write(csv_bytes)

    await message.reply_document(
        document=file_path,
        caption=f"📊 Экспорт базы скамеров\nЗаписей: {len(rows)}\nДата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    os.remove(file_path)


# ── РАССЫЛКА ──
@app.on_message(filters.private & filters.command("broadcast"))
async def cmd_broadcast(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        return

    args = message.command
    if len(args) < 2:
        await message.reply(
            "📢 **Рассылка**\n\n"
            "/broadcast текст — отправить всем пользователям\n"
            "/broadcast stats — статистика пользователей"
        )
        return

    subcmd = args[1].lower()

    if subcmd == "stats":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM bot_users")
        total = c.fetchone()[0]
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%d.%m.%Y %H:%M")
        c.execute("SELECT COUNT(*) FROM bot_users WHERE last_active>=?", (week_ago,))
        active_week = c.fetchone()[0]
        conn.close()
        await message.reply(
            f"📊 **Пользователи бота:**\n\n"
            f"Всего: **{total}**\n"
            f"Активны за неделю: **{active_week}**"
        )
        return

    text = " ".join(args[1:])

    if not message.forward_from_chat and not message.photo and not message.document:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Отправить", callback_data="broadcast_yes"),
             InlineKeyboardButton("❌ Отмена", callback_data="broadcast_no")]
        ])
        await message.reply(
            f"📢 **Рассылка:**\n\n{text}\n\nОтправить всем пользователям?",
            reply_markup=kb
        )
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_users")
    users = c.fetchall()
    conn.close()

    sent = 0
    failed = 0
    for u in users:
        try:
            if message.photo:
                await client.send_photo(u["user_id"], message.photo.file_id, caption=text or message.caption or "")
            elif message.document:
                await client.send_document(u["user_id"], message.document.file_id, caption=text or message.caption or "")
            else:
                await client.send_message(u["user_id"], text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.reply(f"📢 **Рассылка завершена!**\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


@app.on_callback_query(filters.regex(r"^broadcast_(yes|no)$"), group=-1)
async def handle_broadcast_confirm(client, cb: CallbackQuery):
    await cb.stop_propagation()
    action = cb.data.split("_")[1]
    if action == "no":
        await cb.message.edit_text("❌ Рассылка отменена.")
        await cb.answer()
        return

    msg = cb.message
    text = msg.text or msg.caption or ""
    lines = text.split("\n")
    broadcast_text = "\n".join(lines[2:-1]).strip()

    if not broadcast_text:
        await cb.message.edit_text("❌ Текст рассылки пуст.")
        await cb.answer()
        return

    await cb.message.edit_text("📢 Рассылка запущена...")
    await cb.answer()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM bot_users")
    users = c.fetchall()
    conn.close()

    sent = 0
    failed = 0
    for u in users:
        try:
            await client.send_message(u["user_id"], broadcast_text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    try:
        await cb.message.edit_text(f"📢 **Рассылка завершена!**\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")
    except Exception:
        pass



@app.on_message(filters.group & filters.mentioned & ~filters.service)
async def group_autoresponder(client, message: Message):
    gs = get_group_settings(message.chat.id)
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (message.chat.id,))
    row = c.fetchone(); conn.close()
    if row and row['enabled']:
        try:
            await message.reply(row['response_text'][:2000])
        except Exception:
            pass

# ── ОБРАБОТЧИК СОСТОЯНИЙ ──
@app.on_message(filters.private & ~filters.command(["start", "check", "report", "addscam", "removescam",
    "accept", "reject", "ban", "unban", "givesub", "rmsub", "premium", "myid",
    "autosetdelay", "autosettext", "setlog", "grouplist", "search", "export",
    "sync", "vote", "broadcast", "info", "base", "alert", "mystats", "myreports",
    "warn", "tag", "untag", "tags", "mysub", "autosetprivate", "reverse", "activate"]))
async def handle_state_message(client, message: Message):
    user = message.from_user
    state_info = get_state(user.id)
    if not state_info:
        if is_admin(user.id, user.username):
            return
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO bot_users (user_id, username, first_name, last_active, date) VALUES (?,?,?,?,?)",
            (user.id, user.username or "", user.first_name or "",
             datetime.now().strftime("%d.%m.%Y %H:%M"), datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        c.execute("SELECT * FROM private_autoresponder WHERE id=1")
        ar = c.fetchone(); conn.close()
        if ar and ar["enabled"]:
            delay = ar["delay_seconds"]
            text_r = ar["response_text"]
            await asyncio.sleep(delay)
            await message.reply(text_r)
        return
    state = state_info["state"]
    text = message.text or ""

    if state == "addscam_user":
        clear_state(user.id)
        uname = text.lstrip("@").strip()
        if not uname:
            await message.reply("❌ Введите @username"); return
        set_state(user.id, "addscam_reason", {"username": uname})
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await message.reply(f"📝 Теперь введите причину для @{uname}:", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "addscam_reason":
        uname = state_info["data"]["username"]
        reason = text.strip()
        clear_state(user.id)
        if not reason:
            await message.reply("❌ Введите причину"); return
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO scammers (user_id, username, first_name, reason, added_by, added_by_name, date) VALUES (?,?,?,?,?,?,?)",
                  (0, uname, "", reason, user.id, user.username or user.first_name, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await message.reply(f"✅ @{uname} добавлен в базу скамеров.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "removescam_user":
        clear_state(user.id)
        uname = text.lstrip("@").strip()
        if not uname:
            await message.reply("❌ Введите @username"); return
        conn = get_db(); c = conn.cursor()
        c.execute("DELETE FROM scammers WHERE username=?", (uname,))
        d = c.rowcount; conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        if d:
            await message.reply(f"✅ @{uname} удалён из базы.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await message.reply(f"❌ @{uname} не найден в базе.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "accept_id":
        clear_state(user.id)
        if not text.isdigit():
            await message.reply("❌ Введите числовой ID жалобы"); return
        cid = int(text)
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE id=? AND status='pending'", (cid,))
        comp = c.fetchone()
        if not comp:
            conn.close(); await message.reply("❌ Жалоба не найдена или уже обработана."); return
        uname = comp['target_username']
        c.execute("UPDATE complaints SET status='accepted' WHERE id=?", (cid,))
        if uname:
            c.execute("SELECT * FROM scammers WHERE username=?", (uname,))
            if not c.fetchone():
                c.execute("INSERT INTO scammers (user_id, username, first_name, reason, added_by, added_by_name, date) VALUES (?,?,?,?,?,?,?)",
                          (comp['target_user_id'] or 0, uname, comp['target_name'] or "", comp['reason'],
                           comp['reporter_id'], comp['reporter_name'], datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await message.reply(f"✅ Жалоба #{cid} одобрена. @{uname} добавлен в базу.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "reject_id":
        clear_state(user.id)
        if not text.isdigit():
            await message.reply("❌ Введите числовой ID жалобы"); return
        cid = int(text)
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE complaints SET status='rejected' WHERE id=? AND status='pending'", (cid,))
        d = c.rowcount; conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        if d:
            await message.reply(f"✅ Жалоба #{cid} отклонена.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await message.reply("❌ Жалоба не найдена.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "ban_user":
        clear_state(user.id)
        uname = text.lstrip("@").strip()
        if not uname:
            await message.reply("❌ Введите @username"); return
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
        row = c.fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (row['user_id'],))
            conn.commit(); conn.close()
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await message.reply(f"🚫 @{uname} забанен.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            conn.close()
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await message.reply(f"❌ @{uname} не найден.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "unban_user":
        clear_state(user.id)
        uname = text.lstrip("@").strip()
        if not uname:
            await message.reply("❌ Введите @username"); return
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM banned WHERE user_id=?", (row['user_id'],))
            conn.commit(); conn.close()
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await message.reply(f"✅ @{uname} разбанен.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            conn.close()
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await message.reply(f"❌ @{uname} не найден.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "warn_user":
        clear_state(user.id)
        if not text.isdigit():
            await message.reply("❌ Введите числовой user_id"); return
        uid = int(text)
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM user_profiles WHERE user_id=?", (uid,))
        prof = c.fetchone()
        if prof:
            new_warns = prof['warns'] + 1
            if new_warns >= 3:
                c.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (uid,))
                c.execute("DELETE FROM user_profiles WHERE user_id=?", (uid,))
                conn.commit(); conn.close()
                kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
                await message.reply(f"🚫 User {uid} забанен (3 преда).", reply_markup=InlineKeyboardMarkup(kb))
            else:
                c.execute("UPDATE user_profiles SET warns=? WHERE user_id=?", (new_warns, uid))
                conn.commit(); conn.close()
                kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
                await message.reply(f"⚠️ User {uid}: {new_warns}/3 предов.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            conn.close()
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await message.reply(f"❌ User {uid} не найден.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "broadcast_text":
        clear_state(user.id)
        kb = [
            [InlineKeyboardButton("✅ Да, разослать", callback_data="broadcast_confirm")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")],
        ]
        set_state(user.id, "broadcast_pending", {"text": text})
        preview = text[:500] + "..." if len(text) > 500 else text
        await message.reply(
            f"📢 **Предпросмотр рассылки:**\n\n{preview}\n\nОтправить всем пользователям?",
            reply_markup=InlineKeyboardMarkup(kb))

    elif state == "givesub_user":
        clear_state(user.id)
        uname = text.lstrip("@").strip()
        if not uname:
            await message.reply("❌ Введите @username"); return
        set_state(user.id, "givesub_tarif", {"username": uname})
        kb = [
            [InlineKeyboardButton("1 день", callback_data="givedur_1"), InlineKeyboardButton("7 дней", callback_data="givedur_7")],
            [InlineKeyboardButton("30 дней", callback_data="givedur_30"), InlineKeyboardButton("90 дней", callback_data="givedur_90")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")],
        ]
        await message.reply(f"💎 Выберите тариф для @{uname}:", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "rmsub_user":
        clear_state(user.id)
        uname = text.lstrip("@").strip()
        if not uname:
            await message.reply("❌ Введите @username"); return
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE subscriptions SET active=0 WHERE username=?", (uname,))
        d = c.rowcount; conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        if d:
            await message.reply(f"✅ Подписка @{uname} отозвана.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await message.reply(f"❌ Подписка @{uname} не найдена.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "tag_user":
        uname = text.lstrip("@").strip()
        tag = state_info["data"].get("tag")
        clear_state(user.id)
        if not uname or not tag:
            await message.reply("❌ Введите @username"); return
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO user_tags (target_username, tag, set_by, set_by_name, date) VALUES (?,?,?,?,?)",
                  (uname, tag, user.id, user.username or user.first_name, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_tags")]]
        tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡",
                      "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
        emoji = tag_emojis.get(tag, "⚪")
        await message.reply(f"{emoji} Метка «{tag}» поставлена @{uname}.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "untag_user":
        uname = text.lstrip("@").strip()
        clear_state(user.id)
        if not uname:
            await message.reply("❌ Введите @username"); return
        conn = get_db(); c = conn.cursor()
        c.execute("DELETE FROM user_tags WHERE target_username=?", (uname,))
        d = c.rowcount; conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_tags")]]
        if d:
            await message.reply(f"🗑 Все метки @{uname} удалены.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await message.reply(f"❌ У @{uname} нет меток.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_check":
        clear_state(user.id)
        arg = text.lstrip("@").strip()
        if not arg:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Введите @username или ID", reply_markup=InlineKeyboardMarkup(kb)); return
        conn = get_db(); c = conn.cursor()
        row = None
        if arg.isdigit():
            c.execute("SELECT * FROM scammers WHERE user_id=?", (int(arg),))
            row = c.fetchone()
        if not row:
            c.execute("SELECT * FROM scammers WHERE username=?", (arg,))
            row = c.fetchone()
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        result = "scammer" if row else "clean"
        checked_name = f"@{arg}" if not arg.isdigit() else f"ID:{arg}"
        c.execute("INSERT INTO check_history (user_id, checked_username, result, date) VALUES (?,?,?,?)",
                  (user.id, checked_name, result, now))
        if row:
            c.execute("SELECT user_id FROM user_alerts WHERE target_username=? AND active=1", (arg,))
            for au in c.fetchall():
                try:
                    await client.send_message(au["user_id"],
                        f"🔔 **ОПОВЕЩЕНИЕ**\n\nПользователь @{arg} проверен — **СКАМЕР**!\n"
                        f"📝 {row['reason']}\n📅 {row['date']}")
                except Exception:
                    pass
        conn.commit(); conn.close()
        if row:
            u = f"@{row['username']}" if row['username'] else f"ID: {row['user_id']}"
            tag_conn = get_db(); tc = tag_conn.cursor()
            tag_emojis = {"мошенник": "🔴", "скамер": "🔴", "подозреваемый": "🟡", "проверенный": "🟢", "чисто": "🟢", "под подозрением": "🟡"}
            tc.execute("SELECT tag FROM user_tags WHERE target_username=?", (arg,))
            tags = tc.fetchall(); tag_conn.close()
            tag_line = ""
            if tags:
                tag_line = "\n🏷 " + " ".join(f"{tag_emojis.get(t['tag'], '⚪')} {t['tag']}" for t in tags)
            kb = [[InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")],
                  [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply(
                f"🚨 **СКАМЕР**\n\n👤 {u} ({row['first_name']})\n"
                f"📝 {row['reason']}\n👮 {row['added_by_name']}\n📅 {row['date']}{tag_line}",
                reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")],
                  [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply(f"✅ @{arg} — чисто.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_report_user":
        uname = text.lstrip("@").strip()
        if not uname:
            clear_state(user.id)
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Введите @username", reply_markup=InlineKeyboardMarkup(kb)); return
        set_state(user.id, "user_report_reason", {"username": uname})
        kb = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_state")]]
        await message.reply(f"🚨 Введите причину жалобы на @{uname}:", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_report_reason":
        uname = state_info["data"]["username"]
        reason = text.strip()
        clear_state(user.id)
        if not reason:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Введите причину", reply_markup=InlineKeyboardMarkup(kb)); return
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
        r = c.fetchone()
        uid = r['user_id'] if r else 0
        c.execute("INSERT INTO complaints (reporter_id, reporter_name, target_user_id, target_username, target_name, reason, status, date) VALUES (?,?,?,?,?,?,?,?)",
                  (user.id, user.username or user.first_name, uid, uname, "", reason, "pending",
                   datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
        await message.reply(f"✅ Жалоба на @{uname} отправлена на модерацию.\n📝 {reason}", reply_markup=InlineKeyboardMarkup(kb))
        for admin_id in ADMIN_USER_IDS:
            try:
                await client.send_message(admin_id,
                    f"📩 **НОВАЯ ЖАЛОБА**\n\n👤 @{uname}\n📝 {reason}\n👮 От: @{user.username or user.id}")
            except Exception:
                pass

    elif state == "user_alert_add":
        uname = text.lstrip("@").strip()
        clear_state(user.id)
        if not uname:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Введите @username", reply_markup=InlineKeyboardMarkup(kb)); return
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM user_alerts WHERE user_id=? AND target_username=? AND active=1", (user.id, uname))
        if c.fetchone():
            conn.close()
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="alerts_menu")]]
            await message.reply(f"🔔 Уже следите за @{uname}!", reply_markup=InlineKeyboardMarkup(kb)); return
        c.execute("INSERT INTO user_alerts (user_id, target_username, date) VALUES (?,?,?)",
                  (user.id, uname, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Оповещения", callback_data="alerts_menu")]]
        await message.reply(f"🔔 Теперь следите за @{uname}! Уведомление при проверке.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_alert_off":
        uname = text.lstrip("@").strip()
        clear_state(user.id)
        if not uname:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Введите @username", reply_markup=InlineKeyboardMarkup(kb)); return
        conn = get_db(); c = conn.cursor()
        c.execute("UPDATE user_alerts SET active=0 WHERE user_id=? AND target_username=?", (user.id, uname))
        d = c.rowcount; conn.commit(); conn.close()
        kb = [[InlineKeyboardButton("🔙 Оповещения", callback_data="alerts_menu")]]
        if d:
            await message.reply(f"🔔 Оповещение @{uname} отключено.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await message.reply(f"❌ Оповещение @{uname} не найдено.", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_reverse_phone":
        query = text.strip()
        clear_state(user.id)
        if not query:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="reverse_menu")]]
            await message.reply("❌ Введите номер телефона", reply_markup=InlineKeyboardMarkup(kb)); return
        await message.reply("🔍 Ищу...")
        try:
            target_user = await client.get_users(query)
        except Exception:
            target_user = None
        if target_user:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply(
                f"📱 **Найден**\n\n👤 {target_user.first_name}\n🆔 `{target_user.id}`\n📛 @{target_user.username or 'нет'}",
                reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Пользователь не найден", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_reverse_username":
        uname = text.lstrip("@").strip()
        clear_state(user.id)
        if not uname:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="reverse_menu")]]
            await message.reply("❌ Введите @username", reply_markup=InlineKeyboardMarkup(kb)); return
        await message.reply("🔍 Ищу...")
        try:
            target_user = await client.get_users(uname)
        except Exception:
            target_user = None
        if target_user:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply(
                f"👤 **Найден**\n\n👤 {target_user.first_name}\n🆔 `{target_user.id}`\n📛 @{target_user.username or 'нет'}",
                reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Пользователь не найден", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "user_reverse_id":
        clear_state(user.id)
        if not text.strip().isdigit():
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="reverse_menu")]]
            await message.reply("❌ Введите числовой ID", reply_markup=InlineKeyboardMarkup(kb)); return
        uid = int(text.strip())
        await message.reply("🔍 Ищу...")
        try:
            target_user = await client.get_users(uid)
        except Exception:
            target_user = None
        if target_user:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply(
                f"🆔 **Найден**\n\n👤 {target_user.first_name}\n🆔 `{target_user.id}`\n📛 @{target_user.username or 'нет'}",
                reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
            await message.reply("❌ Пользователь не найден", reply_markup=InlineKeyboardMarkup(kb))

    else:
        clear_state(user.id)


@app.on_message(filters.private & filters.command("autosetprivate"))
async def cmd_autosetprivate(client, message: Message):
    user = message.from_user
    if not is_admin(user.id, user.username):
        return

    args = message.command
    if len(args) < 2:
        await message.reply(
            "🤖 **Автоответчик личных сообщений**\n\n"
            "/autosetprivate on — включить\n"
            "/autosetprivate off — выключить\n"
            "/autosetprivate delay 10 — задержка (сек)\n"
            "/autosetprivate text Привет! — текст ответа"
        )
        return

    subcmd = args[1].lower()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO private_autoresponder (id) VALUES (1)")

    if subcmd == "on":
        c.execute("UPDATE private_autoresponder SET enabled=1 WHERE id=1")
        conn.commit(); conn.close()
        await message.reply("✅ Автоответчик в личку ВКЛЁН.")
    elif subcmd == "off":
        c.execute("UPDATE private_autoresponder SET enabled=0 WHERE id=1")
        conn.commit(); conn.close()
        await message.reply("❌ Автоответчик лички ВЫКЛЮЧЕН.")
    elif subcmd == "delay" and len(args) > 2:
        try:
            d = int(args[2])
            c.execute("UPDATE private_autoresponder SET delay_seconds=? WHERE id=1", (d,))
            conn.commit(); conn.close()
            await message.reply(f"⏱ Задержка: {d} сек.")
        except ValueError:
            conn.close(); await message.reply("Числом!")
    elif subcmd == "text":
        txt = " ".join(args[2:])
        c.execute("UPDATE private_autoresponder SET response_text=? WHERE id=1", (txt,))
        conn.commit(); conn.close()
        await message.reply(f"📝 Текст автоответчика:\n{txt}")
    else:
        conn.close()
        await message.reply("/autosetprivate on|off|delay|text")

# ── MAIN ──
if __name__ == "__main__":
    init_db()
    conn = get_db(); c = conn.cursor()
    for uname in ADMIN_USERNAMES:
        c.execute("SELECT user_id FROM bot_users WHERE username=?", (uname,))
        row = c.fetchone()
        if row and row['user_id'] not in ADMIN_USER_IDS:
            ADMIN_USER_IDS.append(row['user_id'])
    conn.close()
    logger.info(f"Admin IDs: {ADMIN_USER_IDS}")
    logger.info("Бот запущен!")
    app.run()
