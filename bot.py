# VILAGROTEX BOT — full version
# Python 3.13 + aiogram 3.x
# Functions:
# - paid publication packages + receipt moderation
# - referral invite links with automatic rewards
# - guided ad creation with categories and conditional fields
# - 1–10 photos, preview, admin moderation, auto-post to channel
# - profile, stats, user's ads, mark sold
# - promo codes, admin tools, broadcast
# - optional AI daily posts + AI ad-description improvement via OpenAI API
# - search, favorites, subscriptions, price editing, bumps, admin buttons, backups
# - channel action buttons: seller chat, phone, favorites, details, share, report
#
# IMPORTANT:
# 1) Insert BOT_TOKEN and PAYMENT_DETAILS below.
# 2) For AI posts, insert OPENAI_API_KEY (optional).
# 3) Bot must be an admin in @VILAGROTEX with rights to post and create invite links.

import asyncio
import csv
import io
import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    FSInputFile,
)

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None


# =========================================================
# CONFIG
# =========================================================

# =========================================================
# RAILWAY / ENV CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не заданий. Додайте його в Railway → Variables."
    )

ADMIN_ID = int(os.getenv("ADMIN_ID", "7097625447"))
CHANNEL = os.getenv("CHANNEL", "@VILAGROTEX").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@v1vchaaar").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "Vilagreo_bot").strip().lstrip("@")

# Якщо до сервісу Railway підключений Volume, Railway автоматично
# задає RAILWAY_VOLUME_MOUNT_PATH. База тоді живе на постійному диску.
DATA_DIR = Path(
    os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    or os.getenv("DATA_DIR")
    or "."
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_NAME = str(DATA_DIR / "vilagro.db")

PAYMENT_DETAILS = os.getenv(
    "PAYMENT_DETAILS",
    """💳 <b>ОПЛАТА VILAGROTEX</b>

СЮДИ ВСТАВ СВОЇ РЕКВІЗИТИ В RAILWAY → VARIABLES

Після оплати натисніть <b>✅ Я оплатив</b>
та надішліть чек."""
)

REFERRALS_FOR_BONUS = 3
REFERRAL_BONUS_ADS = 1

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
AI_DAILY_ENABLED = True
AI_DAILY_HOUR = 10
AI_DAILY_MINUTE = 0
AI_AUTO_PUBLISH = False
AI_TIMEZONE = "Europe/Kyiv"

# Просування: 1 підняття списує стільки публікацій
PROMOTION_COST_ADS = 1

# Автоматичний backup бази адміну
AUTO_BACKUP_ENABLED = True
AUTO_BACKUP_HOUR = 3
AUTO_BACKUP_MINUTE = 15

DAILY_DIGEST_ENABLED = True
DAILY_DIGEST_HOUR = 19
DAILY_DIGEST_MINUTE = 30

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


PACKAGES = {
    "package_1": {"name": "1 оголошення", "count": 1, "price": 35},
    "package_5": {"name": "5 оголошень", "count": 5, "price": 150},
    "package_10": {"name": "10 оголошень", "count": 10, "price": 250},
    "package_15": {"name": "15 оголошень", "count": 15, "price": 300},
}

CATEGORIES = {
    "tractor": "🚜 Трактор",
    "combine": "🌾 Комбайн",
    "header": "🌽 Жатка",
    "plow": "🔩 Плуг",
    "ripper": "🟤 Глибокорозпушувач",
    "seeder": "🌱 Сівалка",
    "cultivator": "⚙️ Культиватор",
    "disc": "⭕ Дискова борона",
    "sprayer": "💦 Обприскувач",
    "loader": "🏗 Навантажувач",
    "mower": "🌿 Косарка",
    "baler": "📦 Прес-підбирач",
    "trailer": "🚛 Причіп",
    "spreader": "🧂 Розкидач добрив",
    "harrow": "🪚 Борона",
    "other": "⚙️ Інша техніка",
}

HOURS_CATEGORIES = {"tractor", "combine"}

REGIONS = [
    "Вінницька", "Волинська", "Дніпропетровська", "Донецька",
    "Житомирська", "Закарпатська", "Запорізька", "Івано-Франківська",
    "Київська", "Кіровоградська", "Луганська", "Львівська",
    "Миколаївська", "Одеська", "Полтавська", "Рівненська",
    "Сумська", "Тернопільська", "Харківська", "Херсонська",
    "Хмельницька", "Черкаська", "Чернівецька", "Чернігівська",
]


class PaymentStates(StatesGroup):
    waiting_receipt = State()


class AdStates(StatesGroup):
    photos = State()
    category = State()
    model = State()
    year = State()
    hours = State()
    price = State()
    region = State()
    description = State()
    description_review = State()
    phone = State()
    preview = State()


class PromoStates(StatesGroup):
    waiting_code = State()


class BroadcastStates(StatesGroup):
    waiting_message = State()


class SearchStates(StatesGroup):
    category = State()
    region = State()


class EditPriceStates(StatesGroup):
    waiting_price = State()


class OfferStates(StatesGroup):
    waiting_amount = State()


class SearchAlertStates(StatesGroup):
    category = State()
    region = State()
    keyword = State()


def connect_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def add_column_if_missing(cursor, table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    names = [row[1] for row in cursor.fetchall()]
    if column not in names:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_tables():
    conn = connect_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            ads_balance INTEGER DEFAULT 0,
            total_bought INTEGER DEFAULT 0,
            total_published INTEGER DEFAULT 0,
            referrals_count INTEGER DEFAULT 0,
            referral_rewards INTEGER DEFAULT 0,
            registered_at TEXT
        )
    """)
    for col, definition in [
        ("referrals_count", "INTEGER DEFAULT 0"),
        ("referral_rewards", "INTEGER DEFAULT 0"),
        ("verified", "INTEGER DEFAULT 0"),
        ("notifications_enabled", "INTEGER DEFAULT 1"),
    ]:
        add_column_if_missing(c, "users", col, definition)

    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            package_name TEXT,
            ads_count INTEGER,
            price INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            receipt_file_id TEXT,
            receipt_type TEXT,
            reviewed_at TEXT
        )
    """)
    for col, definition in [
        ("receipt_file_id", "TEXT"),
        ("receipt_type", "TEXT"),
        ("reviewed_at", "TEXT"),
    ]:
        add_column_if_missing(c, "purchases", col, definition)

    c.execute("""
        CREATE TABLE IF NOT EXISTS referral_links (
            user_id INTEGER PRIMARY KEY,
            invite_link TEXT UNIQUE NOT NULL,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_user_id INTEGER UNIQUE NOT NULL,
            invite_link TEXT,
            joined_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            photos_json TEXT NOT NULL,
            category_code TEXT,
            category_name TEXT,
            model TEXT,
            year INTEGER,
            hours INTEGER,
            price TEXT,
            region TEXT,
            description TEXT,
            phone TEXT,
            status TEXT DEFAULT 'draft',
            created_at TEXT,
            reviewed_at TEXT,
            published_at TEXT,
            channel_message_ids TEXT,
            reject_reason TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            ads_count INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 1,
            uses INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            used_at TEXT,
            UNIQUE(code, user_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            created_at TEXT,
            published_at TEXT
        )
    """)

    add_column_if_missing(c, "ads", "last_bumped_at", "TEXT")
    add_column_if_missing(c, "ads", "favorite_count", "INTEGER DEFAULT 0")
    add_column_if_missing(c, "ads", "seller_clicks", "INTEGER DEFAULT 0")
    add_column_if_missing(c, "ads", "action_message_id", "INTEGER")
    add_column_if_missing(c, "ads", "detail_views", "INTEGER DEFAULT 0")
    add_column_if_missing(c, "ads", "contact_clicks", "INTEGER DEFAULT 0")

    c.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL,
            ad_id INTEGER NOT NULL,
            created_at TEXT,
            UNIQUE(user_id, ad_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER NOT NULL,
            category_code TEXT NOT NULL,
            created_at TEXT,
            UNIQUE(user_id, category_code)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ad_id INTEGER NOT NULL,
            cost_ads INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ad_id INTEGER NOT NULL,
            created_at TEXT,
            UNIQUE(user_id, ad_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ad_drafts (
            user_id INTEGER PRIMARY KEY,
            data_json TEXT NOT NULL,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id INTEGER NOT NULL,
            old_price TEXT,
            new_price TEXT NOT NULL,
            changed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            amount TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            reviewed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS search_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category_code TEXT NOT NULL,
            region TEXT NOT NULL,
            keyword TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def register_user(user):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    exists = c.fetchone()
    if exists:
        c.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (user.username, user.first_name, user.id),
        )
    else:
        c.execute("""
            INSERT INTO users (
                user_id, username, first_name, ads_balance,
                total_bought, total_published,
                referrals_count, referral_rewards, registered_at
            )
            VALUES (?, ?, ?, 0, 0, 0, 0, 0, ?)
        """, (
            user.id,
            user.username,
            user.first_name,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
        ))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_purchase(purchase_id):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM purchases WHERE id=?", (purchase_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_ad(ad_id):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
    row = c.fetchone()
    conn.close()
    return row


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Виставити оголошення")],
            [
                KeyboardButton(text="🔎 Знайти техніку"),
                KeyboardButton(text="❤️ Обране"),
            ],
            [
                KeyboardButton(text="📦 Мої оголошення"),
                KeyboardButton(text="📝 Чернетка"),
            ],
            [
                KeyboardButton(text="👤 Мій профіль"),
                KeyboardButton(text="📊 Статистика"),
            ],
            [
                KeyboardButton(text="💳 Купити пакет"),
                KeyboardButton(text="🎁 Запросити друга"),
            ],
            [
                KeyboardButton(text="🔔 Підписки"),
                KeyboardButton(text="🎟 Промокод"),
            ],
            [
                KeyboardButton(text="📈 Кабінет продавця"),
                KeyboardButton(text="📢 Перейти на канал"),
            ],
            [
                KeyboardButton(text="☎️ Підтримка"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Оберіть потрібний розділ",
    )


def packages_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 1 оголошення — 35 грн", callback_data="package_1")],
        [InlineKeyboardButton(text="📦 5 оголошень — 150 грн", callback_data="package_5")],
        [InlineKeyboardButton(text="🔥 10 оголошень — 250 грн", callback_data="package_10")],
        [InlineKeyboardButton(text="💎 15 оголошень — 300 грн", callback_data="package_15")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")],
    ])


def category_keyboard():
    rows = []
    pairs = [
        ("tractor", "combine"),
        ("header", "plow"),
        ("ripper", "seeder"),
        ("cultivator", "disc"),
        ("sprayer", "loader"),
        ("mower", "baler"),
        ("trailer", "spreader"),
        ("harrow", "other"),
    ]
    for left, right in pairs:
        rows.append([
            InlineKeyboardButton(text=CATEGORIES[left], callback_data=f"cat:{left}"),
            InlineKeyboardButton(text=CATEGORIES[right], callback_data=f"cat:{right}"),
        ])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад до фото", callback_data="ad:back_photos")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def regions_keyboard():
    rows = []
    for i in range(0, len(REGIONS), 2):
        row = []
        for region in REGIONS[i:i+2]:
            row.append(
                InlineKeyboardButton(
                    text=region,
                    callback_data=f"region:{REGIONS.index(region)}",
                )
            )
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад до ціни", callback_data="ad:back_price")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def promo_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )



def search_category_keyboard():
    rows = [[
        InlineKeyboardButton(text="🚜 Уся техніка", callback_data="searchcat:all")
    ]]
    pairs = [
        ("tractor", "combine"),
        ("header", "plow"),
        ("ripper", "seeder"),
        ("cultivator", "disc"),
        ("sprayer", "loader"),
        ("mower", "baler"),
        ("trailer", "spreader"),
        ("harrow", "other"),
    ]
    for left, right in pairs:
        rows.append([
            InlineKeyboardButton(text=CATEGORIES[left], callback_data=f"searchcat:{left}"),
            InlineKeyboardButton(text=CATEGORIES[right], callback_data=f"searchcat:{right}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_region_keyboard(category_code):
    rows = [[
        InlineKeyboardButton(text="📍 Вся Україна", callback_data=f"sreg:{category_code}:all")
    ]]
    for i in range(0, len(REGIONS), 2):
        row = []
        for idx in range(i, min(i + 2, len(REGIONS))):
            row.append(
                InlineKeyboardButton(
                    text=REGIONS[idx],
                    callback_data=f"sreg:{category_code}:{idx}",
                )
            )
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="⬅️ До категорій", callback_data="search:back_categories")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscriptions_keyboard(user_id):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT category_code FROM subscriptions WHERE user_id=?", (user_id,))
    active = {r["category_code"] for r in c.fetchall()}
    conn.close()

    rows = []
    for code, title in CATEGORIES.items():
        mark = "✅" if code in active else "➕"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {title}",
                callback_data=f"subtoggle:{code}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_description_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✨ Покращити AI", callback_data="ad:ai_desc"),
            InlineKeyboardButton(text="✅ Залишити мій", callback_data="ad:keep_desc"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад до опису", callback_data="ad:back_desc")],
    ])


def ai_description_result_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Використати AI", callback_data="ad:use_ai_desc")],
        [InlineKeyboardButton(text="🔄 Ще варіант", callback_data="ad:ai_desc")],
        [InlineKeyboardButton(text="↩️ Залишити мій опис", callback_data="ad:keep_desc")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ad:back_desc")],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
            InlineKeyboardButton(text="⏳ Модерація", callback_data="admin:moderation"),
        ],
        [
            InlineKeyboardButton(text="💳 Оплати", callback_data="admin:payments"),
            InlineKeyboardButton(text="🤖 AI-пост", callback_data="admin:aipost"),
        ],
        [
            InlineKeyboardButton(text="📢 Розсилка", callback_data="admin:broadcast"),
            InlineKeyboardButton(text="💾 Backup", callback_data="admin:backup"),
        ],
    ])


def photos_done_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Фото готові — далі", callback_data="ad:photos_done")],
        [InlineKeyboardButton(text="⬅️ Назад у меню", callback_data="menu:home")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="ad:cancel")],
    ])


def preview_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Надіслати на модерацію", callback_data="ad:submit")],
        [InlineKeyboardButton(text="⬅️ Назад до контактів", callback_data="ad:back_phone")],
        [InlineKeyboardButton(text="🔄 Почати заново", callback_data="ad:restart")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="ad:cancel")],
    ])


def contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Надіслати мій номер", request_contact=True)],
            [KeyboardButton(text="✍️ Ввести номер вручну")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )



def normalize_phone(phone):
    if not phone:
        return None
    raw = str(phone).strip()
    if raw.startswith("@"):
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 9:
        return None
    if digits.startswith("0") and len(digits) == 10:
        digits = "38" + digits
    if not digits.startswith("+"):
        return "+" + digits
    return digits


def seller_chat_url(ad):
    seller = get_user(ad["user_id"])
    if seller and seller["username"]:
        return f"https://t.me/{seller['username']}"
    # Telegram supports tg://user?id=<id> links, subject to user privacy settings.
    return f"tg://user?id={ad['user_id']}"


def channel_post_url_from_id(message_id):
    return f"https://t.me/{CHANNEL.lstrip('@')}/{message_id}"


def public_ad_keyboard(ad, post_url=None, favorite_mode="add"):
    favorite_text = "💔 Прибрати з обраного" if favorite_mode == "remove" else "❤️ В обране"
    favorite_cb = f"favdel:{ad['id']}" if favorite_mode == "remove" else f"favadd:{ad['id']}"

    seller = get_user(ad["user_id"])

    if seller and seller["username"]:
        seller_button = InlineKeyboardButton(
            text="💬 Написати продавцю",
            url=f"https://t.me/{seller['username']}",
        )
    else:
        seller_button = InlineKeyboardButton(
            text="💬 Написати продавцю",
            callback_data=f"seller:{ad['id']}",
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [seller_button],
            [
                InlineKeyboardButton(
                    text=favorite_text,
                    callback_data=favorite_cb,
                )
            ],
        ]
    )


async def send_public_ad_to_channel(ad):
    """Публікує оголошення та додає кнопки взаємодії.
    Для одного фото кнопки прикріплюються прямо до фото.
    Для альбому Telegram Bot API не приймає reply_markup у sendMediaGroup,
    тому блок кнопок надсилається одразу наступним повідомленням.
    """
    photos = json.loads(ad["photos_json"])
    caption = ad_caption_from_row(ad)

    if len(photos) == 1:
        msg = await bot.send_photo(
            CHANNEL,
            photos[0],
            caption=caption,
        )
        post_url = channel_post_url_from_id(msg.message_id)
        await bot.edit_message_reply_markup(
            chat_id=CHANNEL,
            message_id=msg.message_id,
            reply_markup=public_ad_keyboard(ad, post_url=post_url),
        )
        return [msg.message_id], msg.message_id

    media = [
        InputMediaPhoto(media=photo, caption=caption if i == 0 else None)
        for i, photo in enumerate(photos[:10])
    ]
    messages = await bot.send_media_group(chat_id=CHANNEL, media=media)
    first_id = messages[0].message_id
    post_url = channel_post_url_from_id(first_id)
    action = await bot.send_message(
        CHANNEL,
        "👇",
        reply_markup=public_ad_keyboard(ad, post_url=post_url),
    )
    return [m.message_id for m in messages], action.message_id


async def show_ad_detail(chat_id, viewer_id, ad_id):
    ad = get_ad(ad_id)
    if not ad or ad["status"] not in ("published", "sold"):
        await bot.send_message(chat_id, "❌ Це оголошення вже недоступне.")
        return

    conn = connect_db()
    conn.execute(
        "UPDATE ads SET detail_views=COALESCE(detail_views, 0)+1 WHERE id=?",
        (ad_id,),
    )
    conn.commit()
    conn.close()

    ad = get_ad(ad_id)
    photos = json.loads(ad["photos_json"])

    conn = connect_db()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM favorites WHERE user_id=? AND ad_id=?",
        (viewer_id, ad_id),
    )
    is_fav = c.fetchone() is not None
    conn.close()

    prefix = "✅ <b>ПРОДАНО</b>\n\n" if ad["status"] == "sold" else ""
    post_url = None
    try:
        ids = json.loads(ad["channel_message_ids"] or "[]")
        if ids:
            post_url = channel_post_url_from_id(ids[0])
    except Exception:
        pass

    await send_photos_with_caption(
        chat_id,
        photos,
        prefix + ad_caption_from_row(ad),
        reply_markup=public_ad_keyboard(
            ad,
            post_url=post_url,
            favorite_mode="remove" if is_fav else "add",
        ),
    )
    await bot.send_message(
        chat_id,
        f"👁 Відкриттів у боті: <b>{ad['detail_views'] or 0}</b>\n"
        f"🆔 Оголошення: <b>#{ad_id}</b>",
        reply_markup=bot_detail_keyboard(ad, is_fav=is_fav),
    )

    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, model, price
        FROM ads
        WHERE status='published' AND category_code=? AND id<>?
        ORDER BY COALESCE(last_bumped_at, published_at, created_at) DESC
        LIMIT 3
    """, (ad["category_code"], ad_id))
    similar = c.fetchall()
    conn.close()

    if similar:
        await bot.send_message(
            chat_id,
            "🔄 <b>Схожі оголошення</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🚜 {r['model']} — {r['price']}",
                    callback_data=f"details:{r['id']}",
                )]
                for r in similar
            ]),
        )


def ad_caption_from_data(data, ad_id=None):
    hours = data.get("hours")
    hours_line = f"\n⏱ Мотогодини: <b>{hours}</b>" if hours is not None else ""
    ad_number = f"\n🆔 Оголошення: <b>#{ad_id}</b>" if ad_id else ""
    verified_badge = " ✅ <b>Перевірений продавець</b>" if data.get("verified_seller") else ""
    return (
        f"🚜 <b>{escape(str(data.get('model', 'Техніка')))}</b>{verified_badge}\n\n"
        f"📂 Категорія: {escape(str(data.get('category_name', '')))}\n"
        f"📅 Рік: <b>{escape(str(data.get('year', '')))}</b>"
        f"{hours_line}\n"
        f"💰 Ціна: <b>{escape(str(data.get('price', '')))}</b>\n"
        f"📍 Область: <b>{escape(str(data.get('region', '')))}</b>\n\n"
        f"📝 {escape(str(data.get('description', '')))}\n\n"
        f"☎️ Контакт: <b>{escape(str(data.get('phone', '')))}</b>"
        f"{ad_number}\n\n"
        f"🤖 Купити або продати техніку — @{BOT_USERNAME}"
    )


def ad_caption_from_row(ad):
    seller = get_user(ad["user_id"])
    return ad_caption_from_data({
        "model": ad["model"],
        "category_name": ad["category_name"],
        "year": ad["year"],
        "hours": ad["hours"],
        "price": ad["price"],
        "region": ad["region"],
        "description": ad["description"],
        "phone": ad["phone"],
        "verified_seller": bool(seller["verified"]) if seller else False,
    }, ad["id"])


async def send_photos_with_caption(chat_id, photos, caption, reply_markup=None):
    if not photos:
        return []

    # Одне фото — кнопки прямо під самим фото.
    if len(photos) == 1:
        msg = await bot.send_photo(
            chat_id,
            photos[0],
            caption=caption,
            reply_markup=reply_markup,
        )
        return [msg.message_id]

    # Альбом до 10 фото.
    media = [
        InputMediaPhoto(
            media=photo,
            caption=caption if i == 0 else None,
        )
        for i, photo in enumerate(photos[:10])
    ]

    messages = await bot.send_media_group(
        chat_id=chat_id,
        media=media,
    )

    # Telegram не підтримує inline-клавіатуру прямо на sendMediaGroup.
    # Тому під альбомом робимо максимально чисту кнопку без напису
    # "Дії до оголошення №...".
    if reply_markup:
        await bot.send_message(
            chat_id,
            "👇",
            reply_markup=reply_markup,
        )

    return [m.message_id for m in messages]



async def edit_channel_ad_caption(ad, prefix=""):
    """Оновлює caption першого повідомлення оголошення в каналі."""
    try:
        ids = json.loads(ad["channel_message_ids"] or "[]")
        if not ids:
            return False
        caption = ad_caption_from_row(ad)
        if prefix:
            caption = f"{prefix}\n\n{caption}"
        await bot.edit_message_caption(
            chat_id=CHANNEL,
            message_id=ids[0],
            caption=caption,
        )
        return True
    except Exception as e:
        print("Edit channel caption error:", e)
        return False


async def notify_category_subscribers(ad):
    conn = connect_db()
    c = conn.cursor()
    c.execute(
        "SELECT user_id FROM subscriptions WHERE category_code=? AND user_id<>?",
        (ad["category_code"], ad["user_id"]),
    )
    users = [r["user_id"] for r in c.fetchall()]
    conn.close()

    text = (
        "🔔 <b>Нове оголошення у вашій підписці!</b>\n\n"
        f"{escape(ad['model'])}\n"
        f"💰 {escape(ad['price'])}\n"
        f"📍 {escape(ad['region'])} область\n\n"
        "Відкрийте «🔎 Знайти техніку», щоб переглянути."
    )
    for user_id in users:
        try:
            await bot.send_message(user_id, text)
        except Exception:
            pass
        await asyncio.sleep(0.03)


async def improve_description_with_ai(data):
    if not ai_available():
        raise RuntimeError("AI не налаштований.")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    hours_text = (
        f", мотогодини {data.get('hours')}"
        if data.get("hours") is not None
        else ""
    )
    prompt = f"""
Перепиши опис оголошення про сільськогосподарську техніку українською мовою.
Не вигадуй жодних характеристик, яких користувач не вказав.
Зроби текст акуратним, довжиною 2-4 речення, без перебільшень і клікбейту.

Категорія: {data.get('category_name')}
Модель: {data.get('model')}
Рік: {data.get('year')}{hours_text}
Область: {data.get('region')}
Оригінальний опис: {data.get('description')}

Поверни тільки готовий опис без заголовків.
"""
    response = await client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    return response.output_text.strip()



def save_draft(user_id, data):
    conn = connect_db()
    conn.execute("""
        INSERT INTO ad_drafts(user_id, data_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            data_json=excluded.data_json,
            updated_at=excluded.updated_at
    """, (
        user_id,
        json.dumps(data, ensure_ascii=False),
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    conn.commit()
    conn.close()


def load_draft(user_id):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ad_drafts WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return {
            "data": json.loads(row["data_json"]),
            "updated_at": row["updated_at"],
        }
    except Exception:
        return None


def delete_draft(user_id):
    conn = connect_db()
    conn.execute("DELETE FROM ad_drafts WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


async def persist_draft_from_state(user_id, state):
    data = await state.get_data()
    if data:
        save_draft(user_id, data)


def ad_quality_score(data):
    score = 0
    tips = []

    photos = data.get("photos", [])
    if len(photos) >= 5:
        score += 25
    elif len(photos) >= 3:
        score += 20
        tips.append("📸 5+ фото дадуть кращу оцінку")
    elif len(photos) >= 1:
        score += 12
        tips.append("📸 Додайте ще кілька фото")

    if len(str(data.get("model", "")).strip()) >= 5:
        score += 15
    else:
        tips.append("🏷 Точніше вкажіть марку та модель")

    if data.get("year"):
        score += 10

    if data.get("category_code") in HOURS_CATEGORIES:
        if data.get("hours") is not None:
            score += 10
        else:
            tips.append("⏱ Якщо знаєте — додайте мотогодини")
    else:
        score += 10

    if len(str(data.get("description", "")).strip()) >= 80:
        score += 20
    elif len(str(data.get("description", "")).strip()) >= 30:
        score += 14
        tips.append("📝 Трохи детальніший опис підвищить довіру")
    else:
        score += 7
        tips.append("📝 Додайте більше інформації про стан")

    if data.get("price"):
        score += 10

    if data.get("region"):
        score += 5

    if data.get("phone"):
        score += 5

    return min(score, 100), tips[:3]


def bot_detail_keyboard(ad, is_fav=False):
    rows = [
        [InlineKeyboardButton(
            text="💬 Запропонувати свою ціну",
            callback_data=f"offer:{ad['id']}",
        )],
        [
            InlineKeyboardButton(
                text="📉 Історія ціни",
                callback_data=f"pricehistory:{ad['id']}",
            ),
            InlineKeyboardButton(
                text="💔 Прибрати" if is_fav else "❤️ В обране",
                callback_data=f"{'favdel' if is_fav else 'favadd'}:{ad['id']}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def exact_alert_category_keyboard():
    rows = []
    pairs = [
        ("tractor", "combine"),
        ("header", "plow"),
        ("ripper", "seeder"),
        ("cultivator", "disc"),
        ("sprayer", "loader"),
        ("mower", "baler"),
        ("trailer", "spreader"),
        ("harrow", "other"),
    ]
    for left, right in pairs:
        rows.append([
            InlineKeyboardButton(
                text=CATEGORIES[left],
                callback_data=f"alertcat:{left}",
            ),
            InlineKeyboardButton(
                text=CATEGORIES[right],
                callback_data=f"alertcat:{right}",
            ),
        ])
    rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="alert:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def exact_alert_region_keyboard():
    rows = []
    for i in range(0, len(REGIONS), 2):
        row = []
        for idx in range(i, min(i + 2, len(REGIONS))):
            row.append(
                InlineKeyboardButton(
                    text=REGIONS[idx],
                    callback_data=f"alertregion:{idx}",
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🌍 Вся Україна", callback_data="alertregion:all")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_exact_search_alerts(ad):
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT *
        FROM search_alerts
        WHERE active=1 AND category_code=?
    """, (ad["category_code"],))
    alerts = c.fetchall()
    conn.close()

    model_low = (ad["model"] or "").lower()
    desc_low = (ad["description"] or "").lower()

    for alert in alerts:
        if alert["user_id"] == ad["user_id"]:
            continue

        if alert["region"] != "all" and alert["region"] != ad["region"]:
            continue

        keyword = (alert["keyword"] or "").strip().lower()
        if keyword and keyword not in model_low and keyword not in desc_low:
            continue

        try:
            await bot.send_message(
                alert["user_id"],
                "🎯 <b>Знайдено техніку за вашим точним пошуком!</b>\n\n"
                f"🚜 {escape(ad['model'])}\n"
                f"💰 {escape(ad['price'])}\n"
                f"📍 {escape(ad['region'])} область\n\n"
                f"Відкрийте «🔎 Знайти техніку» у @{BOT_USERNAME}."
            )
        except Exception:
            pass
        await asyncio.sleep(0.03)


async def build_and_send_preview(message, state):
    data = await state.get_data()
    await send_photos_with_caption(
        message.chat.id,
        data.get("photos", []),
        ad_caption_from_data(data),
    )
    score, tips = ad_quality_score(data)
    tips_text = ""
    if tips:
        tips_text = "\n\n" + "\n".join(f"• {tip}" for tip in tips)

    await message.answer(
        "👀 <b>Перевірте оголошення.</b>\n\n"
        f"⭐ Якість оголошення: <b>{score}/100</b>"
        f"{tips_text}\n\n"
        "Якщо все правильно — надсилайте на модерацію.",
        reply_markup=preview_keyboard(),
    )
    await state.set_state(AdStates.preview)


@dp.message(CommandStart())
async def start(message: Message):
    register_user(message.from_user)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ad_"):
        try:
            ad_id = int(parts[1].split("_", 1)[1])
        except ValueError:
            ad_id = None
        if ad_id:
            await show_ad_detail(
                message.chat.id,
                message.from_user.id,
                ad_id,
            )
            await message.answer(
                "🏠 Головне меню",
                reply_markup=main_menu(),
            )
            return

    user = get_user(message.from_user.id)
    await message.answer(
        f"🚜 <b>VILAGROTEX</b>\n\n"
        f"Вітаємо, <b>{escape(message.from_user.first_name)}</b>!\n"
        f"Тут можна швидко продати сільгосптехніку.\n\n"
        f"📦 Доступно публікацій: <b>{user['ads_balance']}</b>\n"
        f"🎁 Запрошено друзів: <b>{user['referrals_count']}</b>\n\n"
        "Оберіть потрібний розділ 👇",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "menu:home")
async def go_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🏠 <b>Головне меню</b>",
        reply_markup=main_menu(),
    )
    await callback.answer()



@dp.message(F.text == "📢 Перейти на канал")
async def open_channel(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📢 Відкрити канал VILAGROTEX",
            url=f"https://t.me/{CHANNEL.lstrip('@')}",
        )
    ]])
    await message.answer(
        "📢 <b>Канал VILAGROTEX</b>\n\n"
        "У каналі публікуються всі схвалені оголошення.",
        reply_markup=kb,
    )


@dp.message(F.text == "📈 Кабінет продавця")
async def seller_dashboard(message: Message):
    register_user(message.from_user)
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) AS sold,
            COALESCE(SUM(detail_views),0) AS views,
            COALESCE(SUM(contact_clicks),0) AS phone_clicks,
            COALESCE(SUM(seller_clicks),0) AS seller_clicks,
            COALESCE(SUM(favorite_count),0) AS favorites
        FROM ads
        WHERE user_id=?
    """, (message.from_user.id,))
    r = c.fetchone()
    conn.close()

    u = get_user(message.from_user.id)
    await message.answer(
        "📈 <b>КАБІНЕТ ПРОДАВЦЯ</b>\n\n"
        f"📦 Баланс: <b>{u['ads_balance'] if u else 0}</b>\n"
        f"🛡 Верифікований: <b>{'✅ Так' if u and u['verified'] else '— Ні'}</b>\n\n"
        f"📝 Всього оголошень: <b>{r['total'] or 0}</b>\n"
        f"🟢 Активних: <b>{r['active'] or 0}</b>\n"
        f"✅ Продано: <b>{r['sold'] or 0}</b>\n\n"
        f"👁 Переглядів: <b>{r['views'] or 0}</b>\n"
        f"💬 Переходів до продавця: <b>{r['seller_clicks'] or 0}</b>\n"
        f"📞 Переглядів телефону: <b>{r['phone_clicks'] or 0}</b>\n"
        f"❤️ Додавань в обране: <b>{r['favorites'] or 0}</b>"
    )



@dp.message(F.text == "📝 Чернетка")
async def draft_menu(message: Message, state: FSMContext):
    draft = load_draft(message.from_user.id)
    if not draft:
        await message.answer(
            "📝 Збереженої чернетки немає.",
            reply_markup=main_menu(),
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продовжити", callback_data="draft:resume")],
        [InlineKeyboardButton(text="🗑 Видалити чернетку", callback_data="draft:delete")],
    ])
    await message.answer(
        "📝 <b>Збережена чернетка</b>\n\n"
        f"Останнє збереження: <b>{draft['updated_at']}</b>",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "draft:delete")
async def draft_delete(callback: CallbackQuery, state: FSMContext):
    delete_draft(callback.from_user.id)
    await state.clear()
    await callback.message.answer(
        "🗑 Чернетку видалено.",
        reply_markup=main_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "draft:resume")
async def draft_resume(callback: CallbackQuery, state: FSMContext):
    draft = load_draft(callback.from_user.id)
    if not draft:
        await callback.answer("Чернетку не знайдено.", show_alert=True)
        return

    data = draft["data"]
    await state.clear()
    await state.set_data(data)

    photos = data.get("photos", [])
    if not photos:
        await state.set_state(AdStates.photos)
        await callback.message.answer("📸 Продовжуємо. Надішліть 1–10 фото.")
    elif not data.get("category_code"):
        await state.set_state(AdStates.category)
        await callback.message.answer("📂 Оберіть категорію:", reply_markup=category_keyboard())
    elif not data.get("model"):
        await state.set_state(AdStates.model)
        await callback.message.answer("🏷 Вкажіть марку та модель:", reply_markup=back_keyboard())
    elif not data.get("year"):
        await state.set_state(AdStates.year)
        await callback.message.answer("📅 Вкажіть рік:", reply_markup=back_keyboard())
    elif data.get("category_code") in HOURS_CATEGORIES and "hours" not in data:
        await state.set_state(AdStates.hours)
        await callback.message.answer("⏱ Вкажіть мотогодини або «-»:", reply_markup=back_keyboard())
    elif not data.get("price"):
        await state.set_state(AdStates.price)
        await callback.message.answer("💰 Вкажіть ціну:", reply_markup=back_keyboard())
    elif not data.get("region"):
        await state.set_state(AdStates.region)
        await callback.message.answer("📍 Оберіть область:", reply_markup=regions_keyboard())
    elif not data.get("description"):
        await state.set_state(AdStates.description)
        await callback.message.answer("📝 Напишіть опис:", reply_markup=back_keyboard())
    elif not data.get("phone"):
        await state.set_state(AdStates.phone)
        await callback.message.answer("☎️ Додайте контакт:", reply_markup=contact_keyboard())
    else:
        await build_and_send_preview(callback.message, state)

    await callback.answer()


@dp.message(F.text == "👤 Мій профіль")
async def profile(message: Message):
    register_user(message.from_user)
    u = get_user(message.from_user.id)
    username = f"@{escape(u['username'])}" if u["username"] else "не встановлено"
    await message.answer(
        "👤 <b>МІЙ КАБІНЕТ</b>\n\n"
        f"👨 {escape(u['first_name'] or '')}\n"
        f"🔗 {username}\n"
        f"🆔 <code>{u['user_id']}</code>\n\n"
        f"📦 Публікацій: <b>{u['ads_balance']}</b>\n"
        f"💳 Придбано: <b>{u['total_bought']}</b>\n"
        f"✅ Опубліковано: <b>{u['total_published']}</b>\n"
        f"👥 Рефералів: <b>{u['referrals_count']}</b>\n"
        f"🎁 Реферальних бонусів: <b>{u['referral_rewards']}</b>\n\n"
        f"📅 Реєстрація: {u['registered_at']}"
    )


@dp.message(F.text == "📊 Статистика")
async def statistics(message: Message):
    register_user(message.from_user)
    u = get_user(message.from_user.id)
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE user_id=?", (message.from_user.id,))
    total_ads = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE user_id=? AND status='published'", (message.from_user.id,))
    active = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE user_id=? AND status='sold'", (message.from_user.id,))
    sold = c.fetchone()["n"]
    conn.close()
    await message.answer(
        "📊 <b>ВАША СТАТИСТИКА</b>\n\n"
        f"📦 Баланс: <b>{u['ads_balance']}</b>\n"
        f"📝 Створено оголошень: <b>{total_ads}</b>\n"
        f"🟢 Активних: <b>{active}</b>\n"
        f"✅ Продано: <b>{sold}</b>\n"
        f"👥 Рефералів: <b>{u['referrals_count']}</b>"
    )


@dp.message(F.text == "💳 Купити пакет")
async def buy_package(message: Message):
    register_user(message.from_user)
    await message.answer(
        "💳 <b>ТАРИФИ VILAGROTEX</b>\n\n"
        "📦 1 оголошення — <b>35 грн</b>\n"
        "📦 5 оголошень — <b>150 грн</b>\n"
        "🔥 10 оголошень — <b>250 грн</b>\n"
        "💎 15 оголошень — <b>300 грн</b>\n\n"
        "♾ Публікації не згорають.",
        reply_markup=packages_keyboard(),
    )


@dp.callback_query(F.data.in_(PACKAGES.keys()))
async def choose_package(callback: CallbackQuery):
    register_user(callback.from_user)
    pkg = PACKAGES[callback.data]
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO purchases(user_id, package_name, ads_count, price, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (
        callback.from_user.id,
        pkg["name"],
        pkg["count"],
        pkg["price"],
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    purchase_id = c.lastrowid
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатив", callback_data=f"paid:{purchase_id}")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"paycancel:{purchase_id}")],
    ])
    await callback.message.answer(
        f"✅ <b>ПАКЕТ ОБРАНО</b>\n\n"
        f"📦 {pkg['name']}\n"
        f"💰 До оплати: <b>{pkg['price']} грн</b>\n\n"
        f"{PAYMENT_DETAILS}",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("paycancel:"))
async def cancel_payment(callback: CallbackQuery):
    purchase_id = int(callback.data.split(":")[1])
    p = get_purchase(purchase_id)
    if not p or p["user_id"] != callback.from_user.id or p["status"] != "pending":
        await callback.answer("Цю заявку не можна скасувати.", show_alert=True)
        return
    conn = connect_db()
    conn.execute("UPDATE purchases SET status='cancelled' WHERE id=?", (purchase_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Заявку скасовано.")
    await callback.answer()


@dp.callback_query(F.data.startswith("paid:"))
async def paid(callback: CallbackQuery, state: FSMContext):
    purchase_id = int(callback.data.split(":")[1])
    p = get_purchase(purchase_id)
    if not p or p["user_id"] != callback.from_user.id or p["status"] != "pending":
        await callback.answer("Заявку не знайдено або вже оброблено.", show_alert=True)
        return
    await state.set_state(PaymentStates.waiting_receipt)
    await state.update_data(purchase_id=purchase_id)
    await callback.message.answer(
        "📸 <b>Надішліть фото або файл чека.</b>\n"
        "Після цього оплата піде адміністратору на перевірку."
    )
    await callback.answer()


@dp.message(PaymentStates.waiting_receipt, F.photo | F.document)
async def payment_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    purchase_id = data["purchase_id"]
    p = get_purchase(purchase_id)
    if not p or p["user_id"] != message.from_user.id or p["status"] != "pending":
        await message.answer("❌ Заявка вже недоступна.")
        await state.clear()
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        kind = "photo"
    else:
        file_id = message.document.file_id
        kind = "document"

    conn = connect_db()
    conn.execute("""
        UPDATE purchases
        SET receipt_file_id=?, receipt_type=?, status='review'
        WHERE id=? AND status='pending'
    """, (file_id, kind, purchase_id))
    conn.commit()
    conn.close()

    u = get_user(message.from_user.id)
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"payapprove:{purchase_id}")],
        [InlineKeyboardButton(text="❌ Відхилити", callback_data=f"payreject:{purchase_id}")],
    ])
    caption = (
        "💳 <b>НОВА ОПЛАТА</b>\n\n"
        f"🧾 #{purchase_id}\n"
        f"👤 {escape(u['first_name'] or '')}\n"
        f"🔗 @{escape(u['username']) if u['username'] else 'немає'}\n"
        f"🆔 <code>{u['user_id']}</code>\n\n"
        f"📦 {escape(p['package_name'])}\n"
        f"➕ {p['ads_count']} публікацій\n"
        f"💰 <b>{p['price']} грн</b>"
    )
    if kind == "photo":
        await bot.send_photo(ADMIN_ID, file_id, caption=caption, reply_markup=admin_kb)
    else:
        await bot.send_document(ADMIN_ID, file_id, caption=caption, reply_markup=admin_kb)

    await message.answer("✅ Чек отримано. Очікуйте підтвердження.")
    await state.clear()


@dp.message(PaymentStates.waiting_receipt)
async def payment_wrong_file(message: Message):
    await message.answer("⚠️ Надішліть саме фото або файл чека.")


@dp.callback_query(F.data.startswith("payapprove:"))
async def admin_approve_payment(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    purchase_id = int(callback.data.split(":")[1])

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM purchases WHERE id=?", (purchase_id,))
    p = c.fetchone()
    if not p or p["status"] != "review":
        conn.close()
        await callback.answer("Заявку вже оброблено.", show_alert=True)
        return

    c.execute("""
        UPDATE purchases SET status='approved', reviewed_at=?
        WHERE id=? AND status='review'
    """, (datetime.now().strftime("%d.%m.%Y %H:%M"), purchase_id))
    if c.rowcount != 1:
        conn.rollback()
        conn.close()
        await callback.answer("Заявку вже оброблено.", show_alert=True)
        return
    c.execute("""
        UPDATE users
        SET ads_balance=ads_balance+?, total_bought=total_bought+?
        WHERE user_id=?
    """, (p["ads_count"], p["ads_count"], p["user_id"]))
    conn.commit()
    conn.close()

    u = get_user(p["user_id"])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Оплату #{purchase_id} підтверджено.")
    try:
        await bot.send_message(
            p["user_id"],
            f"✅ <b>Оплату підтверджено!</b>\n\n"
            f"➕ Нараховано: <b>{p['ads_count']}</b>\n"
            f"📦 Баланс: <b>{u['ads_balance']}</b>",
            reply_markup=main_menu(),
        )
    except Exception as e:
        print("Payment notify error:", e)
    await callback.answer("Готово ✅")


@dp.callback_query(F.data.startswith("payreject:"))
async def admin_reject_payment(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    purchase_id = int(callback.data.split(":")[1])
    p = get_purchase(purchase_id)
    if not p or p["status"] != "review":
        await callback.answer("Заявку вже оброблено.", show_alert=True)
        return
    conn = connect_db()
    conn.execute("""
        UPDATE purchases SET status='rejected', reviewed_at=?
        WHERE id=? AND status='review'
    """, (datetime.now().strftime("%d.%m.%Y %H:%M"), purchase_id))
    conn.commit()
    conn.close()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Оплату #{purchase_id} відхилено.")
    try:
        await bot.send_message(
            p["user_id"],
            f"❌ Оплату не підтверджено.\nЗверніться до підтримки: {SUPPORT_USERNAME}"
        )
    except Exception:
        pass
    await callback.answer()


async def get_referral_link(user_id):
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT invite_link FROM referral_links WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return row["invite_link"]

    invite = await bot.create_chat_invite_link(chat_id=CHANNEL, name=f"ref_{user_id}")
    conn = connect_db()
    conn.execute("""
        INSERT OR REPLACE INTO referral_links(user_id, invite_link, created_at)
        VALUES (?, ?, ?)
    """, (
        user_id,
        invite.invite_link,
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    conn.commit()
    conn.close()
    return invite.invite_link


@dp.message(F.text == "🎁 Запросити друга")
async def referral_menu(message: Message):
    register_user(message.from_user)
    try:
        link = await get_referral_link(message.from_user.id)
    except Exception as e:
        print("Referral link error:", e)
        await message.answer(
            "❌ Не вдалося створити реферальне посилання.\n"
            "Перевірте права бота в каналі."
        )
        return

    u = get_user(message.from_user.id)
    rem = u["referrals_count"] % REFERRALS_FOR_BONUS
    until = REFERRALS_FOR_BONUS if rem == 0 else REFERRALS_FOR_BONUS - rem
    await message.answer(
        "🎁 <b>РЕФЕРАЛЬНА ПРОГРАМА</b>\n\n"
        f"👥 Запрошено: <b>{u['referrals_count']}</b>\n"
        f"🎯 До бонусу: <b>{until}</b>\n\n"
        f"Кожні <b>{REFERRALS_FOR_BONUS}</b> нових підписники = "
        f"<b>+{REFERRAL_BONUS_ADS} оголошення</b>\n\n"
        f"🔗 Ваше персональне посилання:\n{link}"
    )


@dp.chat_member()
async def referral_join(event: ChatMemberUpdated):
    if event.chat.username and f"@{event.chat.username}".lower() != CHANNEL.lower():
        return
    if event.old_chat_member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        return
    if event.new_chat_member.status not in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    ):
        return
    if not event.invite_link:
        return

    used_link = event.invite_link.invite_link
    referred_id = event.new_chat_member.user.id

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM referral_links WHERE invite_link=?", (used_link,))
    owner = c.fetchone()
    if not owner:
        conn.close()
        return
    referrer_id = owner["user_id"]
    if referrer_id == referred_id:
        conn.close()
        return

    c.execute("SELECT 1 FROM referrals WHERE referred_user_id=?", (referred_id,))
    if c.fetchone():
        conn.close()
        return

    c.execute("""
        INSERT INTO referrals(referrer_id, referred_user_id, invite_link, joined_at)
        VALUES (?, ?, ?, ?)
    """, (
        referrer_id,
        referred_id,
        used_link,
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    c.execute("UPDATE users SET referrals_count=referrals_count+1 WHERE user_id=?", (referrer_id,))
    c.execute("SELECT referrals_count, referral_rewards FROM users WHERE user_id=?", (referrer_id,))
    row = c.fetchone()
    referrals_count = row["referrals_count"]
    old_rewards = row["referral_rewards"]
    should_have = referrals_count // REFERRALS_FOR_BONUS
    bonus_units = max(0, should_have - old_rewards)
    bonus_ads = bonus_units * REFERRAL_BONUS_ADS

    if bonus_units:
        c.execute("""
            UPDATE users
            SET ads_balance=ads_balance+?, referral_rewards=?
            WHERE user_id=?
        """, (bonus_ads, should_have, referrer_id))

    conn.commit()
    conn.close()

    u = get_user(referrer_id)
    try:
        if bonus_ads:
            await bot.send_message(
                referrer_id,
                "🎉 <b>РЕФЕРАЛЬНИЙ БОНУС!</b>\n\n"
                f"👥 Запрошено: <b>{referrals_count}</b>\n"
                f"🎁 Нараховано: <b>+{bonus_ads}</b>\n"
                f"📦 Баланс: <b>{u['ads_balance']}</b>"
            )
        else:
            rem = referrals_count % REFERRALS_FOR_BONUS
            until = REFERRALS_FOR_BONUS - rem
            await bot.send_message(
                referrer_id,
                "👥 <b>Новий реферал!</b>\n\n"
                f"Запрошено: <b>{referrals_count}</b>\n"
                f"До бонусу: <b>{until}</b>"
            )
    except Exception as e:
        print("Referral notify error:", e)


@dp.message(F.text == "🎟 Промокод")
async def promo_start(message: Message, state: FSMContext):
    await state.set_state(PromoStates.waiting_code)
    await message.answer(
        "🎟 Введіть промокод:",
        reply_markup=promo_keyboard(),
    )


@dp.message(PromoStates.waiting_code, F.text == "⬅️ Назад")
async def promo_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏠 Головне меню",
        reply_markup=main_menu(),
    )


@dp.message(PromoStates.waiting_code, F.text)
async def promo_apply(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM promo_codes WHERE code=? AND active=1", (code,))
    promo = c.fetchone()
    if not promo:
        conn.close()
        await message.answer("❌ Промокод не знайдено або він неактивний.")
        await state.clear()
        return
    c.execute("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, message.from_user.id))
    if c.fetchone():
        conn.close()
        await message.answer("⚠️ Ви вже використовували цей промокод.")
        await state.clear()
        return
    if promo["uses"] >= promo["max_uses"]:
        conn.close()
        await message.answer("❌ Ліміт використань промокоду вичерпано.")
        await state.clear()
        return

    c.execute("INSERT INTO promo_uses(code, user_id, used_at) VALUES (?, ?, ?)", (
        code,
        message.from_user.id,
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    c.execute("UPDATE promo_codes SET uses=uses+1 WHERE code=?", (code,))
    c.execute("UPDATE users SET ads_balance=ads_balance+? WHERE user_id=?", (
        promo["ads_count"],
        message.from_user.id,
    ))
    conn.commit()
    conn.close()
    u = get_user(message.from_user.id)
    await message.answer(
        f"✅ Промокод активовано!\n"
        f"➕ Нараховано: <b>{promo['ads_count']}</b>\n"
        f"📦 Баланс: <b>{u['ads_balance']}</b>"
    )
    await state.clear()



# =========================================================
# SEARCH / FAVORITES / SUBSCRIPTIONS
# =========================================================

@dp.message(F.text == "🔎 Знайти техніку")
async def search_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SearchStates.category)
    await message.answer(
        "🔎 <b>Оберіть категорію техніки</b>",
        reply_markup=search_category_keyboard(),
    )


@dp.callback_query(F.data == "search:back_categories")
async def search_back_categories(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.category)
    await callback.message.answer(
        "🔎 Оберіть категорію:",
        reply_markup=search_category_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("searchcat:"))
async def search_choose_category(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":", 1)[1]
    if code != "all" and code not in CATEGORIES:
        await callback.answer("Категорію не знайдено.", show_alert=True)
        return
    await state.set_state(SearchStates.region)
    await state.update_data(search_category=code)
    title = "Уся техніка" if code == "all" else CATEGORIES[code]
    await callback.message.answer(
        f"✅ {title}\n\n📍 Тепер оберіть область:",
        reply_markup=search_region_keyboard(code),
    )
    await callback.answer()


async def send_search_results(chat_id, user_id, category_code, region_value):
    conn = connect_db()
    c = conn.cursor()

    clauses = ["status='published'"]
    params = []
    if category_code != "all":
        clauses.append("category_code=?")
        params.append(category_code)
    if region_value != "all":
        clauses.append("region=?")
        params.append(region_value)

    sql = (
        "SELECT * FROM ads WHERE " + " AND ".join(clauses) +
        " ORDER BY COALESCE(last_bumped_at, published_at, created_at) DESC LIMIT 12"
    )
    c.execute(sql, tuple(params))
    rows = c.fetchall()

    c.execute("SELECT ad_id FROM favorites WHERE user_id=?", (user_id,))
    favs = {r["ad_id"] for r in c.fetchall()}
    conn.close()

    if not rows:
        await bot.send_message(
            chat_id,
            "😕 За цими параметрами поки немає активних оголошень.",
            reply_markup=main_menu(),
        )
        return

    await bot.send_message(chat_id, f"🔎 Знайдено оголошень: <b>{len(rows)}</b>")
    for ad in rows:
        photos = json.loads(ad["photos_json"])
        is_fav = ad["id"] in favs
        post_url = None
        try:
            ids = json.loads(ad["channel_message_ids"] or "[]")
            if ids:
                post_url = channel_post_url_from_id(ids[0])
        except Exception:
            pass
        kb = public_ad_keyboard(
            ad,
            post_url=post_url,
            favorite_mode="remove" if is_fav else "add",
        )
        await send_photos_with_caption(
            chat_id,
            photos,
            ad_caption_from_row(ad),
            reply_markup=kb,
        )
        await asyncio.sleep(0.08)


@dp.callback_query(F.data.startswith("sreg:"))
async def search_choose_region(callback: CallbackQuery, state: FSMContext):
    _, code, region_token = callback.data.split(":", 2)
    if region_token == "all":
        region_value = "all"
        region_title = "Вся Україна"
    else:
        idx = int(region_token)
        if idx < 0 or idx >= len(REGIONS):
            await callback.answer("Область не знайдена.", show_alert=True)
            return
        region_value = REGIONS[idx]
        region_title = f"{region_value} область"

    await callback.answer("Шукаю...")
    await callback.message.answer(f"📍 {region_title}")
    await send_search_results(
        callback.message.chat.id,
        callback.from_user.id,
        code,
        region_value,
    )
    await state.clear()




@dp.callback_query(F.data.startswith("details:"))
async def details_callback(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    await callback.answer()
    await show_ad_detail(callback.message.chat.id, callback.from_user.id, ad_id)


@dp.callback_query(F.data.startswith("seller:"))
async def open_seller(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)

    if not ad:
        await callback.answer(
            "Не вдалося знайти дані продавця.",
            show_alert=True,
        )
        return

    if ad["status"] == "rejected":
        await callback.answer(
            "Оголошення вже недоступне.",
            show_alert=True,
        )
        return

    conn = connect_db()
    conn.execute(
        "UPDATE ads SET seller_clicks=COALESCE(seller_clicks,0)+1 WHERE id=?",
        (ad_id,),
    )
    conn.commit()
    conn.close()

    seller = get_user(ad["user_id"])

    # Не пишемо callback.message.answer(), бо це створює пост у каналі.
    if seller and seller["username"]:
        await callback.answer(
            f"Продавець: @{seller['username']}\\n"
            "Натисніть оновлену кнопку під постом.",
            show_alert=True,
        )
        return

    await callback.answer(
        f"☎️ Контакт продавця:\\n{ad['phone'] or 'не вказано'}",
        show_alert=True,
    )


@dp.callback_query(F.data.startswith("showphone:"))
async def show_seller_phone(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)

    if not ad:
        await callback.answer(
            "Контакт продавця не знайдено.",
            show_alert=True,
        )
        return

    if ad["status"] == "rejected":
        await callback.answer(
            "Оголошення вже недоступне.",
            show_alert=True,
        )
        return

    phone = normalize_phone(ad["phone"])
    if not phone:
        await callback.answer(
            f"Контакт продавця: {ad['phone']}",
            show_alert=True,
        )
        return

    conn = connect_db()
    conn.execute(
        "UPDATE ads SET contact_clicks=COALESCE(contact_clicks, 0)+1 WHERE id=?",
        (ad_id,),
    )
    conn.commit()
    conn.close()

    await callback.answer(
        f"📞 Телефон продавця:\n{phone}\n\n"
        "Номер також вказаний у тексті оголошення.",
        show_alert=True,
    )


@dp.callback_query(F.data.startswith("report:"))
async def report_ad(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad:
        await callback.answer("Оголошення не знайдено.", show_alert=True)
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO reports(user_id, ad_id, created_at) VALUES (?, ?, ?)",
        (
            callback.from_user.id,
            ad_id,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
        ),
    )
    added = c.rowcount == 1
    conn.commit()
    conn.close()

    if added:
        try:
            await bot.send_message(
                ADMIN_ID,
                "🚩 <b>СКАРГА НА ОГОЛОШЕННЯ</b>\n\n"
                f"🆔 Оголошення: <b>#{ad_id}</b>\n"
                f"🚜 {escape(ad['model'])}\n"
                f"👤 Хто поскаржився: <code>{callback.from_user.id}</code>\n"
                f"👤 Продавець: <code>{ad['user_id']}</code>"
            )
        except Exception:
            pass
        await callback.answer(
            "Дякуємо. Скаргу передано адміністратору.",
            show_alert=True,
        )
    else:
        await callback.answer(
            "Ви вже надсилали скаргу на це оголошення.",
            show_alert=True,
        )


@dp.callback_query(F.data.startswith("favadd:"))
async def favorite_add(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)

    if not ad:
        await callback.answer(
            "Не вдалося знайти оголошення в базі.",
            show_alert=True,
        )
        return

    if ad["status"] == "rejected":
        await callback.answer(
            "Це оголошення вже недоступне.",
            show_alert=True,
        )
        return

    # Людина може натиснути «В обране» прямо в каналі.
    # Для цього їй не обов'язково спочатку відкривати /start.
    register_user(callback.from_user)

    conn = connect_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO favorites(user_id, ad_id, created_at) VALUES (?, ?, ?)",
        (
            callback.from_user.id,
            ad_id,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
        ),
    )
    added = c.rowcount == 1
    if added:
        c.execute(
            "UPDATE ads SET favorite_count=COALESCE(favorite_count,0)+1 WHERE id=?",
            (ad_id,),
        )
    conn.commit()
    conn.close()
    try:
        await callback.message.edit_reply_markup(
            reply_markup=public_ad_keyboard(
                ad,
                favorite_mode="remove",
            )
        )
    except Exception:
        pass

    await callback.answer(
        "Додано в обране ❤️ Воно вже є в розділі «❤️ Обране»."
        if added
        else "Це оголошення вже у вашому обраному ❤️",
        show_alert=True,
    )


@dp.callback_query(F.data.startswith("favdel:"))
async def favorite_delete(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)

    conn = connect_db()
    cur = conn.execute(
        "DELETE FROM favorites WHERE user_id=? AND ad_id=?",
        (callback.from_user.id, ad_id),
    )
    if cur.rowcount:
        conn.execute(
            "UPDATE ads SET favorite_count=MAX(COALESCE(favorite_count,0)-1,0) WHERE id=?",
            (ad_id,),
        )
    conn.commit()
    conn.close()

    if ad:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=public_ad_keyboard(
                    ad,
                    favorite_mode="add",
                )
            )
        except Exception:
            pass

    await callback.answer("Прибрано з обраного")


@dp.message(F.text == "❤️ Обране")
async def favorites_list(message: Message):
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT a.*
        FROM favorites f
        JOIN ads a ON a.id=f.ad_id
        WHERE f.user_id=? AND a.status IN ('published', 'sold')
        ORDER BY f.created_at DESC
        LIMIT 12
    """, (message.from_user.id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await message.answer("❤️ В обраному поки порожньо.")
        return

    await message.answer(f"❤️ <b>Ваше обране: {len(rows)}</b>")
    for ad in rows:
        photos = json.loads(ad["photos_json"])
        post_url = None
        try:
            ids = json.loads(ad["channel_message_ids"] or "[]")
            if ids:
                post_url = channel_post_url_from_id(ids[0])
        except Exception:
            pass
        kb = public_ad_keyboard(
            ad,
            post_url=post_url,
            favorite_mode="remove",
        )
        await send_photos_with_caption(
            message.chat.id,
            photos,
            ad_caption_from_row(ad),
            reply_markup=kb,
        )


@dp.message(F.text == "🔔 Підписки")
async def subscriptions_menu(message: Message):
    await message.answer(
        "🔔 <b>Підписки на нову техніку</b>\n\n"
        "Натисніть категорію, щоб увімкнути або вимкнути просту підписку.\n\n"
        "🎯 Або створіть точний пошук за категорією, областю та ключовим словом.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Створити точний пошук", callback_data="alert:start")],
            [InlineKeyboardButton(text="📋 Мої точні пошуки", callback_data="alert:list")],
        ]),
    )
    await message.answer(
        "Прості підписки по категоріях 👇",
        reply_markup=subscriptions_keyboard(message.from_user.id),
    )



@dp.callback_query(F.data == "alert:start")
async def exact_alert_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SearchAlertStates.category)
    await callback.message.answer(
        "🎯 <b>Точний пошук</b>\\n\\nОберіть категорію:",
        reply_markup=exact_alert_category_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "alert:cancel")
async def exact_alert_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Скасовано.", reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(SearchAlertStates.category, F.data.startswith("alertcat:"))
async def exact_alert_category(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":", 1)[1]
    if code not in CATEGORIES:
        await callback.answer("Категорію не знайдено.", show_alert=True)
        return

    await state.update_data(alert_category=code)
    await state.set_state(SearchAlertStates.region)
    await callback.message.answer(
        f"✅ {CATEGORIES[code]}\\n\\n📍 Оберіть область:",
        reply_markup=exact_alert_region_keyboard(),
    )
    await callback.answer()


@dp.callback_query(SearchAlertStates.region, F.data.startswith("alertregion:"))
async def exact_alert_region(callback: CallbackQuery, state: FSMContext):
    token = callback.data.split(":", 1)[1]
    if token == "all":
        region = "all"
    else:
        idx = int(token)
        if idx < 0 or idx >= len(REGIONS):
            await callback.answer("Область не знайдена.", show_alert=True)
            return
        region = REGIONS[idx]

    await state.update_data(alert_region=region)
    await state.set_state(SearchAlertStates.keyword)
    await callback.message.answer(
        "🔤 Напишіть ключове слово для моделі, наприклад:\\n"
        "<code>John Deere</code> або <code>6900</code>\\n\\n"
        "Якщо не важливо — напишіть <code>-</code>."
    )
    await callback.answer()


@dp.message(SearchAlertStates.keyword, F.text)
async def exact_alert_keyword(message: Message, state: FSMContext):
    keyword = message.text.strip()
    if keyword == "-":
        keyword = ""

    data = await state.get_data()
    category = data.get("alert_category")
    region = data.get("alert_region")

    conn = connect_db()
    conn.execute("""
        INSERT INTO search_alerts(user_id, category_code, region, keyword, active, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (
        message.from_user.id,
        category,
        region,
        keyword,
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    conn.commit()
    conn.close()

    await state.clear()
    region_text = "Вся Україна" if region == "all" else f"{region} область"
    await message.answer(
        "✅ <b>Точний пошук створено!</b>\\n\\n"
        f"🚜 {CATEGORIES.get(category, category)}\\n"
        f"📍 {region_text}\\n"
        f"🔤 Ключове слово: <b>{escape(keyword or 'будь-яке')}</b>\\n\\n"
        "Коли з'явиться відповідне оголошення — бот повідомить вас.",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "alert:list")
async def exact_alert_list(callback: CallbackQuery):
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM search_alerts
        WHERE user_id=? AND active=1
        ORDER BY id DESC
        LIMIT 10
    """, (callback.from_user.id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await callback.answer("У вас немає точних пошуків.", show_alert=True)
        return

    for row in rows:
        region_text = "Вся Україна" if row["region"] == "all" else f"{row['region']} обл."
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Видалити", callback_data=f"alertdelete:{row['id']}")
        ]])
        await callback.message.answer(
            f"🎯 <b>Пошук #{row['id']}</b>\\n"
            f"{CATEGORIES.get(row['category_code'], row['category_code'])}\\n"
            f"📍 {region_text}\\n"
            f"🔤 {escape(row['keyword'] or 'будь-яке')}",
            reply_markup=kb,
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("alertdelete:"))
async def exact_alert_delete(callback: CallbackQuery):
    alert_id = int(callback.data.split(":")[1])
    conn = connect_db()
    cur = conn.execute(
        "DELETE FROM search_alerts WHERE id=? AND user_id=?",
        (alert_id, callback.from_user.id),
    )
    conn.commit()
    conn.close()

    if cur.rowcount:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Пошук видалено")
    else:
        await callback.answer("Пошук не знайдено.", show_alert=True)


@dp.callback_query(F.data.startswith("subtoggle:"))
async def subscription_toggle(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    if code not in CATEGORIES:
        await callback.answer("Категорію не знайдено.", show_alert=True)
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM subscriptions WHERE user_id=? AND category_code=?",
        (callback.from_user.id, code),
    )
    exists = c.fetchone()

    if exists:
        c.execute(
            "DELETE FROM subscriptions WHERE user_id=? AND category_code=?",
            (callback.from_user.id, code),
        )
        text_answer = "Сповіщення вимкнено"
    else:
        c.execute(
            "INSERT INTO subscriptions(user_id, category_code, created_at) VALUES (?, ?, ?)",
            (
                callback.from_user.id,
                code,
                datetime.now().strftime("%d.%m.%Y %H:%M"),
            ),
        )
        text_answer = "Сповіщення увімкнено"

    conn.commit()
    conn.close()
    await callback.message.edit_reply_markup(
        reply_markup=subscriptions_keyboard(callback.from_user.id)
    )
    await callback.answer(text_answer)


@dp.message(F.text == "➕ Виставити оголошення")
async def ad_start(message: Message, state: FSMContext):
    register_user(message.from_user)
    u = get_user(message.from_user.id)
    if u["ads_balance"] <= 0:
        await message.answer(
            "❌ <b>Немає доступних публікацій.</b>\n\n"
            "Придбайте пакет або запросіть друзів.",
            reply_markup=packages_keyboard(),
        )
        return

    await state.clear()
    await state.set_state(AdStates.photos)
    await state.update_data(photos=[], photo_prompt_sent=False)
    await persist_draft_from_state(message.from_user.id, state)
    await message.answer(
        "📸 <b>Додайте від 1 до 10 фото техніки.</b>\n\n"
        "Можна надіслати кілька фото або один альбом.\n"
        "Коли завершите — натисніть <b>✅ Фото готові — далі</b>."
    )


@dp.message(AdStates.photos, F.photo)
async def ad_collect_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    file_id = message.photo[-1].file_id
    if file_id not in photos and len(photos) < 10:
        photos.append(file_id)
    await state.update_data(photos=photos)
    await persist_draft_from_state(message.from_user.id, state)

    if not data.get("photo_prompt_sent"):
        await state.update_data(photo_prompt_sent=True)
        await message.answer(
            f"✅ Фото додаються. Зараз збережено: <b>{len(photos)}</b>.\n"
            "Коли закінчите — натисніть кнопку.",
            reply_markup=photos_done_keyboard(),
        )
    elif not message.media_group_id:
        await message.answer(
            f"📸 Збережено фото: <b>{len(photos)}</b>/10",
            reply_markup=photos_done_keyboard(),
        )


@dp.callback_query(AdStates.photos, F.data == "ad:photos_done")
async def ad_photos_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await callback.answer("Спочатку додайте хоча б 1 фото.", show_alert=True)
        return
    await state.set_state(AdStates.category)
    await callback.message.answer(
        f"📸 Фото: <b>{len(photos)}</b>\n\n"
        "Тепер оберіть категорію 👇",
        reply_markup=category_keyboard(),
    )
    await callback.answer()


@dp.callback_query(AdStates.category, F.data == "ad:back_photos")
async def ad_back_to_photos(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    await state.set_state(AdStates.photos)
    await callback.message.answer(
        f"📸 Повернулися до фото. Зараз збережено: <b>{len(photos)}</b>/10\n"
        "Можете додати ще фото або натиснути «Фото готові — далі».",
        reply_markup=photos_done_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "ad:cancel")
async def ad_cancel(callback: CallbackQuery, state: FSMContext):
    delete_draft(callback.from_user.id)
    await state.clear()
    await callback.message.answer("❌ Створення оголошення скасовано.", reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data == "ad:restart")
async def ad_restart(callback: CallbackQuery, state: FSMContext):
    delete_draft(callback.from_user.id)
    await state.clear()
    await state.set_state(AdStates.photos)
    await state.update_data(photos=[], photo_prompt_sent=False)
    await callback.message.answer("🔄 Починаємо заново. Надішліть 1–10 фото.")
    await callback.answer()


@dp.callback_query(AdStates.category, F.data.startswith("cat:"))
async def ad_category(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[1]
    if code not in CATEGORIES:
        await callback.answer("Категорію не знайдено.", show_alert=True)
        return
    await state.update_data(category_code=code, category_name=CATEGORIES[code])
    await persist_draft_from_state(callback.from_user.id, state)
    await state.set_state(AdStates.model)
    await callback.message.answer(
        f"✅ {CATEGORIES[code]}\n\n"
        "🏷 <b>Вкажіть марку та модель</b>\n"
        "Наприклад: <code>John Deere 6900</code>",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(AdStates.model, F.text == "⬅️ Назад")
async def ad_back_model_to_category(message: Message, state: FSMContext):
    await state.set_state(AdStates.category)
    await message.answer(
        "⬅️ Оберіть категорію:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("Категорії 👇", reply_markup=category_keyboard())


@dp.message(AdStates.model, F.text)
async def ad_model(message: Message, state: FSMContext):
    text = message.text.strip()
    if len(text) < 2:
        await message.answer("⚠️ Вкажіть марку та модель.")
        return
    await state.update_data(model=text)
    await persist_draft_from_state(message.from_user.id, state)
    await state.set_state(AdStates.year)
    await message.answer(
        "📅 Вкажіть рік випуску, наприклад <code>2012</code>.",
        reply_markup=back_keyboard(),
    )


@dp.message(AdStates.year, F.text == "⬅️ Назад")
async def ad_back_year_to_model(message: Message, state: FSMContext):
    await state.set_state(AdStates.model)
    data = await state.get_data()
    current = data.get("model", "")
    await message.answer(
        f"⬅️ Повернулися до марки та моделі.\n"
        f"Поточне значення: <b>{escape(str(current))}</b>\n\n"
        "Введіть марку та модель ще раз:",
        reply_markup=back_keyboard(),
    )


@dp.message(AdStates.year, F.text)
async def ad_year(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or len(text) != 4:
        await message.answer("⚠️ Введіть рік 4 цифрами, наприклад 2012.")
        return
    year = int(text)
    if year < 1950 or year > datetime.now().year + 1:
        await message.answer("⚠️ Перевірте рік.")
        return
    await state.update_data(year=year)
    await persist_draft_from_state(message.from_user.id, state)
    data = await state.get_data()
    if data["category_code"] in HOURS_CATEGORIES:
        await state.set_state(AdStates.hours)
        await message.answer(
            "⏱ <b>Вкажіть мотогодини</b>\n"
            "Наприклад: <code>8000</code>\n\n"
            "Якщо невідомо — напишіть <code>-</code>.",
            reply_markup=back_keyboard(),
        )
    else:
        await state.update_data(hours=None)
        await state.set_state(AdStates.price)
        await message.answer(
            "💰 Вкажіть ціну, наприклад <code>18 500 $</code>.",
            reply_markup=back_keyboard(),
        )


@dp.message(AdStates.hours, F.text == "⬅️ Назад")
async def ad_back_hours_to_year(message: Message, state: FSMContext):
    await state.set_state(AdStates.year)
    data = await state.get_data()
    current = data.get("year", "")
    await message.answer(
        f"⬅️ Повернулися до року. Поточний: <b>{current}</b>\n"
        "Введіть рік ще раз:",
        reply_markup=back_keyboard(),
    )


@dp.message(AdStates.hours, F.text)
async def ad_hours(message: Message, state: FSMContext):
    text = message.text.strip().replace(" ", "")
    if text == "-":
        hours = None
    elif text.isdigit():
        hours = int(text)
    else:
        await message.answer("⚠️ Введіть число або <code>-</code>.")
        return
    await state.update_data(hours=hours)
    await persist_draft_from_state(message.from_user.id, state)
    await state.set_state(AdStates.price)
    await message.answer(
        "💰 Вкажіть ціну, наприклад <code>18 500 $</code>.",
        reply_markup=back_keyboard(),
    )


@dp.message(AdStates.price, F.text == "⬅️ Назад")
async def ad_back_price(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("category_code") in HOURS_CATEGORIES:
        await state.set_state(AdStates.hours)
        current = data.get("hours")
        shown = "-" if current is None else current
        await message.answer(
            f"⬅️ Повернулися до мотогодин. Поточне: <b>{shown}</b>\n"
            "Введіть мотогодини ще раз:",
            reply_markup=back_keyboard(),
        )
    else:
        await state.set_state(AdStates.year)
        current = data.get("year", "")
        await message.answer(
            f"⬅️ Повернулися до року. Поточний: <b>{current}</b>\n"
            "Введіть рік ще раз:",
            reply_markup=back_keyboard(),
        )


@dp.message(AdStates.price, F.text)
async def ad_price(message: Message, state: FSMContext):
    price = message.text.strip()
    if len(price) < 2:
        await message.answer("⚠️ Вкажіть ціну.")
        return
    await state.update_data(price=price)
    await persist_draft_from_state(message.from_user.id, state)
    await state.set_state(AdStates.region)
    await message.answer("📍 Оберіть область 👇", reply_markup=regions_keyboard())


@dp.callback_query(AdStates.region, F.data == "ad:back_price")
async def ad_back_region_to_price(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdStates.price)
    data = await state.get_data()
    current = data.get("price", "")
    await callback.message.answer(
        f"⬅️ Повернулися до ціни. Поточна: <b>{escape(str(current))}</b>\n"
        "Введіть ціну ще раз:",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.callback_query(AdStates.region, F.data.startswith("region:"))
async def ad_region(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    if idx < 0 or idx >= len(REGIONS):
        await callback.answer("Область не знайдена.", show_alert=True)
        return
    await state.update_data(region=REGIONS[idx])
    await persist_draft_from_state(callback.from_user.id, state)
    await state.set_state(AdStates.description)
    await callback.message.answer(
        f"✅ {REGIONS[idx]} область\n\n"
        "📝 <b>Напишіть короткий опис стану техніки.</b>\n"
        "Наприклад: «Хороший технічний стан, готовий до роботи».",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(AdStates.description, F.text == "⬅️ Назад")
async def ad_back_description_to_region(message: Message, state: FSMContext):
    await state.set_state(AdStates.region)
    await message.answer(
        "⬅️ Повернулися до вибору області.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("📍 Оберіть область 👇", reply_markup=regions_keyboard())


@dp.message(AdStates.description, F.text)
async def ad_description(message: Message, state: FSMContext):
    text = message.text.strip()
    if len(text) < 5:
        await message.answer("⚠️ Опис занадто короткий.")
        return
    if len(text) > 800:
        await message.answer("⚠️ Опис занадто довгий. До 800 символів.")
        return

    await state.update_data(description=text, original_description=text)
    await persist_draft_from_state(message.from_user.id, state)
    if ai_available():
        await state.set_state(AdStates.description_review)
        await message.answer(
            "📝 Опис збережено.\n\n"
            "Хочете, щоб AI акуратно покращив текст без вигадування характеристик?",
            reply_markup=ai_description_keyboard(),
        )
    else:
        await state.set_state(AdStates.phone)
        await message.answer(
            "☎️ <b>Додайте контакт.</b>\n"
            "Натисніть кнопку з номером або введіть його вручну.",
            reply_markup=contact_keyboard(),
        )



@dp.callback_query(AdStates.description_review, F.data == "ad:back_desc")
async def ad_ai_back_desc(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdStates.description)
    data = await state.get_data()
    current = data.get("original_description", data.get("description", ""))
    await callback.message.answer(
        f"⬅️ Повернулися до опису.\n"
        f"Поточний: <i>{escape(str(current))}</i>\n\n"
        "Напишіть опис ще раз:",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.callback_query(AdStates.description_review, F.data == "ad:keep_desc")
async def ad_keep_description(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    original = data.get("original_description", data.get("description", ""))
    await state.update_data(description=original)
    await state.set_state(AdStates.phone)
    await callback.message.answer(
        "✅ Залишаємо ваш опис.\n\n☎️ Додайте контакт:",
        reply_markup=contact_keyboard(),
    )
    await callback.answer()


@dp.callback_query(AdStates.description_review, F.data == "ad:ai_desc")
async def ad_ai_description(callback: CallbackQuery, state: FSMContext):
    if not ai_available():
        await callback.answer("AI ще не налаштований.", show_alert=True)
        return
    await callback.answer("AI покращує опис...")
    data = await state.get_data()
    try:
        improved = await improve_description_with_ai(data)
    except Exception as e:
        await callback.message.answer(
            f"⚠️ Не вдалося покращити опис: <code>{escape(str(e))}</code>\n"
            "Можна залишити ваш текст."
        )
        return

    await state.update_data(ai_description=improved)
    await callback.message.answer(
        "✨ <b>Варіант AI:</b>\n\n"
        f"{escape(improved)}",
        reply_markup=ai_description_result_keyboard(),
    )


@dp.callback_query(AdStates.description_review, F.data == "ad:use_ai_desc")
async def ad_use_ai_description(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    improved = data.get("ai_description")
    if not improved:
        await callback.answer("Спочатку згенеруйте AI-опис.", show_alert=True)
        return
    await state.update_data(description=improved)
    await state.set_state(AdStates.phone)
    await callback.message.answer(
        "✅ AI-опис використано.\n\n☎️ Тепер додайте контакт:",
        reply_markup=contact_keyboard(),
    )
    await callback.answer()


@dp.message(AdStates.phone, F.text == "⬅️ Назад")
async def ad_back_phone_to_description(message: Message, state: FSMContext):
    data = await state.get_data()
    if ai_available():
        await state.set_state(AdStates.description_review)
        await message.answer(
            "⬅️ Повернулися до вибору опису.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            f"📝 Поточний опис:\n<i>{escape(str(data.get('description', '')))}</i>",
            reply_markup=ai_description_keyboard(),
        )
    else:
        await state.set_state(AdStates.description)
        current = data.get("description", "")
        await message.answer(
            f"⬅️ Повернулися до опису.\n"
            f"Поточний опис: <i>{escape(str(current))}</i>\n\n"
            "Напишіть опис ще раз:",
            reply_markup=back_keyboard(),
        )


@dp.message(AdStates.phone, F.contact)
async def ad_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await persist_draft_from_state(message.from_user.id, state)
    await message.answer("✅ Контакт додано.", reply_markup=ReplyKeyboardRemove())
    await build_and_send_preview(message, state)


@dp.message(AdStates.phone, F.text)
async def ad_phone_text(message: Message, state: FSMContext):
    if message.text == "✍️ Ввести номер вручну":
        await message.answer("Напишіть номер телефону або @username:", reply_markup=ReplyKeyboardRemove())
        return
    text = message.text.strip()
    if len(text) < 5:
        await message.answer("⚠️ Вкажіть коректний номер або @username.")
        return
    await state.update_data(phone=text)
    await persist_draft_from_state(message.from_user.id, state)
    await message.answer("✅ Контакт додано.", reply_markup=ReplyKeyboardRemove())
    await build_and_send_preview(message, state)


@dp.callback_query(AdStates.preview, F.data == "ad:back_phone")
async def ad_back_preview_to_phone(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdStates.phone)
    await callback.message.answer(
        "⬅️ Повернулися до контакту. Виберіть або введіть контакт ще раз:",
        reply_markup=contact_keyboard(),
    )
    await callback.answer()


@dp.callback_query(AdStates.preview, F.data == "ad:submit")
async def ad_submit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    u = get_user(callback.from_user.id)
    if not u or u["ads_balance"] <= 0:
        await callback.answer("У вас більше немає доступних публікацій.", show_alert=True)
        await state.clear()
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ads (
            user_id, photos_json, category_code, category_name, model, year,
            hours, price, region, description, phone, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'moderation', ?)
    """, (
        callback.from_user.id,
        json.dumps(data["photos"]),
        data["category_code"],
        data["category_name"],
        data["model"],
        data["year"],
        data.get("hours"),
        data["price"],
        data["region"],
        data["description"],
        data["phone"],
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    ad_id = c.lastrowid
    conn.commit()
    conn.close()
    delete_draft(callback.from_user.id)

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"adapprove:{ad_id}"),
            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"adreject:{ad_id}"),
        ]
    ])

    caption = ad_caption_from_data(data, ad_id)
    await send_photos_with_caption(ADMIN_ID, data["photos"], caption)
    await bot.send_message(
        ADMIN_ID,
        f"🛠 <b>МОДЕРАЦІЯ ОГОЛОШЕННЯ #{ad_id}</b>\n"
        f"👤 User ID: <code>{callback.from_user.id}</code>\n"
        f"📦 Баланс користувача зараз: <b>{u['ads_balance']}</b>",
        reply_markup=admin_kb,
    )

    await callback.message.answer(
        f"✅ Оголошення <b>#{ad_id}</b> відправлено на модерацію.\n"
        "Публікація спишеться тільки після схвалення.\n\n"
        "🏠 Ви повернулися в головне меню.",
        reply_markup=main_menu(),
    )
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data.startswith("adapprove:"))
async def ad_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return

    ad_id = int(callback.data.split(":")[1])
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
    ad = c.fetchone()
    if not ad or ad["status"] != "moderation":
        conn.close()
        await callback.answer("Оголошення вже оброблено.", show_alert=True)
        return

    c.execute("SELECT ads_balance FROM users WHERE user_id=?", (ad["user_id"],))
    u = c.fetchone()
    if not u or u["ads_balance"] <= 0:
        conn.close()
        await callback.answer("У користувача 0 публікацій.", show_alert=True)
        return

    try:
        message_ids, action_message_id = await send_public_ad_to_channel(ad)
    except Exception as e:
        conn.close()
        await callback.answer("Помилка публікації в канал.", show_alert=True)
        print("Channel publish error:", e)
        return

    c.execute("""
        UPDATE users
        SET ads_balance=ads_balance-1, total_published=total_published+1
        WHERE user_id=? AND ads_balance>0
    """, (ad["user_id"],))
    if c.rowcount != 1:
        conn.rollback()
        conn.close()
        await callback.answer("Не вдалося списати публікацію.", show_alert=True)
        return

    c.execute("""
        UPDATE ads
        SET status='published', reviewed_at=?, published_at=?,
            channel_message_ids=?, action_message_id=?
        WHERE id=? AND status='moderation'
    """, (
        datetime.now().strftime("%d.%m.%Y %H:%M"),
        datetime.now().strftime("%d.%m.%Y %H:%M"),
        json.dumps(message_ids),
        action_message_id,
        ad_id,
    ))
    conn.commit()
    conn.close()

    u2 = get_user(ad["user_id"])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Оголошення #{ad_id} опубліковано.")
    try:
        await bot.send_message(
            ad["user_id"],
            f"🎉 <b>Оголошення #{ad_id} опубліковано!</b>\n\n"
            f"📦 Залишилось публікацій: <b>{u2['ads_balance']}</b>\n\n"
            "🏠 Можете створити наступне оголошення або скористатися меню.",
            reply_markup=main_menu(),
        )
    except Exception:
        pass

    published_ad = get_ad(ad_id)
    if published_ad:
        await notify_category_subscribers(published_ad)
        await notify_exact_search_alerts(published_ad)

    await callback.answer("Опубліковано ✅")


@dp.callback_query(F.data.startswith("adreject:"))
async def ad_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad or ad["status"] != "moderation":
        await callback.answer("Оголошення вже оброблено.", show_alert=True)
        return

    conn = connect_db()
    conn.execute("""
        UPDATE ads SET status='rejected', reviewed_at=?
        WHERE id=? AND status='moderation'
    """, (datetime.now().strftime("%d.%m.%Y %H:%M"), ad_id))
    conn.commit()
    conn.close()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Оголошення #{ad_id} відхилено.")
    try:
        await bot.send_message(
            ad["user_id"],
            f"❌ Оголошення #{ad_id} не пройшло модерацію.\n"
            f"Публікація не списана. Підтримка: {SUPPORT_USERNAME}"
        )
    except Exception:
        pass
    await callback.answer()


@dp.message(F.text == "📦 Мої оголошення")
async def my_ads(message: Message):
    register_user(message.from_user)
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, model, price, status, created_at
        FROM ads
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (message.from_user.id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await message.answer("📦 У вас поки немає оголошень.")
        return

    status_names = {
        "moderation": "🟡 На модерації",
        "published": "🟢 Активне",
        "rejected": "🔴 Відхилене",
        "sold": "✅ Продано",
    }
    await message.answer("📦 <b>Останні оголошення:</b>")
    for row in rows:
        kb = None
        if row["status"] == "published":
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔥 Підняти", callback_data=f"adbump:{row['id']}"),
                    InlineKeyboardButton(text="💰 Змінити ціну", callback_data=f"adprice:{row['id']}"),
                ],
                [InlineKeyboardButton(text="✅ Позначити проданим", callback_data=f"adsold:{row['id']}")],
            ])
        await message.answer(
            f"<b>#{row['id']} — {escape(row['model'])}</b>\n"
            f"💰 {escape(row['price'])}\n"
            f"{status_names.get(row['status'], row['status'])}\n"
            f"📅 {row['created_at']}",
            reply_markup=kb,
        )




@dp.callback_query(F.data.startswith("offer:"))
async def offer_start(callback: CallbackQuery, state: FSMContext):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)

    if not ad or ad["status"] != "published":
        await callback.answer("Оголошення недоступне.", show_alert=True)
        return

    if ad["user_id"] == callback.from_user.id:
        await callback.answer("Не можна робити пропозицію самому собі.", show_alert=True)
        return

    await state.set_state(OfferStates.waiting_amount)
    await state.update_data(offer_ad_id=ad_id)

    await callback.message.answer(
        f"💬 <b>Запропонувати ціну</b>\\n\\n"
        f"🚜 {escape(ad['model'])}\\n"
        f"Поточна ціна: <b>{escape(ad['price'])}</b>\\n\\n"
        "Напишіть вашу пропозицію, наприклад:\\n"
        "<code>42 000 $</code>\\n\\n"
        "Або натисніть «⬅️ Назад».",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(OfferStates.waiting_amount, F.text == "⬅️ Назад")
async def offer_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Скасовано.", reply_markup=main_menu())


@dp.message(OfferStates.waiting_amount, F.text)
async def offer_send(message: Message, state: FSMContext):
    amount = message.text.strip()
    if len(amount) < 2 or len(amount) > 80:
        await message.answer("⚠️ Вкажіть коректну суму.")
        return

    data = await state.get_data()
    ad_id = data.get("offer_ad_id")
    ad = get_ad(ad_id)

    if not ad or ad["status"] != "published":
        await state.clear()
        await message.answer("Оголошення вже недоступне.", reply_markup=main_menu())
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO offers(ad_id, buyer_id, seller_id, amount, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (
        ad_id,
        message.from_user.id,
        ad["user_id"],
        amount,
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    offer_id = c.lastrowid
    conn.commit()
    conn.close()

    buyer = get_user(message.from_user.id)
    buyer_name = (
        f"@{buyer['username']}"
        if buyer and buyer["username"]
        else f"ID {message.from_user.id}"
    )

    seller_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Прийняти", callback_data=f"offeraccept:{offer_id}"),
            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"offerreject:{offer_id}"),
        ],
        [
            InlineKeyboardButton(text="💬 Написати покупцю", callback_data=f"offerbuyer:{offer_id}")
        ],
    ])

    try:
        await bot.send_message(
            ad["user_id"],
            "💰 <b>НОВА ПРОПОЗИЦІЯ ЦІНИ</b>\\n\\n"
            f"🚜 {escape(ad['model'])}\\n"
            f"Ваша ціна: <b>{escape(ad['price'])}</b>\\n"
            f"Пропозиція: <b>{escape(amount)}</b>\\n"
            f"👤 Покупець: {escape(buyer_name)}",
            reply_markup=seller_kb,
        )
    except Exception:
        pass

    await state.clear()
    await message.answer(
        "✅ Пропозицію відправлено продавцю.",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data.startswith("offeraccept:"))
async def offer_accept(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM offers WHERE id=?", (offer_id,))
    offer = c.fetchone()

    if not offer or offer["seller_id"] != callback.from_user.id or offer["status"] != "pending":
        conn.close()
        await callback.answer("Пропозиція вже недоступна.", show_alert=True)
        return

    c.execute("""
        UPDATE offers SET status='accepted', reviewed_at=? WHERE id=?
    """, (datetime.now().strftime("%d.%m.%Y %H:%M"), offer_id))
    conn.commit()
    conn.close()

    ad = get_ad(offer["ad_id"])
    try:
        await bot.send_message(
            offer["buyer_id"],
            "✅ <b>Продавець прийняв вашу пропозицію!</b>\\n\\n"
            f"🚜 {escape(ad['model']) if ad else 'Оголошення'}\\n"
            f"💰 Ваша пропозиція: <b>{escape(offer['amount'])}</b>"
        )
    except Exception:
        pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ Пропозицію прийнято.")
    await callback.answer()


@dp.callback_query(F.data.startswith("offerreject:"))
async def offer_reject(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM offers WHERE id=?", (offer_id,))
    offer = c.fetchone()

    if not offer or offer["seller_id"] != callback.from_user.id or offer["status"] != "pending":
        conn.close()
        await callback.answer("Пропозиція вже недоступна.", show_alert=True)
        return

    c.execute("""
        UPDATE offers SET status='rejected', reviewed_at=? WHERE id=?
    """, (datetime.now().strftime("%d.%m.%Y %H:%M"), offer_id))
    conn.commit()
    conn.close()

    try:
        await bot.send_message(
            offer["buyer_id"],
            f"❌ Продавець відхилив вашу пропозицію <b>{escape(offer['amount'])}</b>."
        )
    except Exception:
        pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Пропозицію відхилено.")
    await callback.answer()


@dp.callback_query(F.data.startswith("offerbuyer:"))
async def offer_write_buyer(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM offers WHERE id=?", (offer_id,))
    offer = c.fetchone()
    conn.close()

    if not offer or offer["seller_id"] != callback.from_user.id:
        await callback.answer("Немає доступу.", show_alert=True)
        return

    buyer = get_user(offer["buyer_id"])
    if buyer and buyer["username"]:
        await callback.message.answer(
            f"💬 Покупець: <b>@{escape(buyer['username'])}</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="Відкрити чат",
                    url=f"https://t.me/{buyer['username']}",
                )
            ]]),
        )
    else:
        await callback.answer(
            f"ID покупця: {offer['buyer_id']}",
            show_alert=True,
        )


@dp.callback_query(F.data.startswith("pricehistory:"))
async def price_history_show(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad:
        await callback.answer("Оголошення не знайдено.", show_alert=True)
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT old_price, new_price, changed_at
        FROM price_history
        WHERE ad_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (ad_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await callback.answer("Ціна ще не змінювалась.", show_alert=True)
        return

    lines = ["📉 <b>ІСТОРІЯ ЦІНИ</b>\\n"]
    for row in reversed(rows):
        lines.append(
            f"{row['changed_at']}: "
            f"<s>{escape(row['old_price'] or '—')}</s> → "
            f"<b>{escape(row['new_price'])}</b>"
        )

    await callback.message.answer("\\n".join(lines))
    await callback.answer()


@dp.callback_query(F.data.startswith("adbump:"))
async def bump_confirm(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad or ad["user_id"] != callback.from_user.id or ad["status"] != "published":
        await callback.answer("Оголошення недоступне.", show_alert=True)
        return

    u = get_user(callback.from_user.id)
    if not u or u["ads_balance"] < PROMOTION_COST_ADS:
        await callback.answer(
            f"Для підняття потрібно {PROMOTION_COST_ADS} публікація.",
            show_alert=True,
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🔥 Підняти за {PROMOTION_COST_ADS} публікацію",
                callback_data=f"adbumpok:{ad_id}",
            )
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="noop")],
    ])
    await callback.message.answer(
        "🔥 <b>Підняття оголошення</b>\n\n"
        "Бот повторно опублікує оголошення у каналі вище нових постів.\n"
        f"Буде списано: <b>{PROMOTION_COST_ADS}</b> публікацію.",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer("Скасовано")


@dp.callback_query(F.data.startswith("adbumpok:"))
async def bump_execute(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
    ad = c.fetchone()
    if not ad or ad["user_id"] != callback.from_user.id or ad["status"] != "published":
        conn.close()
        await callback.answer("Оголошення недоступне.", show_alert=True)
        return

    c.execute("SELECT ads_balance FROM users WHERE user_id=?", (callback.from_user.id,))
    u = c.fetchone()
    if not u or u["ads_balance"] < PROMOTION_COST_ADS:
        conn.close()
        await callback.answer("Недостатньо публікацій.", show_alert=True)
        return

    try:
        photos = json.loads(ad["photos_json"])
        caption = "🔥 <b>ПІДНЯТЕ ОГОЛОШЕННЯ</b>\n\n" + ad_caption_from_row(ad)
        if len(photos) == 1:
            bumped = await bot.send_photo(CHANNEL, photos[0], caption=caption)
            post_url = channel_post_url_from_id(bumped.message_id)
            await bot.edit_message_reply_markup(
                chat_id=CHANNEL,
                message_id=bumped.message_id,
                reply_markup=public_ad_keyboard(ad, post_url=post_url),
            )
        else:
            media = [
                InputMediaPhoto(media=photo, caption=caption if i == 0 else None)
                for i, photo in enumerate(photos[:10])
            ]
            bumped_msgs = await bot.send_media_group(CHANNEL, media=media)
            post_url = channel_post_url_from_id(bumped_msgs[0].message_id)
            await bot.send_message(
                CHANNEL,
                "👇",
                reply_markup=public_ad_keyboard(ad, post_url=post_url),
            )
    except Exception as e:
        conn.close()
        print("Bump publish error:", e)
        await callback.answer("Не вдалося підняти оголошення.", show_alert=True)
        return

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    c.execute(
        "UPDATE users SET ads_balance=ads_balance-? WHERE user_id=? AND ads_balance>=?",
        (PROMOTION_COST_ADS, callback.from_user.id, PROMOTION_COST_ADS),
    )
    if c.rowcount != 1:
        conn.rollback()
        conn.close()
        await callback.answer("Не вдалося списати баланс.", show_alert=True)
        return
    c.execute("UPDATE ads SET last_bumped_at=? WHERE id=?", (now, ad_id))
    c.execute("""
        INSERT INTO promotions(user_id, ad_id, cost_ads, created_at)
        VALUES (?, ?, ?, ?)
    """, (callback.from_user.id, ad_id, PROMOTION_COST_ADS, now))
    conn.commit()
    conn.close()

    u2 = get_user(callback.from_user.id)
    await callback.message.answer(
        f"🔥 Оголошення #{ad_id} піднято!\n"
        f"📦 Баланс: <b>{u2['ads_balance']}</b>"
    )
    await callback.answer("Піднято 🔥")


@dp.callback_query(F.data.startswith("adprice:"))
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad or ad["user_id"] != callback.from_user.id or ad["status"] != "published":
        await callback.answer("Оголошення недоступне.", show_alert=True)
        return
    await state.set_state(EditPriceStates.waiting_price)
    await state.update_data(edit_ad_id=ad_id)
    await callback.message.answer(
        f"💰 Поточна ціна: <b>{escape(ad['price'])}</b>\n"
        "Введіть нову ціну або натисніть «⬅️ Назад».",
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@dp.message(EditPriceStates.waiting_price, F.text == "⬅️ Назад")
async def edit_price_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Скасовано.", reply_markup=main_menu())


@dp.message(EditPriceStates.waiting_price, F.text)
async def edit_price_save(message: Message, state: FSMContext):
    new_price = message.text.strip()
    if len(new_price) < 2 or len(new_price) > 80:
        await message.answer("⚠️ Вкажіть коректну ціну.")
        return

    data = await state.get_data()
    ad_id = data.get("edit_ad_id")
    ad = get_ad(ad_id)
    if not ad or ad["user_id"] != message.from_user.id or ad["status"] != "published":
        await state.clear()
        await message.answer("Оголошення вже недоступне.", reply_markup=main_menu())
        return

    old_price = ad["price"]
    conn = connect_db()
    conn.execute("UPDATE ads SET price=? WHERE id=?", (new_price, ad_id))
    conn.execute("""
        INSERT INTO price_history(ad_id, old_price, new_price, changed_at)
        VALUES (?, ?, ?, ?)
    """, (
        ad_id,
        old_price,
        new_price,
        datetime.now().strftime("%d.%m.%Y %H:%M"),
    ))
    conn.commit()
    conn.close()

    updated = get_ad(ad_id)
    await edit_channel_ad_caption(updated)

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM favorites WHERE ad_id=?", (ad_id,))
    watchers = [r["user_id"] for r in c.fetchall()]
    conn.close()

    for watcher_id in watchers:
        if watcher_id == message.from_user.id:
            continue
        try:
            await bot.send_message(
                watcher_id,
                "📉 <b>Змінилась ціна в обраному</b>\n\n"
                f"🚜 {escape(updated['model'])}\n"
                f"Було: <s>{escape(old_price)}</s>\n"
                f"Стало: <b>{escape(new_price)}</b>\n\n"
                f"Перегляньте «❤️ Обране» у @{BOT_USERNAME}."
            )
        except Exception:
            pass
        await asyncio.sleep(0.03)

    await state.clear()
    await message.answer(
        f"✅ Ціну змінено:\n"
        f"<s>{escape(old_price)}</s> → <b>{escape(new_price)}</b>",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data.startswith("adsold:"))
async def mark_sold(callback: CallbackQuery):
    ad_id = int(callback.data.split(":")[1])
    ad = get_ad(ad_id)
    if not ad or ad["user_id"] != callback.from_user.id or ad["status"] != "published":
        await callback.answer("Оголошення недоступне.", show_alert=True)
        return
    conn = connect_db()
    conn.execute("UPDATE ads SET status='sold' WHERE id=?", (ad_id,))
    conn.commit()
    conn.close()

    sold_ad = get_ad(ad_id)
    if sold_ad:
        await edit_channel_ad_caption(sold_ad, prefix="✅ <b>ПРОДАНО</b>")
        try:
            if sold_ad["action_message_id"]:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL,
                    message_id=sold_ad["action_message_id"],
                    reply_markup=None,
                )
        except Exception as e:
            print("Remove sold keyboard error:", e)

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Оголошення #{ad_id} позначено як продане.")
    await callback.answer()


@dp.message(F.text == "☎️ Підтримка")
async def support(message: Message):
    await message.answer(
        "☎️ <b>ПІДТРИМКА VILAGROTEX</b>\n\n"
        f"Питання щодо оплати, оголошень або рефералів:\n👉 {SUPPORT_USERNAME}"
    )


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) AS n FROM users")
    users = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE status='moderation'")
    moderation = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE status='published'")
    active_ads = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM purchases WHERE status='review'")
    payments = c.fetchone()["n"]
    c.execute("SELECT COALESCE(SUM(price),0) AS s FROM purchases WHERE status='approved'")
    revenue = c.fetchone()["s"]
    c.execute("SELECT COUNT(*) AS n FROM referrals")
    referrals = c.fetchone()["n"]
    conn.close()

    try:
        members = await bot.get_chat_member_count(CHANNEL)
    except Exception:
        members = "?"

    await message.answer(
        "🛠 <b>VILAGROTEX ADMIN</b>\n\n"
        f"👥 Користувачів бота: <b>{users}</b>\n"
        f"📢 Підписників каналу: <b>{members}</b>\n"
        f"👥 Рефералів: <b>{referrals}</b>\n"
        f"⏳ Оголошень на модерації: <b>{moderation}</b>\n"
        f"🟢 Активних оголошень: <b>{active_ads}</b>\n"
        f"💳 Оплат на перевірці: <b>{payments}</b>\n"
        f"💰 Підтверджено оплат: <b>{revenue} грн</b>\n\n"
        "<b>Команди:</b>\n"
        "<code>/addads ID КІЛЬКІСТЬ</code>\n"
        "<code>/makepromo CODE ADS USES</code>\n"
        "<code>/broadcast</code>\n"
        "<code>/aipost</code>\n"
        "<code>/backup</code>\n"
        "<code>/fixbuttons</code>",
        reply_markup=admin_keyboard(),
    )



async def send_backup_to_admin():
    if not Path(DB_NAME).exists():
        raise FileNotFoundError(DB_NAME)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    file = FSInputFile(DB_NAME, filename=f"vilagro_backup_{stamp}.db")
    await bot.send_document(
        ADMIN_ID,
        file,
        caption=f"💾 Backup VILAGROTEX\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    )


@dp.callback_query(F.data == "admin:stats")
async def admin_stats_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) AS n FROM users")
    users = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE status='moderation'")
    moderation = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE status='published'")
    active_ads = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM ads WHERE status='sold'")
    sold_ads = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM purchases WHERE status='review'")
    payments = c.fetchone()["n"]
    c.execute("SELECT COALESCE(SUM(price),0) AS s FROM purchases WHERE status='approved'")
    revenue = c.fetchone()["s"]
    c.execute("SELECT COUNT(*) AS n FROM referrals")
    referrals = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM promotions")
    bumps = c.fetchone()["n"]
    c.execute("SELECT COUNT(*) AS n FROM reports")
    reports = c.fetchone()["n"]
    c.execute("SELECT COALESCE(SUM(detail_views),0) AS n FROM ads")
    detail_views = c.fetchone()["n"]
    c.execute("SELECT COALESCE(SUM(contact_clicks),0) AS n FROM ads")
    contact_clicks = c.fetchone()["n"]
    conn.close()

    try:
        members = await bot.get_chat_member_count(CHANNEL)
    except Exception:
        members = "?"

    await callback.message.answer(
        "📊 <b>СТАТИСТИКА VILAGROTEX</b>\n\n"
        f"👥 Користувачів: <b>{users}</b>\n"
        f"📢 Підписників каналу: <b>{members}</b>\n"
        f"👥 Рефералів: <b>{referrals}</b>\n\n"
        f"⏳ На модерації: <b>{moderation}</b>\n"
        f"🟢 Активних: <b>{active_ads}</b>\n"
        f"✅ Продано: <b>{sold_ads}</b>\n"
        f"🔥 Піднять: <b>{bumps}</b>\n"
        f"👁 Відкриттів деталей: <b>{detail_views}</b>\n"
        f"📞 Натискань телефону: <b>{contact_clicks}</b>\n"
        f"🚩 Скарг: <b>{reports}</b>\n\n"
        f"💳 Оплат на перевірці: <b>{payments}</b>\n"
        f"💰 Підтверджено оплат: <b>{revenue} грн</b>",
        reply_markup=admin_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "admin:moderation")
async def admin_moderation_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, model, price, region, user_id
        FROM ads
        WHERE status='moderation'
        ORDER BY id ASC
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    if not rows:
        await callback.message.answer("✅ Оголошень на модерації немає.")
    else:
        await callback.message.answer(f"⏳ На модерації: <b>{len(rows)}</b>")
        for row in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"adapprove:{row['id']}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"adreject:{row['id']}"),
            ]])
            await callback.message.answer(
                f"#{row['id']} — <b>{escape(row['model'])}</b>\n"
                f"💰 {escape(row['price'])}\n"
                f"📍 {escape(row['region'])}\n"
                f"👤 <code>{row['user_id']}</code>",
                reply_markup=kb,
            )
    await callback.answer()


@dp.callback_query(F.data == "admin:payments")
async def admin_payments_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM purchases
        WHERE status='review'
        ORDER BY id ASC
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    if not rows:
        await callback.message.answer("✅ Оплат на перевірці немає.")
    else:
        await callback.message.answer(f"💳 На перевірці: <b>{len(rows)}</b>")
        for p in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"payapprove:{p['id']}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"payreject:{p['id']}"),
            ]])
            await callback.message.answer(
                f"🧾 #{p['id']}\n"
                f"👤 <code>{p['user_id']}</code>\n"
                f"📦 {escape(p['package_name'])}\n"
                f"💰 <b>{p['price']} грн</b>",
                reply_markup=kb,
            )
    await callback.answer()


@dp.callback_query(F.data == "admin:aipost")
async def admin_ai_post_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    if not ai_available():
        await callback.answer("AI не налаштований.", show_alert=True)
        return
    await callback.answer("Генерую...")
    try:
        await ai_post_to_admin()
    except Exception as e:
        await callback.message.answer(f"❌ AI: <code>{escape(str(e))}</code>")


@dp.callback_query(F.data == "admin:backup")
async def admin_backup_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer("Готую backup...")
    try:
        await send_backup_to_admin()
    except Exception as e:
        await callback.message.answer(f"❌ Backup: <code>{escape(str(e))}</code>")


@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(BroadcastStates.waiting_message)
    await callback.message.answer(
        "📢 Надішліть текст розсилки.\n/cancel — скасувати."
    )
    await callback.answer()


@dp.message(Command("backup"))
async def backup_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        await send_backup_to_admin()
    except Exception as e:
        await message.answer(f"❌ Backup: <code>{escape(str(e))}</code>")



@dp.message(Command("verify"))
async def verify_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: <code>/verify USER_ID</code>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("USER_ID має бути числом.")
        return
    if not get_user(user_id):
        await message.answer("Користувача не знайдено.")
        return
    conn = connect_db()
    conn.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Користувача <code>{user_id}</code> верифіковано.")


@dp.message(Command("unverify"))
async def unverify_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: <code>/unverify USER_ID</code>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        return
    conn = connect_db()
    conn.execute("UPDATE users SET verified=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    await message.answer(f"Верифікацію <code>{user_id}</code> знято.")


@dp.message(Command("exportcsv"))
async def export_ads_csv(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT id,user_id,category_name,model,year,hours,price,region,status,
               detail_views,seller_clicks,contact_clicks,favorite_count,
               created_at,published_at
        FROM ads
        ORDER BY id DESC
    """)
    rows = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id","user_id","category","model","year","hours","price","region",
        "status","views","seller_clicks","phone_clicks","favorites",
        "created_at","published_at"
    ])
    for r in rows:
        writer.writerow(list(r))

    export_path = Path("/mnt/data/vilagro_ads_export.csv")
    export_path.write_text(output.getvalue(), encoding="utf-8-sig")
    await message.answer_document(
        FSInputFile(str(export_path)),
        caption="📊 Експорт оголошень VILAGROTEX",
    )



@dp.message(Command("fixbuttons"))
async def fix_channel_buttons(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT *
        FROM ads
        WHERE channel_message_ids IS NOT NULL
           OR action_message_id IS NOT NULL
        ORDER BY id DESC
    """)
    ads = c.fetchall()
    conn.close()

    fixed = 0
    failed = 0

    for ad in ads:
        if ad["status"] == "rejected":
            continue

        try:
            # Для альбомів кнопки знаходяться в окремому action_message_id.
            if ad["action_message_id"]:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL,
                    message_id=ad["action_message_id"],
                    reply_markup=public_ad_keyboard(ad),
                )
                fixed += 1
                continue

            # Для одного фото кнопки прикріплені до самого поста.
            ids = json.loads(ad["channel_message_ids"] or "[]")
            if ids:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL,
                    message_id=ids[0],
                    reply_markup=public_ad_keyboard(ad),
                )
                fixed += 1

        except Exception as e:
            failed += 1
            print(f"Fix buttons #{ad['id']} error:", e)

        await asyncio.sleep(0.05)

    await message.answer(
        "🔧 <b>Кнопки оновлено</b>\n\n"
        f"✅ Успішно: <b>{fixed}</b>\n"
        f"❌ Не вдалося: <b>{failed}</b>"
    )


@dp.message(Command("addads"))
async def add_ads_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: <code>/addads ID КІЛЬКІСТЬ</code>")
        return
    try:
        user_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("ID і кількість мають бути числами.")
        return
    if amount <= 0 or not get_user(user_id):
        await message.answer("❌ Неправильні дані або користувача немає.")
        return
    conn = connect_db()
    conn.execute("UPDATE users SET ads_balance=ads_balance+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    u = get_user(user_id)
    await message.answer(f"✅ +{amount}. Баланс користувача: {u['ads_balance']}")
    try:
        await bot.send_message(user_id, f"🎁 Вам нараховано <b>+{amount}</b> публікацій.")
    except Exception:
        pass


@dp.message(Command("makepromo"))
async def make_promo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Формат: <code>/makepromo CODE ADS USES</code>")
        return
    code = parts[1].upper()
    try:
        ads_count = int(parts[2])
        max_uses = int(parts[3])
    except ValueError:
        await message.answer("ADS і USES мають бути числами.")
        return
    conn = connect_db()
    conn.execute("""
        INSERT OR REPLACE INTO promo_codes(code, ads_count, max_uses, uses, active, created_at)
        VALUES (?, ?, ?, 0, 1, ?)
    """, (code, ads_count, max_uses, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()
    await message.answer(
        f"✅ Промокод <code>{code}</code>\n"
        f"➕ {ads_count} публікацій\n"
        f"👥 Ліміт: {max_uses}"
    )


@dp.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(BroadcastStates.waiting_message)
    await message.answer("📢 Надішліть текст розсилки. /cancel — скасувати.")


@dp.message(BroadcastStates.waiting_message, Command("cancel"))
async def broadcast_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Скасовано.")


@dp.message(BroadcastStates.waiting_message, F.text)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        return
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = [r["user_id"] for r in c.fetchall()]
    conn.close()

    ok = 0
    fail = 0
    await message.answer(f"📢 Починаю розсилку для {len(users)} користувачів...")
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.04)
    await state.clear()
    await message.answer(f"✅ Доставлено: {ok}\n❌ Не доставлено: {fail}")


def ai_available():
    return bool(OPENAI_API_KEY.strip()) and AsyncOpenAI is not None


async def generate_ai_post():
    if not ai_available():
        raise RuntimeError("OPENAI_API_KEY не налаштований або пакет openai не встановлено.")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    prompt = """
Ти контент-менеджер українського Telegram-каналу VILAGROTEX про продаж сільськогосподарської техніки.
Створи ОДИН короткий корисний пост українською мовою для аграріїв.

Вимоги:
- 500–900 символів.
- Тема щоразу може бути різною: порада з вибору вживаної техніки, сезонна перевірка, цікава помилка покупців, догляд, підготовка до робіт, продаж техніки.
- Не вигадуй конкретні характеристики, ціни, статистику або новини.
- Не використовуй клікбейт.
- Наприкінці м'який CTA: техніку можна купити або виставити через VILAGROTEX.
- 2–5 доречних емодзі.
- Без Markdown-заголовків із #.
Поверни тільки готовий текст поста.
"""
    response = await client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    return response.output_text.strip()


async def save_ai_post(text, status="draft"):
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ai_posts(text, status, created_at)
        VALUES (?, ?, ?)
    """, (text, status, datetime.now().strftime("%d.%m.%Y %H:%M")))
    post_id = c.lastrowid
    conn.commit()
    conn.close()
    return post_id


async def ai_post_to_admin():
    text = await generate_ai_post()
    post_id = await save_ai_post(text, "draft")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"aipublish:{post_id}"),
            InlineKeyboardButton(text="🔄 Інший варіант", callback_data="airegenerate"),
        ],
        [InlineKeyboardButton(text="❌ Відхилити", callback_data=f"aireject:{post_id}")],
    ])
    await bot.send_message(
        ADMIN_ID,
        f"🤖 <b>AI-ПОСТ НА ПЕРЕВІРКУ</b>\n\n{text}",
        reply_markup=kb,
    )


async def ai_publish_direct():
    text = await generate_ai_post()
    await bot.send_message(CHANNEL, text)
    post_id = await save_ai_post(text, "published")
    conn = connect_db()
    conn.execute(
        "UPDATE ai_posts SET published_at=? WHERE id=?",
        (datetime.now().strftime("%d.%m.%Y %H:%M"), post_id),
    )
    conn.commit()
    conn.close()


@dp.message(Command("aipost"))
async def ai_post_now(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not ai_available():
        await message.answer(
            "⚠️ AI ще не налаштований.\n"
            "Додайте OPENAI_API_KEY у верхній частині коду та встановіть пакет openai."
        )
        return
    await message.answer("🤖 Генерую пост...")
    try:
        await ai_post_to_admin()
        await message.answer("✅ Чернетку надіслано вам.")
    except Exception as e:
        await message.answer(f"❌ Помилка AI: <code>{escape(str(e))}</code>")


@dp.callback_query(F.data.startswith("aipublish:"))
async def ai_publish_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    post_id = int(callback.data.split(":")[1])
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT * FROM ai_posts WHERE id=?", (post_id,))
    row = c.fetchone()
    if not row or row["status"] != "draft":
        conn.close()
        await callback.answer("Пост уже оброблено.", show_alert=True)
        return
    await bot.send_message(CHANNEL, row["text"])
    c.execute(
        "UPDATE ai_posts SET status='published', published_at=? WHERE id=?",
        (datetime.now().strftime("%d.%m.%Y %H:%M"), post_id),
    )
    conn.commit()
    conn.close()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ AI-пост опубліковано.")
    await callback.answer()


@dp.callback_query(F.data == "airegenerate")
async def ai_regenerate(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    await callback.answer("Генерую...")
    try:
        await ai_post_to_admin()
    except Exception as e:
        await callback.message.answer(f"❌ Помилка AI: <code>{escape(str(e))}</code>")


@dp.callback_query(F.data.startswith("aireject:"))
async def ai_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    post_id = int(callback.data.split(":")[1])
    conn = connect_db()
    conn.execute("UPDATE ai_posts SET status='rejected' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ AI-пост відхилено.")
    await callback.answer()


async def daily_ai_loop():
    if not AI_DAILY_ENABLED:
        return
    tz = ZoneInfo(AI_TIMEZONE)

    while True:
        now = datetime.now(tz)
        target = now.replace(
            hour=AI_DAILY_HOUR,
            minute=AI_DAILY_MINUTE,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        if ai_available():
            try:
                if AI_AUTO_PUBLISH:
                    await ai_publish_direct()
                else:
                    await ai_post_to_admin()
            except Exception as e:
                print("Daily AI error:", e)
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"⚠️ Не вдалося створити щоденний AI-пост:\n<code>{escape(str(e))}</code>"
                    )
                except Exception:
                    pass

        await asyncio.sleep(5)



async def daily_backup_loop():
    if not AUTO_BACKUP_ENABLED:
        return
    tz = ZoneInfo(AI_TIMEZONE)
    while True:
        now = datetime.now(tz)
        target = now.replace(
            hour=AUTO_BACKUP_HOUR,
            minute=AUTO_BACKUP_MINUTE,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await send_backup_to_admin()
        except Exception as e:
            print("Auto backup error:", e)
        await asyncio.sleep(5)



async def daily_digest_loop():
    if not DAILY_DIGEST_ENABLED:
        return

    tz = ZoneInfo(AI_TIMEZONE)
    while True:
        now = datetime.now(tz)
        target = now.replace(
            hour=DAILY_DIGEST_HOUR,
            minute=DAILY_DIGEST_MINUTE,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)

        await asyncio.sleep((target - now).total_seconds())

        conn = connect_db()
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT s.user_id
            FROM subscriptions s
            JOIN users u ON u.user_id=s.user_id
            WHERE COALESCE(u.notifications_enabled,1)=1
        """)
        users = [r["user_id"] for r in c.fetchall()]
        conn.close()

        # Для простоти дайджест бере до 5 останніх активних оголошень
        # у підписаних категоріях.
        for user_id in users:
            conn = connect_db()
            c = conn.cursor()
            c.execute("SELECT category_code FROM subscriptions WHERE user_id=?", (user_id,))
            codes = [r["category_code"] for r in c.fetchall()]

            rows = []
            if codes:
                marks = ",".join("?" for _ in codes)
                c.execute(
                    f"""SELECT id,model,price,region
                        FROM ads
                        WHERE status='published'
                          AND category_code IN ({marks})
                        ORDER BY COALESCE(last_bumped_at,published_at,created_at) DESC
                        LIMIT 5""",
                    tuple(codes),
                )
                rows = c.fetchall()
            conn.close()

            if rows:
                lines = ["🌙 <b>Добірка техніки за вашими підписками</b>\\n"]
                for r in rows:
                    lines.append(
                        f"🚜 <b>{escape(r['model'])}</b> — {escape(r['price'])}, "
                        f"{escape(r['region'])}"
                    )
                try:
                    await bot.send_message(user_id, "\\n".join(lines))
                except Exception:
                    pass
            await asyncio.sleep(0.04)

        await asyncio.sleep(5)


async def main():
    create_tables()

    is_railway = bool(os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_PROJECT_ID"))
    volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")

    print("")
    print("======================================")
    print("🚜 VILAGROTEX BOT ЗАПУЩЕНИЙ")
    print("======================================")
    print(f"📢 Канал: {CHANNEL}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"💾 База: {DB_NAME}")
    if is_railway and not volume_path:
        print("⚠️ УВАГА: Railway Volume не підключений — SQLite може втратитися після redeploy.")
    elif is_railway and volume_path:
        print(f"✅ Railway Volume: {volume_path}")
    print("💳 Оплати: АКТИВНІ")
    print("🎁 Реферали: АКТИВНІ")
    print("🚜 Оголошення: АКТИВНІ")
    print("🔎 Пошук/обране/підписки: АКТИВНІ")
    print("🔥 Просування: АКТИВНЕ")
    print("💾 Auto-backup: АКТИВНИЙ" if AUTO_BACKUP_ENABLED else "💾 Auto-backup: ВИМКНЕНО")
    print(f"🤖 AI: {'АКТИВНИЙ' if ai_available() else 'НЕ НАЛАШТОВАНИЙ'}")
    print("======================================")
    print("")

    asyncio.create_task(daily_ai_loop())
    asyncio.create_task(daily_backup_loop())
    asyncio.create_task(daily_digest_loop())

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
