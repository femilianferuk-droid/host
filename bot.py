import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
import json
import uuid

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand
)
from dotenv import load_dotenv
import aiohttp
import asyncpg

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
ADMIN_ID = 7973988177
ADMIN_IDS = [7973988177]
DATABASE_URL = os.getenv("DATABASE_URL")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

db_pool: Optional[asyncpg.Pool] = None

# ID премиум эмодзи
EMOJI = {
    "upload": "5870528606328852614",
    "servers": "5778672437122045013",
    "profile": "5870994129244131212",
    "calendar": "5890937706803894250",
    "gift": "6041731551845159060",
    "back": "5893057118545646106",
    "cancel": "5893192487324880883",
    "wallet": "5769126056262898415",
    "refresh": "5345906554510012647",
    "bot": "6030400221232501136",
    "settings": "5870982283724328568",
    "lock": "6037249452824072506",
    "delete": "5870875489362513438",
    "check": "5870633910337015697",
    "media": "6035128606563241721",
    "announce": "6039422865189638057",
    "stats": "5870921681735781843",
    "info": "6028435952299413210",
    "clock": "5983150113483134607",
    "link": "5769289093221454192",
    "file": "5870528606328852614",
    "crypto": "5260752406890711732",
    "money": "5904462880941545555",
    "success": "5891207662678317861",
    "pending": "5775896410780079073",
    "active": "6037496202990194718",
    "stopped": "6037249452824072506"
}


# ==================== База данных ====================
class Database:
    @staticmethod
    async def init_db():
        global db_pool
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        
        async with db_pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    bot_token TEXT NOT NULL,
                    github_url TEXT NOT NULL,
                    env_vars JSONB DEFAULT '{}',
                    tariff TEXT NOT NULL,
                    price DECIMAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    payment_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    activated_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS media (
                    id SERIAL PRIMARY KEY,
                    section TEXT UNIQUE NOT NULL,
                    media_type TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    caption TEXT
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    payment_id TEXT UNIQUE NOT NULL,
                    user_id BIGINT,
                    server_id INTEGER,
                    amount DECIMAL,
                    status TEXT DEFAULT 'pending',
                    crypto_bot_invoice_id BIGINT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    paid_at TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS action_logs (
                    id SERIAL PRIMARY KEY,
                    server_id INTEGER,
                    user_id BIGINT,
                    action TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')

    @staticmethod
    async def get_user(user_id: int):
        async with db_pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)

    @staticmethod
    async def create_user(user_id: int, username: str, first_name: str, last_name: str):
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name
            ''', user_id, username, first_name, last_name)

    @staticmethod
    async def create_server(user_id: int, bot_token: str, github_url: str, 
                            env_vars: dict, tariff: str, price: float) -> int:
        async with db_pool.acquire() as conn:
            expires_at = None
            if tariff == "7_days":
                expires_at = datetime.now() + timedelta(days=7)
            elif tariff == "21_days":
                expires_at = datetime.now() + timedelta(days=21)
            elif tariff == "30_days":
                expires_at = datetime.now() + timedelta(days=30)
            
            return await conn.fetchval('''
                INSERT INTO servers (user_id, bot_token, github_url, env_vars, tariff, price, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
            ''', user_id, bot_token, github_url, json.dumps(env_vars), tariff, price, expires_at)

    @staticmethod
    async def get_server(server_id: int):
        async with db_pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM servers WHERE id = $1', server_id)

    @staticmethod
    async def get_user_servers(user_id: int):
        async with db_pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM servers WHERE user_id = $1 AND status IN ('pending', 'active', 'stopped') ORDER BY created_at DESC",
                user_id
            )

    @staticmethod
    async def update_server_status(server_id: int, status: str):
        async with db_pool.acquire() as conn:
            if status == 'active':
                await conn.execute(
                    "UPDATE servers SET status = $1, activated_at = NOW() WHERE id = $2",
                    status, server_id
                )
            else:
                await conn.execute(
                    "UPDATE servers SET status = $1 WHERE id = $2",
                    status, server_id
                )

    @staticmethod
    async def delete_server(server_id: int):
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE servers SET status = 'deleted' WHERE id = $1", server_id)

    @staticmethod
    async def create_payment(payment_id: str, user_id: int, server_id: int, amount: float):
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO payments (payment_id, user_id, server_id, amount)
                VALUES ($1, $2, $3, $4)
            ''', payment_id, user_id, server_id, amount)

    @staticmethod
    async def update_payment(payment_id: str, status: str, crypto_bot_invoice_id: int = None):
        async with db_pool.acquire() as conn:
            if status == 'paid':
                await conn.execute('''
                    UPDATE payments SET status = $1, paid_at = NOW(), crypto_bot_invoice_id = $3
                    WHERE payment_id = $2
                ''', status, payment_id, crypto_bot_invoice_id)
            else:
                await conn.execute('''
                    UPDATE payments SET status = $1, crypto_bot_invoice_id = $3
                    WHERE payment_id = $2
                ''', status, payment_id, crypto_bot_invoice_id)

    @staticmethod
    async def get_payment_by_id(payment_id: str):
        async with db_pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM payments WHERE payment_id = $1', payment_id)

    @staticmethod
    async def create_action_log(server_id: int, user_id: int, action: str):
        async with db_pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO action_logs (server_id, user_id, action) VALUES ($1, $2, $3)',
                server_id, user_id, action
            )

    @staticmethod
    async def get_media(section: str):
        async with db_pool.acquire() as conn:
            return await conn.fetchrow('SELECT * FROM media WHERE section = $1', section)

    @staticmethod
    async def set_media(section: str, media_type: str, file_id: str, caption: str = None):
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO media (section, media_type, file_id, caption)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (section) DO UPDATE SET
                    media_type = EXCLUDED.media_type,
                    file_id = EXCLUDED.file_id,
                    caption = EXCLUDED.caption
            ''', section, media_type, file_id, caption)

    @staticmethod
    async def get_all_users():
        async with db_pool.acquire() as conn:
            return await conn.fetch('SELECT user_id FROM users')

    @staticmethod
    async def get_stats():
        async with db_pool.acquire() as conn:
            total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
            total_servers = await conn.fetchval('SELECT COUNT(*) FROM servers')
            active_servers = await conn.fetchval("SELECT COUNT(*) FROM servers WHERE status = 'active'")
            total_payments = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'")
            return {
                'total_users': total_users,
                'total_servers': total_servers,
                'active_servers': active_servers,
                'total_payments': float(total_payments) if total_payments else 0
            }


# ==================== Состояния ====================
class UploadStates(StatesGroup):
    waiting_github = State()
    waiting_env = State()
    waiting_token = State()
    waiting_tariff = State()


class AdminStates(StatesGroup):
    waiting_media_section = State()
    waiting_media_upload = State()
    waiting_broadcast = State()


# ==================== Временное хранилище ====================
temp_data = {}


# ==================== Клавиатуры ====================
class Keyboards:
    @staticmethod
    def main_menu():
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="Загрузить",
                    icon_custom_emoji_id=EMOJI["upload"]
                )],
                [KeyboardButton(
                    text="Мои сервера",
                    icon_custom_emoji_id=EMOJI["servers"]
                )],
                [KeyboardButton(
                    text="Профиль",
                    icon_custom_emoji_id=EMOJI["profile"]
                )]
            ],
            resize_keyboard=True
        )

    @staticmethod
    def tariff_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="7 Дней - 10₽",
                callback_data="tariff_7",
                icon_custom_emoji_id=EMOJI["calendar"]
            )],
            [InlineKeyboardButton(
                text="21 день - 25₽",
                callback_data="tariff_21",
                icon_custom_emoji_id=EMOJI["calendar"]
            )],
            [InlineKeyboardButton(
                text="30 дней - 30₽",
                callback_data="tariff_30",
                icon_custom_emoji_id=EMOJI["calendar"]
            )],
            [InlineKeyboardButton(
                text="Навсегда - 50₽",
                callback_data="tariff_forever",
                icon_custom_emoji_id=EMOJI["gift"]
            )],
            [InlineKeyboardButton(
                text="Назад",
                callback_data="cancel_upload",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])

    @staticmethod
    def cancel_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="cancel_upload",
                icon_custom_emoji_id=EMOJI["cancel"]
            )]
        ])

    @staticmethod
    def pay_keyboard(payment_url: str, payment_id: str):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Оплатить",
                url=payment_url,
                icon_custom_emoji_id=EMOJI["wallet"]
            )],
            [InlineKeyboardButton(
                text="Проверить оплату",
                callback_data=f"check_payment_{payment_id}",
                icon_custom_emoji_id=EMOJI["refresh"]
            )],
            [InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_tariff",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])

    @staticmethod
    def server_control_keyboard(server_id: int, bot_username: str = None):
        buttons = []
        if bot_username:
            buttons.append([
                InlineKeyboardButton(
                    text="Перейти в бота",
                    url=f"https://t.me/{bot_username}",
                    icon_custom_emoji_id=EMOJI["bot"]
                )
            ])
        
        buttons.extend([
            [
                InlineKeyboardButton(
                    text="Обновить",
                    callback_data=f"update_{server_id}",
                    icon_custom_emoji_id=EMOJI["refresh"]
                ),
                InlineKeyboardButton(
                    text="Перезагрузить",
                    callback_data=f"restart_{server_id}",
                    icon_custom_emoji_id=EMOJI["settings"]
                )
            ],
            [
                InlineKeyboardButton(
                    text="Остановить",
                    callback_data=f"stop_{server_id}",
                    icon_custom_emoji_id=EMOJI["lock"]
                ),
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"delete_{server_id}",
                    icon_custom_emoji_id=EMOJI["delete"]
                )
            ],
            [InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_servers",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def admin_approve_keyboard(server_id: int):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Я поставил на хостинг",
                callback_data=f"approve_server_{server_id}",
                icon_custom_emoji_id=EMOJI["check"]
            )]
        ])

    @staticmethod
    def admin_menu_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Установить медиа",
                callback_data="admin_set_media",
                icon_custom_emoji_id=EMOJI["media"]
            )],
            [InlineKeyboardButton(
                text="Рассылка",
                callback_data="admin_broadcast",
                icon_custom_emoji_id=EMOJI["announce"]
            )],
            [InlineKeyboardButton(
                text="Статистика",
                callback_data="admin_stats",
                icon_custom_emoji_id=EMOJI["stats"]
            )]
        ])

    @staticmethod
    def media_section_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Загрузить",
                callback_data="media_upload",
                icon_custom_emoji_id=EMOJI["upload"]
            )],
            [InlineKeyboardButton(
                text="Мои сервера",
                callback_data="media_servers",
                icon_custom_emoji_id=EMOJI["servers"]
            )],
            [InlineKeyboardButton(
                text="Профиль",
                callback_data="media_profile",
                icon_custom_emoji_id=EMOJI["profile"]
            )],
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])

    @staticmethod
    def back_to_servers_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад к серверам",
                callback_data="back_to_servers",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])


# ==================== Crypto Bot API ====================
class CryptoBot:
    API_URL = "https://pay.crypt.bot/api"
    
    @staticmethod
    async def create_invoice(amount_usdt: float) -> dict:
        """Создание счёта в Crypto Bot. Курс 1 USDT = 90₽"""
        amount_rub = amount_usdt * 90
        
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            data = {
                "asset": "USDT",
                "amount": str(amount_usdt),
                "description": "Оплата хостинга Telegram бота",
                "allow_anonymous": False
            }
            
            async with session.post(
                f"{CryptoBot.API_URL}/createInvoice",
                headers=headers,
                json=data
            ) as response:
                result = await response.json()
                if result.get("ok"):
                    return result["result"]
                return None

    @staticmethod
    async def check_invoice(invoice_id: int) -> dict:
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            data = {"invoice_ids": [invoice_id]}
            
            async with session.post(
                f"{CryptoBot.API_URL}/getInvoices",
                headers=headers,
                json=data
            ) as response:
                result = await response.json()
                if result.get("ok") and result["result"]["items"]:
                    return result["result"]["items"][0]
                return None


# ==================== Вспомогательные функции ====================
def get_emoji_text(emoji_key: str, text_char: str) -> str:
    """Форматирует текст с премиум эмодзи"""
    emoji_id = EMOJI.get(emoji_key, EMOJI["info"])
    return f"<tg-emoji emoji-id='{emoji_id}'>{text_char}</tg-emoji>"


# ==================== Обработчики команд ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    await Database.create_user(user.id, user.username, user.first_name, user.last_name)
    
    media = await Database.get_media("profile")
    success_emoji = get_emoji_text("success", "✅")
    
    if media:
        if media['media_type'] == 'photo':
            await message.answer_photo(
                media['file_id'],
                caption=media['caption'] or f"{success_emoji} Добро пожаловать, {user.first_name}!",
                reply_markup=Keyboards.main_menu()
            )
            return
    
    await message.answer(
        f"{success_emoji} Добро пожаловать в <b>Vest Host</b>!\n\n"
        f"Здесь вы можете разместить своего Telegram бота на хостинге.",
        reply_markup=Keyboards.main_menu()
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        cancel_emoji = get_emoji_text("cancel", "❌")
        await message.answer(f"{cancel_emoji} У вас нет доступа.")
        return
    
    settings_emoji = get_emoji_text("settings", "⚙")
    await message.answer(
        f"{settings_emoji} Админ-панель",
        reply_markup=Keyboards.admin_menu_keyboard()
    )


@router.message(F.text == "Загрузить")
async def upload_start(message: Message, state: FSMContext):
    media = await Database.get_media("upload")
    file_emoji = get_emoji_text("file", "📁")
    
    if media:
        if media['media_type'] == 'photo':
            await message.answer_photo(
                media['file_id'],
                caption=media['caption'] or f"{file_emoji} Отправьте ссылку на GitHub репозиторий:",
                reply_markup=Keyboards.cancel_keyboard()
            )
        else:
            await message.answer(
                media['caption'] or f"{file_emoji} Отправьте ссылку на GitHub репозиторий:",
                reply_markup=Keyboards.cancel_keyboard()
            )
    else:
        await message.answer(
            f"{file_emoji} Отправьте ссылку на GitHub репозиторий:",
            reply_markup=Keyboards.cancel_keyboard()
        )
    await state.set_state(UploadStates.waiting_github)


@router.message(F.text == "Мои сервера")
async def my_servers(message: Message):
    servers = await Database.get_user_servers(message.from_user.id)
    media = await Database.get_media("servers")
    
    info_emoji = get_emoji_text("info", "ℹ")
    servers_emoji = get_emoji_text("servers", "📦")
    
    if not servers:
        text = f"{info_emoji} У вас пока нет серверов."
        if media and media['media_type'] == 'photo':
            await message.answer_photo(media['file_id'], caption=text)
        else:
            await message.answer(text)
        return
    
    text = f"{servers_emoji} <b>Ваши сервера:</b>\n\n"
    
    for server in servers:
        if server['status'] == 'pending':
            status_emoji = get_emoji_text("pending", "⏳")
        elif server['status'] == 'active':
            status_emoji = get_emoji_text("active", "✅")
        else:
            status_emoji = get_emoji_text("stopped", "🔒")
        
        text += f"{status_emoji} <b>Бот #{server['id']}</b>\n"
        text += f"Тариф: {server['tariff']}\n"
        if server['expires_at']:
            days_left = (server['expires_at'] - datetime.now()).days
            text += f"Дней осталось: {max(0, days_left)}\n"
        text += f"/server_{server['id']}\n\n"
    
    if media and media['media_type'] == 'photo':
        await message.answer_photo(
            media['file_id'],
            caption=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Обновить",
                    callback_data="refresh_servers",
                    icon_custom_emoji_id=EMOJI["refresh"]
                )]
            ])
        )
    else:
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Обновить",
                    callback_data="refresh_servers",
                    icon_custom_emoji_id=EMOJI["refresh"]
                )]
            ])
        )


@router.message(F.text == "Профиль")
async def profile(message: Message):
    user = message.from_user
    servers = await Database.get_user_servers(user.id)
    active_servers = len([s for s in servers if s['status'] == 'active'])
    
    media = await Database.get_media("profile")
    
    profile_emoji = get_emoji_text("profile", "👤")
    servers_emoji = get_emoji_text("servers", "📦")
    active_emoji = get_emoji_text("active", "🔓")
    
    text = (
        f"{profile_emoji} <b>Профиль</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {user.first_name}\n"
        f"Username: @{user.username or 'нет'}\n\n"
        f"{servers_emoji} Всего серверов: {len(servers)}\n"
        f"{active_emoji} Активных: {active_servers}"
    )
    
    if media and media['media_type'] == 'photo':
        await message.answer_photo(media['file_id'], caption=text)
    else:
        await message.answer(text)


@router.message(Command("server_"))
async def server_details(message: Message):
    try:
        server_id = int(message.text.split("_")[1])
    except:
        cancel_emoji = get_emoji_text("cancel", "❌")
        await message.answer(f"{cancel_emoji} Неверный ID сервера")
        return
    
    server = await Database.get_server(server_id)
    
    if not server or server['user_id'] != message.from_user.id:
        cancel_emoji = get_emoji_text("cancel", "❌")
        await message.answer(f"{cancel_emoji} Сервер не найден")
        return
    
    status_text = {
        'pending': 'Ожидает активации',
        'active': 'Активен',
        'stopped': 'Остановлен'
    }.get(server['status'], 'Неизвестно')
    
    bot_emoji = get_emoji_text("bot", "🤖")
    
    text = (
        f"{bot_emoji} <b>Бот #{server['id']}</b>\n\n"
        f"Статус: {status_text}\n"
        f"Тариф: {server['tariff']}\n"
        f"GitHub: {server['github_url']}\n"
        f"Создан: {server['created_at'].strftime('%d.%m.%Y')}\n"
    )
    
    if server['expires_at']:
        text += f"Истекает: {server['expires_at'].strftime('%d.%m.%Y')}\n"
    
    await message.answer(
        text,
        reply_markup=Keyboards.server_control_keyboard(server_id)
    )


# ==================== Обработчики состояний загрузки ====================
@router.message(UploadStates.waiting_github)
async def process_github(message: Message, state: FSMContext):
    github_url = message.text.strip()
    cancel_emoji = get_emoji_text("cancel", "❌")
    
    if not github_url.startswith("https://github.com/"):
        await message.answer(
            f"{cancel_emoji} Пожалуйста, отправьте корректную ссылку на GitHub репозиторий",
            reply_markup=Keyboards.cancel_keyboard()
        )
        return
    
    await state.update_data(github_url=github_url)
    
    settings_emoji = get_emoji_text("settings", "⚙")
    await message.answer(
        f"{settings_emoji} Отправьте переменные окружения в формате:\n"
        f"<code>KEY1=value1\nKEY2=value2</code>\n\n"
        f"Или отправьте <code>-</code> если их нет",
        reply_markup=Keyboards.cancel_keyboard()
    )
    await state.set_state(UploadStates.waiting_env)


@router.message(UploadStates.waiting_env)
async def process_env(message: Message, state: FSMContext):
    env_text = message.text.strip()
    env_vars = {}
    
    if env_text != "-":
        for line in env_text.split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()
    
    await state.update_data(env_vars=env_vars)
    
    lock_emoji = get_emoji_text("lock", "🔒")
    await message.answer(
        f"{lock_emoji} Отправьте токен вашего бота:",
        reply_markup=Keyboards.cancel_keyboard()
    )
    await state.set_state(UploadStates.waiting_token)


@router.message(UploadStates.waiting_token)
async def process_token(message: Message, state: FSMContext):
    bot_token = message.text.strip()
    cancel_emoji = get_emoji_text("cancel", "❌")
    money_emoji = get_emoji_text("money", "🪙")
    
    # Проверяем валидность токена
    try:
        temp_bot = Bot(token=bot_token)
        bot_info = await temp_bot.get_me()
        await temp_bot.session.close()
        
        await state.update_data(bot_token=bot_token, bot_username=bot_info.username)
        
        await message.answer(
            f"{money_emoji} Выберите тариф:",
            reply_markup=Keyboards.tariff_keyboard()
        )
        await state.set_state(UploadStates.waiting_tariff)
        
    except Exception as e:
        await message.answer(
            f"{cancel_emoji} Неверный токен бота. Попробуйте снова:",
            reply_markup=Keyboards.cancel_keyboard()
        )


# ==================== Обработчики callback ====================
@router.callback_query(F.data == "cancel_upload")
async def cancel_upload(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    cancel_emoji = get_emoji_text("cancel", "❌")
    await callback.message.answer(
        f"{cancel_emoji} Загрузка отменена",
        reply_markup=Keyboards.main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_tariff")
async def back_to_tariff(callback: CallbackQuery, state: FSMContext):
    money_emoji = get_emoji_text("money", "🪙")
    await callback.message.edit_text(
        f"{money_emoji} Выберите тариф:",
        reply_markup=Keyboards.tariff_keyboard()
    )
    await state.set_state(UploadStates.waiting_tariff)
    await callback.answer()


@router.callback_query(F.data == "back_to_servers")
async def back_to_servers(callback: CallbackQuery):
    servers = await Database.get_user_servers(callback.from_user.id)
    info_emoji = get_emoji_text("info", "ℹ")
    servers_emoji = get_emoji_text("servers", "📦")
    
    if not servers:
        await callback.message.edit_text(f"{info_emoji} У вас пока нет серверов.")
        await callback.answer()
        return
    
    text = f"{servers_emoji} <b>Ваши сервера:</b>\n\n"
    
    for server in servers:
        if server['status'] == 'pending':
            status_emoji = get_emoji_text("pending", "⏳")
        elif server['status'] == 'active':
            status_emoji = get_emoji_text("active", "✅")
        else:
            status_emoji = get_emoji_text("stopped", "🔒")
        
        text += f"{status_emoji} <b>Бот #{server['id']}</b> - /server_{server['id']}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Обновить",
                callback_data="refresh_servers",
                icon_custom_emoji_id=EMOJI["refresh"]
            )]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "refresh_servers")
async def refresh_servers(callback: CallbackQuery):
    await back_to_servers(callback)


@router.callback_query(F.data.startswith("tariff_"))
async def process_tariff(callback: CallbackQuery, state: FSMContext):
    tariff_map = {
        "tariff_7": ("7_days", "7 дней", 10),
        "tariff_21": ("21_days", "21 день", 25),
        "tariff_30": ("30_days", "30 дней", 30),
        "tariff_forever": ("forever", "Навсегда", 50)
    }
    
    tariff_key, tariff_name, price = tariff_map[callback.data]
    
    data = await state.get_data()
    await state.clear()
    
    # Создаём сервер в БД
    server_id = await Database.create_server(
        callback.from_user.id,
        data['bot_token'],
        data['github_url'],
        data['env_vars'],
        tariff_name,
        price
    )
    
    # Создаём платёж
    payment_id = str(uuid.uuid4())
    await Database.create_payment(payment_id, callback.from_user.id, server_id, price / 90)
    
    # Создаём счёт в Crypto Bot
    invoice = await CryptoBot.create_invoice(price / 90)
    
    cancel_emoji = get_emoji_text("cancel", "❌")
    crypto_emoji = get_emoji_text("crypto", "👾")
    
    if not invoice:
        await callback.message.edit_text(
            f"{cancel_emoji} Ошибка создания счёта. Попробуйте позже."
        )
        await callback.answer()
        return
    
    await Database.update_payment(payment_id, 'pending', invoice['invoice_id'])
    
    text = (
        f"{crypto_emoji} <b>Оплата</b>\n\n"
        f"Тариф: {tariff_name}\n"
        f"Сумма: {price}₽ ({price / 90:.2f} USDT)\n\n"
        f"Нажмите кнопку ниже для оплаты:"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.pay_keyboard(invoice['pay_url'], payment_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("check_payment_", "")
    
    payment = await Database.get_payment_by_id(payment_id)
    
    if not payment:
        await callback.answer("Платёж не найден", show_alert=True)
        return
    
    invoice = await CryptoBot.check_invoice(payment['crypto_bot_invoice_id'])
    
    success_emoji = get_emoji_text("success", "✅")
    clock_emoji = get_emoji_text("clock", "⏰")
    crypto_emoji = get_emoji_text("crypto", "👾")
    
    if invoice and invoice['status'] == 'paid':
        await Database.update_payment(payment_id, 'paid')
        await Database.update_server_status(payment['server_id'], 'pending')
        
        # Отправляем данные админу
        server = await Database.get_server(payment['server_id'])
        user = await Database.get_user(payment['user_id'])
        
        admin_text = (
            f"{crypto_emoji} <b>Новый заказ!</b>\n\n"
            f"Пользователь: @{user['username'] or 'нет'} (ID: {user['user_id']})\n"
            f"Сервер ID: {server['id']}\n"
            f"GitHub: {server['github_url']}\n"
            f"Токен: <code>{server['bot_token']}</code>\n"
            f"Тариф: {server['tariff']}\n"
            f"Сумма: {server['price']}₽\n\n"
            f"Переменные окружения:\n<code>{json.dumps(server['env_vars'], ensure_ascii=False, indent=2)}</code>"
        )
        
        await bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=Keyboards.admin_approve_keyboard(server['id'])
        )
        
        await callback.message.edit_text(
            f"{success_emoji} Оплата успешна!\n\n"
            f"{clock_emoji} Бот будет поставлен на хостинг в течение 24 часов!"
        )
        
        await bot.send_message(
            callback.from_user.id,
            f"{success_emoji} Оплата успешна! Бот будет поставлен на хостинг в течение 24 часов!",
            reply_markup=Keyboards.main_menu()
        )
        
        await callback.answer("Оплата подтверждена!", show_alert=True)
    else:
        await callback.answer("Оплата ещё не поступила", show_alert=True)


# ==================== Управление сервером ====================
@router.callback_query(F.data.startswith("update_"))
async def server_update(callback: CallbackQuery):
    server_id = int(callback.data.replace("update_", ""))
    await Database.create_action_log(server_id, callback.from_user.id, "update")
    
    refresh_emoji = get_emoji_text("refresh", "🔄")
    clock_emoji = get_emoji_text("clock", "⏰")
    
    await bot.send_message(
        ADMIN_ID,
        f"{refresh_emoji} Пользователь @{callback.from_user.username or 'нет'} (ID: {callback.from_user.id}) "
        f"запросил <b>обновление</b> бота #{server_id}"
    )
    
    await callback.message.edit_text(
        f"{clock_emoji} Действие скоро будет совершено, ожидайте до 2 часов.",
        reply_markup=Keyboards.back_to_servers_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("restart_"))
async def server_restart(callback: CallbackQuery):
    server_id = int(callback.data.replace("restart_", ""))
    await Database.create_action_log(server_id, callback.from_user.id, "restart")
    
    settings_emoji = get_emoji_text("settings", "⚙")
    clock_emoji = get_emoji_text("clock", "⏰")
    
    await bot.send_message(
        ADMIN_ID,
        f"{settings_emoji} Пользователь @{callback.from_user.username or 'нет'} (ID: {callback.from_user.id}) "
        f"запросил <b>перезагрузку</b> бота #{server_id}"
    )
    
    await callback.message.edit_text(
        f"{clock_emoji} Действие скоро будет совершено, ожидайте до 2 часов.",
        reply_markup=Keyboards.back_to_servers_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stop_"))
async def server_stop(callback: CallbackQuery):
    server_id = int(callback.data.replace("stop_", ""))
    await Database.create_action_log(server_id, callback.from_user.id, "stop")
    
    lock_emoji = get_emoji_text("lock", "🔒")
    clock_emoji = get_emoji_text("clock", "⏰")
    
    await bot.send_message(
        ADMIN_ID,
        f"{lock_emoji} Пользователь @{callback.from_user.username or 'нет'} (ID: {callback.from_user.id}) "
        f"запросил <b>остановку</b> бота #{server_id}"
    )
    
    await callback.message.edit_text(
        f"{clock_emoji} Действие скоро будет совершено, ожидайте до 2 часов.",
        reply_markup=Keyboards.back_to_servers_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_"))
async def server_delete(callback: CallbackQuery):
    server_id = int(callback.data.replace("delete_", ""))
    await Database.create_action_log(server_id, callback.from_user.id, "delete")
    
    delete_emoji = get_emoji_text("delete", "🗑")
    clock_emoji = get_emoji_text("clock", "⏰")
    
    await bot.send_message(
        ADMIN_ID,
        f"{delete_emoji} Пользователь @{callback.from_user.username or 'нет'} (ID: {callback.from_user.id}) "
        f"запросил <b>удаление</b> бота #{server_id}"
    )
    
    await callback.message.edit_text(
        f"{clock_emoji} Действие скоро будет совершено, ожидайте до 2 часов.",
        reply_markup=Keyboards.back_to_servers_keyboard()
    )
    await callback.answer()


# ==================== Админ панель ====================
@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    settings_emoji = get_emoji_text("settings", "⚙")
    await callback.message.edit_text(
        f"{settings_emoji} Админ-панель",
        reply_markup=Keyboards.admin_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_set_media")
async def admin_set_media(callback: CallbackQuery, state: FSMContext):
    media_emoji = get_emoji_text("media", "🖼")
    await callback.message.edit_text(
        f"{media_emoji} Выберите раздел для установки медиа:",
        reply_markup=Keyboards.media_section_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("media_"))
async def admin_media_section(callback: CallbackQuery, state: FSMContext):
    section = callback.data.replace("media_", "")
    await state.update_data(media_section=section)
    
    upload_emoji = get_emoji_text("upload", "📁")
    await callback.message.edit_text(
        f"{upload_emoji} Отправьте медиа (фото/видео/документ) с подписью (опционально)\n\n"
        f"Отправьте /cancel для отмены",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_set_media",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_media_upload)
    await callback.answer()


@router.message(AdminStates.waiting_media_upload, F.content_type.in_([
    ContentType.PHOTO, ContentType.VIDEO, ContentType.DOCUMENT,
    ContentType.AUDIO, ContentType.ANIMATION
]))
async def admin_receive_media(message: Message, state: FSMContext):
    data = await state.get_data()
    section = data.get('media_section')
    
    media_type = message.content_type
    file_id = None
    
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.animation:
        file_id = message.animation.file_id
    
    caption = message.caption or message.text
    
    await Database.set_media(section, media_type, file_id, caption)
    
    await state.clear()
    success_emoji = get_emoji_text("success", "✅")
    await message.answer(
        f"{success_emoji} Медиа для раздела <b>{section}</b> установлено!",
        reply_markup=Keyboards.admin_menu_keyboard()
    )


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    announce_emoji = get_emoji_text("announce", "📣")
    await callback.message.edit_text(
        f"{announce_emoji} Отправьте сообщение для рассылки всем пользователям.\n\n"
        f"Отправьте /cancel для отмены",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()


@router.message(AdminStates.waiting_broadcast)
async def admin_send_broadcast(message: Message, state: FSMContext):
    users = await Database.get_all_users()
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            await message.copy_to(user['user_id'])
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1
    
    await state.clear()
    success_emoji = get_emoji_text("success", "✅")
    await message.answer(
        f"{success_emoji} Рассылка завершена!\n\n"
        f"Успешно: {success}\n"
        f"Ошибок: {failed}",
        reply_markup=Keyboards.admin_menu_keyboard()
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    stats = await Database.get_stats()
    
    stats_emoji = get_emoji_text("stats", "📊")
    profile_emoji = get_emoji_text("profile", "👤")
    servers_emoji = get_emoji_text("servers", "📦")
    active_emoji = get_emoji_text("active", "🔓")
    money_emoji = get_emoji_text("money", "🪙")
    
    text = (
        f"{stats_emoji} <b>Статистика</b>\n\n"
        f"{profile_emoji} Пользователей: {stats['total_users']}\n"
        f"{servers_emoji} Всего серверов: {stats['total_servers']}\n"
        f"{active_emoji} Активных: {stats['active_servers']}\n"
        f"{money_emoji} Заработано: {stats['total_payments']}₽"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("approve_server_"))
async def admin_approve_server(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    server_id = int(callback.data.replace("approve_server_", ""))
    
    await Database.update_server_status(server_id, 'active')
    server = await Database.get_server(server_id)
    
    success_emoji = get_emoji_text("success", "✅")
    
    await bot.send_message(
        server['user_id'],
        f"{success_emoji} Бот успешно поставлен на хостинг!\n\n"
        f"Используйте /server_{server_id} для управления."
    )
    
    await callback.message.edit_text(
        callback.message.text + f"\n\n{success_emoji} <b>Подтверждено!</b>"
    )
    await callback.answer("Сервер активирован!")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    cancel_emoji = get_emoji_text("cancel", "❌")
    await message.answer(
        f"{cancel_emoji} Действие отменено",
        reply_markup=Keyboards.main_menu()
    )


# ==================== Запуск ====================
async def set_commands():
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="admin", description="Админ-панель"),
        BotCommand(command="cancel", description="Отменить действие")
    ]
    await bot.set_my_commands(commands)


async def on_startup():
    await Database.init_db()
    await set_commands()
    logger.info("Бот запущен!")


async def main():
    await on_startup()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
