import logging
import sqlite3
import os
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, ChatMemberUpdated, ChatMember,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ChatMemberHandler, ContextTypes, filters,
)

TOKEN = "8974338004:AAG5GpQhPJholUAgTF629NhZQfQ-T1HyBys"
ADMIN_USERNAMES = ["Xomka132"]
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scammers.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS scammers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, first_name TEXT,
        reason TEXT, added_by INTEGER, added_by_name TEXT, date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER, reporter_name TEXT,
        target_user_id INTEGER, target_username TEXT, target_name TEXT,
        reason TEXT, status TEXT DEFAULT 'pending', date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS banned (
        user_id INTEGER PRIMARY KEY
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS premium_users (
        user_id INTEGER PRIMARY KEY, username TEXT, activated_date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT,
        sub_type TEXT DEFAULT 'basic',
        start_date TEXT, end_date TEXT,
        active INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS auto_responder (
        chat_id INTEGER PRIMARY KEY,
        enabled INTEGER DEFAULT 0,
        delay_minutes INTEGER DEFAULT 60,
        response_text TEXT DEFAULT 'Автоматический ответ: я сейчас занят, отвечу позже!'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_settings (
        chat_id INTEGER PRIMARY KEY,
        chat_title TEXT,
        scam_check INTEGER DEFAULT 1,
        welcome INTEGER DEFAULT 1,
        welcome_text TEXT DEFAULT 'Добро пожаловать! Я проверяю участников на скам.',
        auto_reply INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_activity (
        user_id INTEGER, chat_id INTEGER, last_message TEXT, last_time TEXT,
        PRIMARY KEY (user_id, chat_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, chat_id INTEGER,
        reason TEXT, given_by TEXT, date TEXT
    )""")
    conn.commit()
    conn.close()


def is_admin(user):
    return user.username and user.username in ADMIN_USERNAMES


def has_subscription(user_id):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute(
        "SELECT * FROM subscriptions WHERE user_id=? AND active=1 AND end_date>?",
        (user_id, now)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return True
    c2 = get_db()
    c2.execute("UPDATE subscriptions SET active=0 WHERE active=1 AND end_date<=?", (now,))
    c2.connection.commit()
    c2.connection.close()
    return False


def is_premium(user):
    return True


def is_banned(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM banned WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r is not None


def get_scammer_info(query):
    conn = get_db()
    c = conn.cursor()
    row = None
    if query.isdigit():
        c.execute("SELECT * FROM scammers WHERE user_id=?", (int(query),))
        row = c.fetchone()
    if not row:
        c.execute("SELECT * FROM scammers WHERE username=?", (query.lstrip("@"),))
        row = c.fetchone()
    conn.close()
    return row


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM subscriptions WHERE user_id=? AND active=1 AND end_date>?",
              (user.id, datetime.now().strftime("%Y-%m-%d %H:%M")))
    sub = c.fetchone()
    conn.close()

    if not sub and not is_admin(user):
        keyboard = [[InlineKeyboardButton("Купить подписку", callback_data="buy_sub")]]
        await update.message.reply_text(
            "🔒 У тебя нет подписки!\n\n"
            "Для использования бота нужна активная подписка.\n"
            "Нажми кнопку ниже чтобы купить.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    premium_badge = "⭐" if is_premium(user) else ""
    admin_badge = " 👑" if is_admin(user) else ""
    sub_badge = " 🔓" if sub else ""

    keyboard = [
        [InlineKeyboardButton("🔍 Проверить юзера", callback_data="check"),
         InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")],
        [InlineKeyboardButton("⭐ Premium", callback_data="premium_menu"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("📋 Моя подписка", callback_data="my_sub")],
    ]
    if is_admin(user):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])

    await update.message.reply_text(
        f"🛡 KATSUROSECURITY{premium_badge}{admin_badge}{sub_badge}\n\n"
        f"Привет, {user.first_name}!\n"
        f"База скамеров. Проверяй, жалуйся, защищайся.\n\n"
        f"Команды:\n"
        f"/check — проверить юзера\n"
        f"/report — пожаловаться\n"
        f"/premium — премиум статус\n"
        f"/myid — мой ID",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "back_main":
        keyboard = [
            [InlineKeyboardButton("🔍 Проверить юзера", callback_data="check"),
             InlineKeyboardButton("🚨 Пожаловаться", callback_data="report")],
            [InlineKeyboardButton("⭐ Premium", callback_data="premium_menu"),
             InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("📋 Моя подписка", callback_data="my_sub")],
        ]
        if is_admin(user):
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
        await query.edit_message_text("Главное меню:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "buy_sub":
        keyboard = [
            [InlineKeyboardButton("1 день — 50₽", callback_data="sub_1d"),
             InlineKeyboardButton("7 дней — 250₽", callback_data="sub_7d")],
            [InlineKeyboardButton("30 дней — 800₽", callback_data="sub_30d"),
             InlineKeyboardButton("90 дней — 2000₽", callback_data="sub_90d")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "💎 Каталог подписок\n\n"
            "1 день — 50₽\n"
            "7 дней — 250₽\n"
            "30 дней — 800₽\n"
            "90 дней — 2000₽\n\n"
            "Оплата: перевод админу @Xomka132\n"
            "После оплаты нажми на тариф.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("sub_"):
        if not is_admin(user):
            sub_type = data.replace("sub_", "")
            days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
            days = days_map.get(sub_type, 1)
            start_d = datetime.now()
            end_d = start_d + timedelta(days=days)
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "INSERT INTO subscriptions (user_id, username, sub_type, start_date, end_date, active) VALUES (?,?,?,?,?,?)",
                (user.id, user.username or user.first_name, sub_type,
                 start_d.strftime("%Y-%m-%d %H:%M"), end_d.strftime("%Y-%m-%d %H:%M"), 1)
            )
            conn.commit()
            conn.close()
            await query.edit_message_text(
                f"✅ Подписка активирована!\n\n"
                f"Тариф: {sub_type}\n"
                f"Действует до: {end_d.strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            await query.edit_message_text("Админу подписка не нужна — у тебя полный доступ!")
        return

    if data == "my_sub":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM subscriptions WHERE user_id=? AND active=1 AND end_date>?",
                  (user.id, datetime.now().strftime("%Y-%m-%d %H:%M")))
        sub = c.fetchone()
        conn.close()
        if sub:
            await query.edit_message_text(
                "📋 Твоя подписка\n\n"
                f"Тип: {sub['sub_type']}\n"
                f"Активна с: {sub['start_date']}\n"
                f"Действует до: {sub['end_date']}\n"
                f"Статус: ✅ Активна"
            )
        else:
            keyboard = [[InlineKeyboardButton("Купить подписку", callback_data="buy_sub")]]
            await query.edit_message_text(
                "❌ У тебя нет активной подписки.\nНажми кнопку чтобы купить.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return

    if data == "check":
        await query.edit_message_text(
            "🔍 Проверка:\n\n"
            "/check @username\n/check 123456789\nИли реплай: /check"
        )
        return

    if data == "report":
        await query.edit_message_text(
            "🚨 Жалоба:\n\n"
            "/report @username причина\nИли реплай: /report причина"
        )
        return

    if data == "premium_menu":
        prem = "✅ Активен" if is_premium(user) else "❌ Не активен"
        keyboard = [
            [InlineKeyboardButton("✅ Активировать", callback_data="activate_premium")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            f"⭐ Premium\n\nСтатус: {prem}\n\n"
            "Привилегии:\n• ⭐ при проверке\n• Приоритет в жалобах\n"
            "• Эксклюзивные функции\n• Зелёная подсветка\n\n💰 БЕСПЛАТНО!",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "activate_premium":
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO premium_users (user_id, username, activated_date) VALUES (?,?,?)",
                  (user.id, user.username or user.first_name, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        conn.close()
        await query.edit_message_text("⭐ Premium активирован!")
        return

    if data == "stats":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM scammers"); scam = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM complaints WHERE status='pending'"); pend = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM complaints"); tot = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM subscriptions WHERE active=1"); subs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM group_settings"); groups = c.fetchone()[0]
        conn.close()
        await query.edit_message_text(
            "📊 Статистика\n\n"
            f"🔴 Скамеров: {scam}\n"
            f"⏳ Жалоб в обработке: {pend}\n"
            f"📋 Всего жалоб: {tot}\n"
            f"💎 Активных подписок: {subs}\n"
            f"👥 Групп с ботом: {groups}"
        )
        return

    if data == "admin_panel":
        if not is_admin(user):
            await query.edit_message_text("⛔ Нет доступа.")
            return
        keyboard = [
            [InlineKeyboardButton("➕ Скамер", callback_data="admin_add"),
             InlineKeyboardButton("➖ Скамер", callback_data="admin_remove")],
            [InlineKeyboardButton("📋 База скамеров", callback_data="admin_list")],
            [InlineKeyboardButton("📩 Жалобы", callback_data="admin_complaints")],
            [InlineKeyboardButton("🚫 Бан", callback_data="admin_ban"),
             InlineKeyboardButton("✅ Разбан", callback_data="admin_unban")],
            [InlineKeyboardButton("💎 Подписки", callback_data="admin_subs")],
            [InlineKeyboardButton("🤖 Автоответчик", callback_data="admin_autoresp")],
            [InlineKeyboardButton("👥 Группы", callback_data="admin_groups")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
        ]
        await query.edit_message_text("⚙️ Админ-панель", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "admin_add":
        await query.edit_message_text("➕ /addscam @username причина\nИли реплай: /addscam причина")
        return
    if data == "admin_remove":
        await query.edit_message_text("➖ /removescam @username")
        return
    if data == "admin_list":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM scammers ORDER BY id DESC LIMIT 50")
        rows = c.fetchall(); conn.close()
        if not rows:
            await query.edit_message_text("📋 База пуста."); return
        text = "📋 Скамеры:\n\n"
        for r in rows:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            text += f"• {u} — {r['reason']}\n  👤 {r['added_by_name']} | {r['date']}\n\n"
        await query.edit_message_text(text[:4000])
        return
    if data == "admin_complaints":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM complaints WHERE status='pending' ORDER BY id DESC LIMIT 20")
        rows = c.fetchall(); conn.close()
        if not rows:
            await query.edit_message_text("📩 Нет жалоб."); return
        text = "📩 Жалобы:\n\n"
        for r in rows:
            u = f"@{r['target_username']}" if r['target_username'] else f"ID:{r['target_user_id']}"
            text += f"#{r['id']} | {u}\n  От: {r['reporter_name']}\n  Причина: {r['reason']}\n\n"
        text += "/accept ID | /reject ID"
        await query.edit_message_text(text[:4000])
        return
    if data == "admin_ban":
        await query.edit_message_text("🚫 /ban @username или /ban ID")
        return
    if data == "admin_unban":
        await query.edit_message_text("✅ /unban @username или /unban ID")
        return
    if data == "admin_subs":
        keyboard = [
            [InlineKeyboardButton("Выдать подписку", callback_data="admin_give_sub"),
             InlineKeyboardButton("Отозвать", callback_data="admin_rm_sub")],
            [InlineKeyboardButton("Список подписчиков", callback_data="admin_list_subs")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        ]
        await query.edit_message_text(
            "💎 Управление подписками\n\n"
            "/givesub @username 30d\n"
            "/rmsub @username\n\n"
            "Тарифы: 1d, 7d, 30d, 90d",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    if data == "admin_give_sub":
        await query.edit_message_text("💎 /givesub @username 30d\nТарифы: 1d, 7d, 30d, 90d")
        return
    if data == "admin_rm_sub":
        await query.edit_message_text("💎 /rmsub @username")
        return
    if data == "admin_list_subs":
        conn = get_db()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("SELECT * FROM subscriptions WHERE active=1 AND end_date>?", (now,))
        rows = c.fetchall(); conn.close()
        if not rows:
            await query.edit_message_text("Нет активных подписок."); return
        text = "💎 Активные подписки:\n\n"
        for r in rows:
            u = f"@{r['username']}" if r['username'] else f"ID:{r['user_id']}"
            text += f"• {u} | {r['sub_type']} | до {r['end_date']}\n"
        await query.edit_message_text(text[:4000])
        return
    if data == "admin_autoresp":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
        row = c.fetchone(); conn.close()
        status = "✅ Вкл" if row and row['enabled'] else "❌ Выкл"
        delay = row['delay_minutes'] if row else 60
        text_resp = row['response_text'] if row else "Автоответ..."
        keyboard = [
            [InlineKeyboardButton("Вкл/Выкл", callback_data="autoresp_toggle")],
            [InlineKeyboardButton("Изменить время", callback_data="autoresp_time")],
            [InlineKeyboardButton("Изменить текст", callback_data="autoresp_text")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        ]
        await query.edit_message_text(
            f"🤖 Автоответчик\n\n"
            f"Статус: {status}\n"
            f"Задержка: {delay} мин\n"
            f"Текст: {text_resp}\n\n"
            f"/autosetdelay 60\n/autosettext текст",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    if data == "autoresp_toggle":
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
        status = "включён" if new_state else "выключен"
        await query.edit_message_text(f"🤖 Автоответчик {status}.")
        return
    if data == "autoresp_time":
        await query.edit_message_text("⏱ /autosetdelay 60\n(задержка в минутах)")
        return
    if data == "autoresp_text":
        await query.edit_message_text("✏️ /autosettext текст\n(текст автоответа)")
        return
    if data == "admin_groups":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM group_settings")
        rows = c.fetchall(); conn.close()
        if not rows:
            await query.edit_message_text("Нет групп с ботом."); return
        text = "👥 Группы с ботом:\n\n"
        for r in rows:
            sc = "✅" if r['scam_check'] else "❌"
            w = "✅" if r['welcome'] else "❌"
            text += f"• {r['chat_title'] or r['chat_id']}\n  Скам-проверка: {sc} | Приветствие: {w}\n"
        await query.edit_message_text(text[:4000])
        return


async def check_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return

    target_user_id = None
    target_username = None
    target_name = None

    if update.message.reply_to_message:
        msg = update.message.reply_to_message
        target_user_id = msg.from_user.id
        target_username = msg.from_user.username
        target_name = msg.from_user.first_name
    elif context.args:
        arg = context.args[0].lstrip("@")
        try:
            target_user_id = int(arg)
        except ValueError:
            target_username = arg
            target_name = arg
    else:
        await update.message.reply_text("🔍 /check @username | /check ID | реплай: /check")
        return

    row = None
    conn = get_db()
    c = conn.cursor()
    if target_username:
        c.execute("SELECT * FROM scammers WHERE username=?", (target_username,))
        row = c.fetchone()
    if not row and target_user_id:
        c.execute("SELECT * FROM scammers WHERE user_id=?", (target_user_id,))
        row = c.fetchone()
    conn.close()

    prem = "⭐ " if is_premium(user) else ""
    if row:
        u = f"@{row['username']}" if row['username'] else f"ID: {row['user_id']}"
        await update.message.reply_text(
            f"🚨 {prem}СКАМЕР НАЙДЕН\n\n"
            f"👤 {u} ({row['first_name']})\n"
            f"📝 {row['reason']}\n"
            f"👮 {row['added_by_name']}\n"
            f"📅 {row['date']}"
        )
    else:
        display = f"@{target_username}" if target_username else f"ID: {target_user_id}"
        await update.message.reply_text(f"✅ {display} — чисто.")


async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text("🚨 /report @username причина | реплай: /report причина")
        return

    target_user_id = None
    target_username = None
    target_name = None
    reason = None

    if update.message.reply_to_message:
        msg = update.message.reply_to_message
        target_user_id = msg.from_user.id
        target_username = msg.from_user.username
        target_name = msg.from_user.first_name
        reason = " ".join(context.args) if context.args else "Не указана"
    else:
        arg = context.args[0].lstrip("@")
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Не указана"
        target_username = arg
        target_name = arg
        try:
            target_user_id = int(arg)
        except ValueError:
            pass

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO complaints (reporter_id,reporter_name,target_user_id,target_username,target_name,reason,date) VALUES (?,?,?,?,?,?,?)",
        (user.id, user.username or user.first_name, target_user_id, target_username, target_name, reason,
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    conn.commit(); conn.close()

    await update.message.reply_text(
        "✅ Жалоба отправлена!\n\n"
        f"На: @{target_username or target_name}\n"
        f"📝 {reason}\n\nАдмин рассмотрит."
    )


async def addscam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("⛔ Только для админа."); return

    target_user_id = None
    target_username = None
    target_name = None
    reason = None

    if update.message.reply_to_message:
        msg = update.message.reply_to_message
        target_user_id = msg.from_user.id
        target_username = msg.from_user.username
        target_name = msg.from_user.first_name
        reason = " ".join(context.args) if context.args else "Без описания"
    elif context.args:
        arg = context.args[0].lstrip("@")
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Без описания"
        target_username = arg
        target_name = arg
        try:
            target_user_id = int(arg)
        except ValueError:
            pass
    else:
        await update.message.reply_text("➕ /addscam @username причина | реплай: /addscam причина")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO scammers (user_id,username,first_name,reason,added_by,added_by_name,date) VALUES (?,?,?,?,?,?,?)",
        (target_user_id, target_username, target_name, reason, user.id,
         f"@{user.username}" if user.username else user.first_name,
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    conn.commit(); conn.close()
    await update.message.reply_text(f"🔴 Скамер добавлен!\n👤 @{target_username or target_name}\n📝 {reason}")


async def removescam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("⛔ Только для админа."); return
    if not context.args:
        await update.message.reply_text("➖ /removescam @username"); return

    arg = context.args[0].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM scammers WHERE username=?", (arg,))
    deleted = c.rowcount
    if not deleted:
        try:
            c.execute("DELETE FROM scammers WHERE user_id=?", (int(arg),))
            deleted = c.rowcount
        except ValueError:
            pass
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ @{arg} удалён." if deleted else f"❌ @{arg} не найден.")


async def accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID числом!"); return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints WHERE id=? AND status='pending'", (cid,))
    row = c.fetchone()
    if not row:
        conn.close(); await update.message.reply_text("❌ Не найдена."); return

    c.execute(
        "INSERT INTO scammers (user_id,username,first_name,reason,added_by,added_by_name,date) VALUES (?,?,?,?,?,?,?)",
        (row['target_user_id'], row['target_username'], row['target_name'],
         f"Жалоба #{cid}: {row['reason']}", user.id,
         f"@{user.username}" if user.username else user.first_name,
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    c.execute("UPDATE complaints SET status='accepted' WHERE id=?", (cid,))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ Жалоба #{cid} одобрена. @{row['target_username']} в базе.")


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE complaints SET status='rejected' WHERE id=? AND status='pending'", (cid,))
    changed = c.rowcount; conn.commit(); conn.close()
    await update.message.reply_text(f"❌ Жалоба #{cid} отклонена." if changed else "❌ Не найдена.")


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    arg = context.args[0].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    try:
        uid = int(arg)
        c.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (uid,))
        conn.commit(); conn.close()
        await update.message.reply_text(f"🚫 {arg} забанен.")
    except ValueError:
        c.execute("SELECT user_id FROM scammers WHERE username=?", (arg,))
        row = c.fetchone()
        if row:
            c.execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (row['user_id'],))
            conn.commit(); conn.close()
            await update.message.reply_text(f"🚫 @{arg} забанен.")
        else:
            conn.close()
            await update.message.reply_text(f"❌ @{arg} не найден. /ban ID")


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    arg = context.args[0].lstrip("@")
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
    await update.message.reply_text("✅ Разбан.")


async def givesub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        return
    if len(context.args) < 2:
        await update.message.reply_text("💎 /givesub @username 30d\nТарифы: 1d, 7d, 30d, 90d")
        return

    arg = context.args[0].lstrip("@")
    tarif = context.args[1].lower()
    days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
    if tarif not in days_map:
        await update.message.reply_text("❌ Тариф: 1d, 7d, 30d, 90d"); return

    days = days_map[tarif]
    start_d = datetime.now()
    end_d = start_d + timedelta(days=days)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM scammers WHERE username=?", (arg,))
    row = c.fetchone()
    uid = row['user_id'] if row else 0
    c.execute(
        "INSERT INTO subscriptions (user_id, username, sub_type, start_date, end_date, active) VALUES (?,?,?,?,?,?)",
        (uid, arg, tarif, start_d.strftime("%Y-%m-%d %H:%M"), end_d.strftime("%Y-%m-%d %H:%M"), 1)
    )
    conn.commit(); conn.close()
    await update.message.reply_text(f"💎 Подписка {tarif} выдана @{arg}\nДо: {end_d.strftime('%d.%m.%Y %H:%M')}")


async def rmsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    arg = context.args[0].lstrip("@")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE subscriptions SET active=0 WHERE username=?", (arg,))
    conn.commit(); conn.close()
    await update.message.reply_text(f"💎 Подписка @{arg} отозвана.")


async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return
    prem = is_premium(user)
    status = "✅ Активен" if prem else "❌ Не активен"
    keyboard = []
    if not prem:
        keyboard.append([InlineKeyboardButton("Активировать", callback_data="activate_premium")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    await update.message.reply_text(
        f"⭐ Premium\n\nСтатус: {status}\n\n"
        "Привилегии:\n• ⭐ при проверке\n• Приоритет\n• Эксклюзив",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    prem = "⭐" if is_premium(user) else ""
    admin = " 👑" if is_admin(user) else ""
    text = f"🆔 {user.id}\n"
    if user.username:
        text += f"👤 @{user.username}\n"
    text += f"📛 {user.first_name}\n{prem}{admin}"
    await update.message.reply_text(text)


async def autosetdelay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        return
    if not context.args:
        await update.message.reply_text("⏱ /autosetdelay 60"); return
    try:
        delay = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Числом!"); return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE auto_responder SET delay_minutes=? WHERE chat_id=?", (delay, user.id))
    else:
        c.execute("INSERT INTO auto_responder (chat_id, delay_minutes) VALUES (?,?)", (user.id, delay))
    conn.commit(); conn.close()
    await update.message.reply_text(f"⏱ Задержка: {delay} мин")


async def autosettext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        return
    if not context.args:
        await update.message.reply_text("✏️ /autosettext текст"); return
    text = " ".join(context.args)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auto_responder WHERE chat_id=?", (user.id,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE auto_responder SET response_text=? WHERE chat_id=?", (text, user.id))
    else:
        c.execute("INSERT INTO auto_responder (chat_id, response_text) VALUES (?,?)", (user.id, text))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ Текст: {text}")


async def group_settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM group_settings")
    rows = c.fetchall(); conn.close()

    if not rows:
        await update.message.reply_text("Нет групп."); return

    text = "👥 Группы:\n\n"
    for r in rows:
        sc = "✅" if r['scam_check'] else "❌"
        w = "✅" if r['welcome'] else "❌"
        ar = "✅" if r['auto_reply'] else "❌"
        text += f"• {r['chat_title'] or r['chat_id']}\n  Скам: {sc} | Приветствие: {w} | Автоответ: {ar}\n"
    text += "\n/togglescam ID — вкл/выскам-проверку\n/togglewelcome ID — приветствие\n/toggleautoreply ID — автоответ"
    await update.message.reply_text(text[:4000])


async def togglescam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT scam_check FROM group_settings WHERE chat_id=?", (cid,))
    row = c.fetchone()
    if row:
        new = 0 if row['scam_check'] else 1
        c.execute("UPDATE group_settings SET scam_check=? WHERE chat_id=?", (new, cid))
        conn.commit(); conn.close()
        await update.message.reply_text(f"Скам-проверка: {'вкл' if new else 'выкл'}")
    else:
        conn.close()


async def togglewelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT welcome FROM group_settings WHERE chat_id=?", (cid,))
    row = c.fetchone()
    if row:
        new = 0 if row['welcome'] else 1
        c.execute("UPDATE group_settings SET welcome=? WHERE chat_id=?", (new, cid))
        conn.commit(); conn.close()
        await update.message.reply_text(f"Приветствие: {'вкл' if new else 'выкл'}")
    else:
        conn.close()


async def toggleautoreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args:
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT auto_reply FROM group_settings WHERE chat_id=?", (cid,))
    row = c.fetchone()
    if row:
        new = 0 if row['auto_reply'] else 1
        c.execute("UPDATE group_settings SET auto_reply=? WHERE chat_id=?", (new, cid))
        conn.commit(); conn.close()
        await update.message.reply_text(f"Автоответ в группе: {'вкл' if new else 'выкл'}")
    else:
        conn.close()


async def welcome_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user) or not context.args or len(context.args) < 2:
        await update.message.reply_text("👋 /setwelcometext chat_id текст")
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID числом!"); return
    text = " ".join(context.args[1:])
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE group_settings SET welcome_text=? WHERE chat_id=?", (text, cid))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ Приветствие обновлено для {cid}")


async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    chat = update.effective_chat
    bot = context.bot
    bot_member = await chat.get_member(bot.id)
    if bot_member.status not in ('administrator', 'creator'):
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat.id,))
    gsettings = c.fetchone()
    if not gsettings:
        c.execute(
            "INSERT INTO group_settings (chat_id, chat_title) VALUES (?,?)",
            (chat.id, chat.title)
        )
        conn.commit()
        gsettings = c.fetchone() if c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat.id,)) else None
        c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat.id,))
        gsettings = c.fetchone()

    for member in update.message.new_chat_members:
        if member.id == bot.id:
            continue

        if gsettings and gsettings['welcome']:
            username = f"@{member.username}" if member.username else member.first_name
            try:
                await chat.send_message(
                    f"👋 Добро пожаловать, {member.first_name}!\n"
                    f"Я KATSUROSECURITY — проверяю участников на скам.\n"
                    f"Напиши /check чтобы проверить кого-то."
                )
            except Exception:
                pass

        if gsettings and gsettings['scam_check']:
            c2 = conn.cursor()
            uname = member.username or ""
            c2.execute("SELECT * FROM scammers WHERE username=?", (uname,))
            scam_row = c2.fetchone()
            if not scam_row:
                c2.execute("SELECT * FROM scammers WHERE user_id=?", (member.id,))
                scam_row = c2.fetchone()

            if scam_row:
                su = f"@{scam_row['username']}" if scam_row['username'] else f"ID:{scam_row['user_id']}"
                try:
                    await chat.send_message(
                        f"🚨 ВНИМАНИЕ! СКАМЕР В ГРУППЕ!\n\n"
                        f"👤 {su} ({scam_row['first_name']})\n"
                        f"📝 Причина: {scam_row['reason']}\n"
                        f"👮 Добавил: {scam_row['added_by_name']}\n"
                        f"📅 {scam_row['date']}\n\n"
                        f"⚠️ Будьте осторожны!"
                    )
                except Exception:
                    pass

    conn.commit(); conn.close()


async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat.type in ('group', 'supergroup'):
        return

    user = update.effective_user
    chat = update.effective_chat

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO user_activity (user_id, chat_id, last_message, last_time) VALUES (?,?,?,?)",
        (user.id, chat.id, update.message.text or "", datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    c.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat.id,))
    gs = c.fetchone()
    conn.commit(); conn.close()

    if gs and gs['auto_reply']:
        pass


async def check_auto_responder(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM auto_responder WHERE enabled=1")
    auto_resps = c.fetchall()

    now = datetime.now()
    for ar in auto_resps:
        chat_id = ar['chat_id']
        delay = ar['delay_minutes']
        cutoff = (now - timedelta(minutes=delay)).strftime("%Y-%m-%d %H:%M")

        c2 = conn.cursor()
        c2.execute(
            "SELECT * FROM user_activity WHERE chat_id=? AND last_time<?",
            (chat_id, cutoff)
        )
        stale = c2.fetchall()

        for s in stale:
            c2.execute("DELETE FROM user_activity WHERE user_id=? AND chat_id=?",
                       (s['user_id'], chat_id))
            try:
                await context.bot.send_message(
                    chat_id=s['user_id'],
                    text=ar['response_text']
                )
            except Exception:
                pass

    conn.commit(); conn.close()


async def error_handler(update, context):
    logger.error(f"Exception: {context.error}", exc_info=context.error)


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("check", "Проверить юзера"),
        BotCommand("report", "Пожаловаться"),
        BotCommand("premium", "Premium"),
        BotCommand("myid", "Мой ID"),
    ])


def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_user))
    app.add_handler(CommandHandler("report", report_user))
    app.add_handler(CommandHandler("addscam", addscam))
    app.add_handler(CommandHandler("removescam", removescam))
    app.add_handler(CommandHandler("accept", accept))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("givesub", givesub))
    app.add_handler(CommandHandler("rmsub", rmsub))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("autosetdelay", autosetdelay))
    app.add_handler(CommandHandler("autosettext", autosettext))
    app.add_handler(CommandHandler("grouplist", group_settings_cmd))
    app.add_handler(CommandHandler("togglescam", togglescam))
    app.add_handler(CommandHandler("togglewelcome", togglewelcome))
    app.add_handler(CommandHandler("toggleautoreply", toggleautoreply))
    app.add_handler(CommandHandler("setwelcometext", welcome_settings))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(handle_new_chat_members, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_messages))

    app.add_error_handler(error_handler)

    job_queue = app.job_queue
    job_queue.run_repeating(check_auto_responder, interval=120, first=30)

    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
