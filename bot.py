import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import asyncpg
import aiohttp
import json

# Конфигурация
API_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [7973988177]
USDT_RATE = 90

# ID премиум эмодзи
EMOJI = {
    "settings": "5870982283724328568",
    "profile": "5870994129244131212",
    "upload": "5963103826075456248",
    "download": "6039802767931871481",
    "server": "6030400221232501136",
    "check": "5870633910337015697",
    "cross": "5870657884844462243",
    "wallet": "5769126056262898415",
    "crypto_bot": "5260752406890711732",
    "money": "5904462880941545555",
    "calendar": "5890937706803894250",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
    "back": "5893057118545646106",
    "trash": "5870875489362513438",
    "refresh": "5345906554510012647",
    "stop": "5870657884844462243",
    "link": "5769289093221454192",
    "box": "5884479287171485878",
    "code": "5940433880585605708",
    "home": "5873147866364514353",
    "info": "6028435952299413210",
    "notification": "6039486778597970865",
    "success": "6041731551845159060",
    "people": "5870772616305839506",
    "eye": "6037397706505195857",
    "key": "6037249452824072506",
    "pencil": "5870676941614354370",
    "file": "5870528606328852614",
    "rocket": "6039422865189638057",
    "stats": "5870921681735781843"
}

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Пул подключений к БД
db_pool: Optional[asyncpg.Pool] = None

# Тарифы
TARIFFS = {
    "7": {"name": "7 Дней", "price": 10, "days": 7},
    "21": {"name": "21 День", "price": 25, "days": 21},
    "30": {"name": "30 Дней", "price": 30, "days": 30},
    "forever": {"name": "Навсегда", "price": 50, "days": None}
}

# Состояния FSM
class DeployStates(StatesGroup):
    waiting_repo = State()
    waiting_env = State()
    waiting_token = State()
    waiting_tariff = State()
    waiting_payment = State()

class AdminStates(StatesGroup):
    waiting_media_type = State()
    waiting_media = State()
    waiting_media_text = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()

# Инициализация БД
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance DECIMAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Таблица серверов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS servers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                repo_url TEXT NOT NULL,
                env_vars TEXT,
                bot_token TEXT NOT NULL,
                bot_username TEXT,
                tariff TEXT NOT NULL,
                price DECIMAL NOT NULL,
                days INTEGER,
                status TEXT DEFAULT 'pending',
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                deployed_at TIMESTAMP,
                stopped_at TIMESTAMP
            )
        ''')
        
        # Таблица платежей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                server_id INTEGER REFERENCES servers(id),
                invoice_id TEXT UNIQUE,
                amount DECIMAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                paid_at TIMESTAMP
            )
        ''')
        
        # Таблица медиа
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS media (
                section TEXT PRIMARY KEY,
                media_type TEXT,
                file_id TEXT,
                caption TEXT
            )
        ''')
        
        # Инициализация медиа
        for section in ['upload', 'my_servers', 'profile']:
            await conn.execute('''
                INSERT INTO media (section, media_type, file_id, caption)
                VALUES ($1, NULL, NULL, NULL)
                ON CONFLICT (section) DO NOTHING
            ''', section)

# Получение медиа
async def get_media(section: str) -> tuple:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT media_type, file_id, caption FROM media WHERE section = $1',
            section
        )
        if row:
            return row['media_type'], row['file_id'], row['caption']
        return None, None, None

# Отправка медиа с текстом
async def send_media_with_text(message: Message, section: str, default_text: str, keyboard=None):
    media_type, file_id, caption = await get_media(section)
    
    text = caption if caption else default_text
    
    if media_type and file_id:
        try:
            if media_type == 'photo':
                await message.answer_photo(
                    file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            elif media_type == 'video':
                await message.answer_video(
                    file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            elif media_type == 'animation':
                await message.answer_animation(
                    file_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Error sending media: {e}")
            await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

# Главное меню
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(
            text="Загрузить",
            icon_custom_emoji_id=EMOJI["upload"]
        ),
        KeyboardButton(
            text="Мои сервера",
            icon_custom_emoji_id=EMOJI["box"]
        )
    )
    builder.row(
        KeyboardButton(
            text="Профиль",
            icon_custom_emoji_id=EMOJI["profile"]
        )
    )
    if ADMIN_IDS:
        builder.row(
            KeyboardButton(
                text="Админ панель",
                icon_custom_emoji_id=EMOJI["settings"]
            )
        )
    return builder.as_markup(resize_keyboard=True)

# Клавиатура тарифов
def get_tariff_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="7 Дней - 10₽",
            callback_data="tariff_7",
            icon_custom_emoji_id=EMOJI["calendar"]
        )],
        [InlineKeyboardButton(
            text="21 День - 25₽",
            callback_data="tariff_21",
            icon_custom_emoji_id=EMOJI["calendar"]
        )],
        [InlineKeyboardButton(
            text="30 Дней - 30₽",
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
            callback_data="back_to_main",
            icon_custom_emoji_id=EMOJI["back"]
        )]
    ])

# Клавиатура оплаты
def get_payment_keyboard(invoice_url: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Оплатить",
            url=invoice_url,
            icon_custom_emoji_id=EMOJI["wallet"]
        )],
        [InlineKeyboardButton(
            text="Проверить оплату",
            callback_data="check_payment",
            icon_custom_emoji_id=EMOJI["refresh"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_tariff",
            icon_custom_emoji_id=EMOJI["back"]
        )]
    ])

# Клавиатура управления сервером
def get_server_control_keyboard(server_id: int, bot_username: str = ""):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Перейти в бота",
            url=f"https://t.me/{bot_username}" if bot_username else "https://t.me/",
            icon_custom_emoji_id=EMOJI["server"]
        )],
        [
            InlineKeyboardButton(
                text="Обновить",
                callback_data=f"server_update_{server_id}",
                icon_custom_emoji_id=EMOJI["refresh"]
            ),
            InlineKeyboardButton(
                text="Перезагрузить",
                callback_data=f"server_restart_{server_id}",
                icon_custom_emoji_id=EMOJI["refresh"]
            )
        ],
        [
            InlineKeyboardButton(
                text="Остановить",
                callback_data=f"server_stop_{server_id}",
                icon_custom_emoji_id=EMOJI["stop"]
            ),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=f"server_delete_{server_id}",
                icon_custom_emoji_id=EMOJI["trash"]
            )
        ],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_servers",
            icon_custom_emoji_id=EMOJI["back"]
        )]
    ])

# Админ клавиатура подтверждения
def get_admin_confirm_keyboard(user_id: int, server_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Я поставил на хостинг",
            callback_data=f"admin_deploy_{user_id}_{server_id}",
            icon_custom_emoji_id=EMOJI["check"]
        )]
    ])

# Админ панель
def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Медиа для Загрузить",
            callback_data="admin_media_upload",
            icon_custom_emoji_id=EMOJI["upload"]
        )],
        [InlineKeyboardButton(
            text="Медиа для Мои сервера",
            callback_data="admin_media_servers",
            icon_custom_emoji_id=EMOJI["box"]
        )],
        [InlineKeyboardButton(
            text="Медиа для Профиль",
            callback_data="admin_media_profile",
            icon_custom_emoji_id=EMOJI["profile"]
        )],
        [InlineKeyboardButton(
            text="Рассылка",
            callback_data="admin_broadcast",
            icon_custom_emoji_id=EMOJI["notification"]
        )],
        [InlineKeyboardButton(
            text="Статистика",
            callback_data="admin_stats",
            icon_custom_emoji_id=EMOJI["stats"]
        )],
        [InlineKeyboardButton(
            text="Закрыть",
            callback_data="close_admin",
            icon_custom_emoji_id=EMOJI["back"]
        )]
    ])

# Клавиатура выбора типа медиа
def get_media_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Фото",
            callback_data="media_photo",
            icon_custom_emoji_id=EMOJI["file"]
        )],
        [InlineKeyboardButton(
            text="Видео",
            callback_data="media_video",
            icon_custom_emoji_id=EMOJI["file"]
        )],
        [InlineKeyboardButton(
            text="GIF",
            callback_data="media_animation",
            icon_custom_emoji_id=EMOJI["file"]
        )],
        [InlineKeyboardButton(
            text="Только текст",
            callback_data="media_text_only",
            icon_custom_emoji_id=EMOJI["pencil"]
        )],
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_media",
            icon_custom_emoji_id=EMOJI["cross"]
        )]
    ])

# Клавиатура пропуска
def get_skip_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Пропустить",
            callback_data="skip_media_text",
            icon_custom_emoji_id=EMOJI["check"]
        )]
    ])

# Клавиатура подтверждения удаления
def get_delete_confirm_keyboard(server_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Да, удалить",
                callback_data=f"confirm_delete_{server_id}",
                icon_custom_emoji_id=EMOJI["check"]
            ),
            InlineKeyboardButton(
                text="Нет, отмена",
                callback_data="cancel_delete",
                icon_custom_emoji_id=EMOJI["cross"]
            )
        ]
    ])

# Создание счета в Crypto Bot
async def create_crypto_invoice(amount_rub: float) -> Optional[Dict]:
    amount_usdt = amount_rub / USDT_RATE
    
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    data = {
        "asset": "USDT",
        "amount": str(round(amount_usdt, 2)),
        "description": "Оплата хостинга Telegram бота",
        "paid_btn_name": "callback",
        "paid_btn_url": "https://t.me/your_bot",
        "expires_in": 3600
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    return result["result"]
    return None

# Проверка платежа
async def check_crypto_invoice(invoice_id: int) -> Optional[str]:
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN,
        "Content-Type": "application/json"
    }
    data = {"invoice_ids": str(invoice_id)}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                if result.get("ok"):
                    items = result["result"].get("items", [])
                    if items:
                        return items[0].get("status")
    return None

# Команда /start
@router.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO users (user_id, username, full_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET username = $2, full_name = $3
        ''', user.id, user.username, user.full_name)
    
    welcome_text = f"""
<tg-emoji emoji-id='{EMOJI["home"]}'>🏘</tg-emoji> <b>Добро пожаловать в Vest Host!</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Здесь вы можете разместить своего Telegram бота на хостинге.

<tg-emoji emoji-id='{EMOJI["upload"]}'>📁</tg-emoji> <b>Загрузить</b> - загрузить нового бота
<tg-emoji emoji-id='{EMOJI["box"]}'>📦</tg-emoji> <b>Мои сервера</b> - управление вашими ботами
<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> <b>Профиль</b> - информация о профиле
"""
    
    await send_media_with_text(
        message,
        "upload",
        welcome_text,
        get_main_keyboard()
    )

# Обработка текстовых команд меню
@router.message(F.text == "Загрузить")
async def upload_handler(message: Message, state: FSMContext):
    await state.set_state(DeployStates.waiting_repo)
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["code"]}'>🔨</tg-emoji> <b>Загрузка бота</b>

<tg-emoji emoji-id='{EMOJI["link"]}'>🔗</tg-emoji> Отправьте ссылку на GitHub репозиторий вашего бота.
"""
    await send_media_with_text(message, "upload", text)

@router.message(F.text == "Мои сервера")
async def my_servers_handler(message: Message):
    await show_servers(message)

@router.message(F.text == "Профиль")
async def profile_handler(message: Message):
    user = message.from_user
    
    async with db_pool.acquire() as conn:
        servers = await conn.fetch(
            "SELECT COUNT(*) FROM servers WHERE user_id = $1",
            user.id
        )
        active_servers = await conn.fetch(
            "SELECT COUNT(*) FROM servers WHERE user_id = $1 AND status = 'active'",
            user.id
        )
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> <b>Профиль</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> ID: <code>{user.id}</code>
<tg-emoji emoji-id='{EMOJI["people"]}'>👥</tg-emoji> Имя: {user.full_name}
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Всего ботов: {servers[0]['count']}
<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Активных: {active_servers[0]['count']}
"""
    await send_media_with_text(message, "profile", text, get_main_keyboard())

@router.message(F.text == "Админ панель")
async def admin_panel_handler(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(
            f"<tg-emoji emoji-id='{EMOJI['cross']}'>❌</tg-emoji> У вас нет доступа к админ панели."
        )
        return
    
    text = f"""
<tg-emoji emoji-id='{EMOJI['settings']}'>⚙</tg-emoji> <b>Админ панель</b>

Выберите действие:
"""
    await message.answer(text, reply_markup=get_admin_keyboard())

# Обработка состояния ожидания репозитория
@router.message(StateFilter(DeployStates.waiting_repo))
async def process_repo(message: Message, state: FSMContext):
    repo_url = message.text.strip()
    
    if not repo_url.startswith("https://github.com/"):
        await message.answer(
            f"<tg-emoji emoji-id='{EMOJI['cross']}'>❌</tg-emoji> Пожалуйста, отправьте корректную ссылку на GitHub репозиторий."
        )
        return
    
    await state.update_data(repo_url=repo_url)
    await state.set_state(DeployStates.waiting_env)
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["code"]}'>🔨</tg-emoji> <b>Переменные окружения</b>

<tg-emoji emoji-id='{EMOJI["key"]}'>🔒</tg-emoji> Отправьте переменные окружения в формате:

<code>KEY1=value1
KEY2=value2</code>

Или отправьте <code>-</code> если переменные не нужны.
"""
    await message.answer(text)

@router.message(StateFilter(DeployStates.waiting_env))
async def process_env(message: Message, state: FSMContext):
    env_vars = message.text.strip()
    
    await state.update_data(env_vars=env_vars if env_vars != "-" else None)
    await state.set_state(DeployStates.waiting_token)
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["key"]}'>🔒</tg-emoji> <b>Токен бота</b>

<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Отправьте токен вашего Telegram бота.
"""
    await message.answer(text)

@router.message(StateFilter(DeployStates.waiting_token))
async def process_token(message: Message, state: FSMContext):
    bot_token = message.text.strip()
    
    # Проверка токена
    try:
        test_bot = Bot(token=bot_token)
        bot_info = await test_bot.get_me()
        await test_bot.session.close()
        
        await state.update_data(bot_token=bot_token, bot_username=bot_info.username)
        await state.set_state(DeployStates.waiting_tariff)
        
        text = f"""
<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Бот @{bot_info.username} найден!

<tg-emoji emoji-id='{EMOJI["money"]}'>🪙</tg-emoji> <b>Выберите тариф:</b>
"""
        await message.answer(text, reply_markup=get_tariff_keyboard())
        
    except Exception as e:
        await message.answer(
            f"<tg-emoji emoji-id='{EMOJI['cross']}'>❌</tg-emoji> Неверный токен бота. Попробуйте снова."
        )

# Обработка callback запросов
@router.callback_query(F.data.startswith("tariff_"))
async def process_tariff(callback: CallbackQuery, state: FSMContext):
    tariff_key = callback.data.replace("tariff_", "")
    tariff = TARIFFS[tariff_key]
    
    await state.update_data(tariff=tariff_key, price=tariff["price"])
    
    # Создаем платеж
    invoice = await create_crypto_invoice(tariff["price"])
    
    if not invoice:
        await callback.message.answer(
            f"<tg-emoji emoji-id='{EMOJI['cross']}'>❌</tg-emoji> Ошибка создания платежа. Попробуйте позже."
        )
        await callback.answer()
        return
    
    await state.update_data(invoice_id=invoice["invoice_id"])
    await state.set_state(DeployStates.waiting_payment)
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["wallet"]}'>👛</tg-emoji> <b>Оплата</b>

<tg-emoji emoji-id='{EMOJI["money"]}'>🪙</tg-emoji> Сумма к оплате: <b>{tariff['price']}₽</b>
<tg-emoji emoji-id='{EMOJI["calendar"]}'>📅</tg-emoji> Тариф: <b>{tariff['name']}</b>

<tg-emoji emoji-id='{EMOJI["crypto_bot"]}'>👾</tg-emoji> Нажмите кнопку ниже для оплаты через Crypto Bot.
"""
    await callback.message.edit_text(
        text,
        reply_markup=get_payment_keyboard(invoice["bot_invoice_url"])
    )
    await callback.answer()

@router.callback_query(F.data == "check_payment")
async def check_payment_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    invoice_id = data.get("invoice_id")
    
    status = await check_crypto_invoice(invoice_id)
    
    if status == "paid":
        user_id = callback.from_user.id
        tariff_key = data["tariff"]
        tariff = TARIFFS[tariff_key]
        
        # Сохраняем сервер в БД
        async with db_pool.acquire() as conn:
            # Создаем сервер
            expires_at = None
            if tariff["days"]:
                expires_at = datetime.now() + timedelta(days=tariff["days"])
            
            server = await conn.fetchrow('''
                INSERT INTO servers 
                (user_id, repo_url, env_vars, bot_token, bot_username, tariff, price, days, expires_at, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
                RETURNING id
            ''', user_id, data["repo_url"], data["env_vars"], data["bot_token"],
                data["bot_username"], tariff["name"], tariff["price"], tariff["days"], expires_at)
            
            server_id = server["id"]
            
            # Сохраняем платеж
            await conn.execute('''
                INSERT INTO payments (user_id, server_id, invoice_id, amount, status, paid_at)
                VALUES ($1, $2, $3, $4, 'paid', NOW())
            ''', user_id, server_id, invoice_id, tariff["price"])
        
        await state.clear()
        
        # Уведомление пользователю
        await callback.message.edit_text(
            f"""
<tg-emoji emoji-id='{EMOJI["success"]}'>🎉</tg-emoji> <b>Оплата успешна!</b>

<tg-emoji emoji-id='{EMOJI["clock"]}'>⏰</tg-emoji> Бот будет поставлен на хостинг в течение 24 часов!
"""
        )
        
        # Уведомление админу
        admin_text = f"""
<tg-emoji emoji-id='{EMOJI["notification"]}'>🔔</tg-emoji> <b>Новый заказ!</b>

<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> Пользователь: @{callback.from_user.username or 'Нет'} (ID: {user_id})
<tg-emoji emoji-id='{EMOJI["code"]}'>🔨</tg-emoji> Репозиторий: {data["repo_url"]}
<tg-emoji emoji-id='{EMOJI["key"]}'>🔒</tg-emoji> Токен: <code>{data["bot_token"]}</code>
<tg-emoji emoji-id='{EMOJI["file"]}'>📁</tg-emoji> Env: <code>{data.get('env_vars') or 'Нет'}</code>
<tg-emoji emoji-id='{EMOJI["calendar"]}'>📅</tg-emoji> Тариф: {tariff["name"]}
<tg-emoji emoji-id='{EMOJI["money"]}'>🪙</tg-emoji> Цена: {tariff["price"]}₽
"""
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=get_admin_confirm_keyboard(user_id, server_id)
                )
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")
    
    elif status == "active":
        await callback.answer("Ожидает оплаты...", show_alert=True)
    else:
        await callback.answer("Платеж не найден или истек", show_alert=True)

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["home"]}'>🏘</tg-emoji> <b>Главное меню</b>
"""
    await send_media_with_text(
        callback.message,
        "upload",
        text,
        get_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_tariff")
async def back_to_tariff(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DeployStates.waiting_tariff)
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["money"]}'>🪙</tg-emoji> <b>Выберите тариф:</b>
"""
    await callback.message.edit_text(text, reply_markup=get_tariff_keyboard())
    await callback.answer()

# Админ подтверждение деплоя
@router.callback_query(F.data.startswith("admin_deploy_"))
async def admin_confirm_deploy(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    parts = callback.data.split("_")
    user_id = int(parts[2])
    server_id = int(parts[3])
    
    async with db_pool.acquire() as conn:
        # Обновляем статус сервера
        await conn.execute('''
            UPDATE servers 
            SET status = 'active', deployed_at = NOW()
            WHERE id = $1 AND user_id = $2
        ''', server_id, user_id)
        
        # Получаем информацию о сервере
        server = await conn.fetchrow(
            "SELECT bot_username FROM servers WHERE id = $1",
            server_id
        )
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Бот отмечен как размещенный!
"""
    )
    
    # Уведомление пользователю
    try:
        await bot.send_message(
            user_id,
            f"""
<tg-emoji emoji-id='{EMOJI["success"]}'>🎉</tg-emoji> <b>Бот успешно поставлен на хостинг!</b>

<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Ваш бот @{server['bot_username']} теперь активен!
"""
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
    
    await callback.answer("Подтверждено!")

# Показ списка серверов
async def show_servers(message: Message):
    user_id = message.from_user.id
    
    async with db_pool.acquire() as conn:
        servers = await conn.fetch(
            "SELECT * FROM servers WHERE user_id = $1 AND status != 'deleted' ORDER BY created_at DESC",
            user_id
        )
    
    if not servers:
        text = f"""
<tg-emoji emoji-id='{EMOJI["box"]}'>📦</tg-emoji> <b>Мои сервера</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> У вас пока нет серверов.

<tg-emoji emoji-id='{EMOJI["upload"]}'>📁</tg-emoji> Нажмите "Загрузить" чтобы добавить бота.
"""
        await send_media_with_text(message, "my_servers", text, get_main_keyboard())
        return
    
    # Создаем клавиатуру со списком серверов
    keyboard = []
    for server in servers:
        status_id = EMOJI["check"] if server["status"] == "active" else EMOJI["clock"]
        bot_name = server["bot_username"] or "Бот"
        
        keyboard.append([InlineKeyboardButton(
            text=f"{bot_name} ({server['tariff']})",
            callback_data=f"server_{server['id']}",
            icon_custom_emoji_id=status_id
        )])
    
    keyboard.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_main",
        icon_custom_emoji_id=EMOJI["back"]
    )])
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["box"]}'>📦</tg-emoji> <b>Мои сервера</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Всего: {len(servers)}
<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Активных: {sum(1 for s in servers if s['status'] == 'active')}

Выберите сервер для управления:
"""
    await send_media_with_text(
        message,
        "my_servers",
        text,
        InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("server_"))
async def server_details(callback: CallbackQuery):
    server_id = int(callback.data.replace("server_", ""))
    user_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        server = await conn.fetchrow(
            "SELECT * FROM servers WHERE id = $1 AND user_id = $2",
            server_id, user_id
        )
    
    if not server:
        await callback.answer("Сервер не найден", show_alert=True)
        return
    
    status_text = "Активен" if server["status"] == "active" else "Ожидает размещения"
    status_id = EMOJI["check"] if server["status"] == "active" else EMOJI["clock"]
    
    expires_text = "Никогда" if not server["expires_at"] else server["expires_at"].strftime("%d.%m.%Y")
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> <b>Управление ботом</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Бот: @{server['bot_username'] or 'Не указан'}
<tg-emoji emoji-id='{EMOJI["calendar"]}'>📅</tg-emoji> Тариф: {server['tariff']}
<tg-emoji emoji-id='{status_id}'></tg-emoji> Статус: {status_text}
<tg-emoji emoji-id='{EMOJI["clock"]}'>⏰</tg-emoji> Истекает: {expires_text}
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_server_control_keyboard(server_id, server["bot_username"])
    )
    await callback.answer()

# Обработка действий с сервером
@router.callback_query(F.data.startswith("server_update_"))
async def server_update(callback: CallbackQuery):
    server_id = int(callback.data.replace("server_update_", ""))
    user_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        server = await conn.fetchrow(
            "SELECT bot_username FROM servers WHERE id = $1 AND user_id = $2",
            server_id, user_id
        )
    
    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"""
<tg-emoji emoji-id='{EMOJI["refresh"]}'>🔄</tg-emoji> <b>Запрос на обновление</b>

<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> Пользователь: @{callback.from_user.username or 'Нет'} (ID: {user_id})
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Бот: @{server['bot_username']} (ID: {server_id})
<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие: Обновить
"""
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["clock"]}'>⏰</tg-emoji> <b>Запрос отправлен</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие скоро будет совершено, ожидайте до 2 часов.
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Назад к серверу",
                callback_data=f"server_{server_id}",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await callback.answer("Запрос отправлен!")

@router.callback_query(F.data.startswith("server_restart_"))
async def server_restart(callback: CallbackQuery):
    server_id = int(callback.data.replace("server_restart_", ""))
    user_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        server = await conn.fetchrow(
            "SELECT bot_username FROM servers WHERE id = $1 AND user_id = $2",
            server_id, user_id
        )
    
    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"""
<tg-emoji emoji-id='{EMOJI["refresh"]}'>🔄</tg-emoji> <b>Запрос на перезагрузку</b>

<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> Пользователь: @{callback.from_user.username or 'Нет'} (ID: {user_id})
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Бот: @{server['bot_username']} (ID: {server_id})
<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие: Перезагрузить
"""
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["clock"]}'>⏰</tg-emoji> <b>Запрос отправлен</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие скоро будет совершено, ожидайте до 2 часов.
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Назад к серверу",
                callback_data=f"server_{server_id}",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await callback.answer("Запрос отправлен!")

@router.callback_query(F.data.startswith("server_stop_"))
async def server_stop(callback: CallbackQuery):
    server_id = int(callback.data.replace("server_stop_", ""))
    user_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        server = await conn.fetchrow(
            "SELECT bot_username FROM servers WHERE id = $1 AND user_id = $2",
            server_id, user_id
        )
    
    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"""
<tg-emoji emoji-id='{EMOJI["stop"]}'>❌</tg-emoji> <b>Запрос на остановку</b>

<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> Пользователь: @{callback.from_user.username or 'Нет'} (ID: {user_id})
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Бот: @{server['bot_username']} (ID: {server_id})
<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие: Остановить
"""
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["clock"]}'>⏰</tg-emoji> <b>Запрос отправлен</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие скоро будет совершено, ожидайте до 2 часов.
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Назад к серверу",
                callback_data=f"server_{server_id}",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await callback.answer("Запрос отправлен!")

@router.callback_query(F.data.startswith("server_delete_"))
async def server_delete(callback: CallbackQuery):
    server_id = int(callback.data.replace("server_delete_", ""))
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["trash"]}'>🗑</tg-emoji> <b>Удаление сервера</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Вы уверены, что хотите удалить бота?
Это действие нельзя отменить.
""",
        reply_markup=get_delete_confirm_keyboard(server_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete(callback: CallbackQuery):
    server_id = int(callback.data.replace("confirm_delete_", ""))
    user_id = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        server = await conn.fetchrow(
            "SELECT bot_username FROM servers WHERE id = $1 AND user_id = $2",
            server_id, user_id
        )
        
        # Помечаем как удаленный
        await conn.execute(
            "UPDATE servers SET status = 'deleted' WHERE id = $1",
            server_id
        )
    
    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"""
<tg-emoji emoji-id='{EMOJI["trash"]}'>🗑</tg-emoji> <b>Запрос на удаление</b>

<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> Пользователь: @{callback.from_user.username or 'Нет'} (ID: {user_id})
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Бот: @{server['bot_username']} (ID: {server_id})
<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие: Удалить
"""
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["clock"]}'>⏰</tg-emoji> <b>Запрос отправлен</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Действие скоро будет совершено, ожидайте до 2 часов.
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_servers",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await callback.answer("Сервер удален!")

@router.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='{EMOJI['check']}'>✅</tg-emoji> Удаление отменено.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_servers",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_servers")
async def back_to_servers(callback: CallbackQuery):
    await callback.message.delete()
    await show_servers(callback.message)
    await callback.answer()

# Админ установка медиа
@router.callback_query(F.data.startswith("admin_media_"))
async def admin_media_setup(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    section = callback.data.replace("admin_media_", "")
    
    await state.update_data(media_section=section)
    await state.set_state(AdminStates.waiting_media_type)
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["file"]}'>📁</tg-emoji> <b>Выберите тип медиа</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Для раздела: <b>{section}</b>
""",
        reply_markup=get_media_type_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("media_"))
async def process_media_type(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    media_type = callback.data.replace("media_", "")
    await state.update_data(media_type=media_type)
    
    if media_type == "text_only":
        await state.set_state(AdminStates.waiting_media_text)
        await callback.message.edit_text(
            f"""
<tg-emoji emoji-id='{EMOJI["pencil"]}'>✍</tg-emoji> <b>Введите текст</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Отправьте текст, который будет отображаться в этом разделе.
""",
            reply_markup=get_skip_keyboard()
        )
    else:
        await state.set_state(AdminStates.waiting_media)
        await callback.message.edit_text(
            f"""
<tg-emoji emoji-id='{EMOJI["upload"]}'>📁</tg-emoji> <b>Отправьте медиа</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Отправьте {media_type} файл.
"""
        )
    await callback.answer()

@router.message(StateFilter(AdminStates.waiting_media), F.photo | F.video | F.animation)
async def process_media_file(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    media_type = data["media_type"]
    section = data["media_section"]
    
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.animation:
        file_id = message.animation.file_id
        media_type = "animation"
    
    await state.update_data(file_id=file_id, media_type=media_type)
    await state.set_state(AdminStates.waiting_media_text)
    
    await message.answer(
        f"""
<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Медиа получено!

<tg-emoji emoji-id='{EMOJI["pencil"]}'>✍</tg-emoji> Теперь отправьте текст (подпись) или нажмите "Пропустить".
""",
        reply_markup=get_skip_keyboard()
    )

@router.message(StateFilter(AdminStates.waiting_media_text))
async def process_media_text(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    section = data["media_section"]
    media_type = data.get("media_type")
    file_id = data.get("file_id")
    text = message.text if message.text else ""
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            UPDATE media 
            SET media_type = $1, file_id = $2, caption = $3
            WHERE section = $4
        ''', media_type, file_id, text, section)
    
    await state.clear()
    
    await message.answer(
        f"""
<tg-emoji emoji-id='{EMOJI["success"]}'>🎉</tg-emoji> <b>Медиа установлено!</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Раздел: {section}
""",
        reply_markup=get_admin_keyboard()
    )

@router.callback_query(F.data == "skip_media_text")
async def skip_media_text(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    section = data["media_section"]
    media_type = data.get("media_type")
    file_id = data.get("file_id")
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            UPDATE media 
            SET media_type = $1, file_id = $2, caption = $3
            WHERE section = $4
        ''', media_type, file_id, "", section)
    
    await state.clear()
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["success"]}'>🎉</tg-emoji> <b>Медиа установлено!</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Раздел: {section}
"""
    )
    await callback.message.answer(
        f"<tg-emoji emoji-id='{EMOJI['settings']}'>⚙</tg-emoji> Админ панель:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "cancel_media")
async def cancel_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await state.clear()
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='{EMOJI['cross']}'>❌</tg-emoji> Установка медиа отменена."
    )
    await callback.message.answer(
        f"<tg-emoji emoji-id='{EMOJI['settings']}'>⚙</tg-emoji> Админ панель:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "close_admin")
async def close_admin(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# Рассылка
@router.callback_query(F.data == "admin_broadcast")
async def broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await state.set_state(BroadcastStates.waiting_for_message)
    
    await callback.message.edit_text(
        f"""
<tg-emoji emoji-id='{EMOJI["notification"]}'>🔔</tg-emoji> <b>Рассылка</b>

<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> Отправьте сообщение, которое хотите разослать всем пользователям.
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Отмена",
                callback_data="close_admin",
                icon_custom_emoji_id=EMOJI["cross"]
            )
        ]])
    )
    await callback.answer()

@router.message(StateFilter(BroadcastStates.waiting_for_message))
async def process_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            await message.copy_to(user["user_id"])
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send broadcast to {user['user_id']}: {e}")
    
    await state.clear()
    
    await message.answer(
        f"""
<tg-emoji emoji-id='{EMOJI["success"]}'>🎉</tg-emoji> <b>Рассылка завершена!</b>

<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Успешно: {success}
<tg-emoji emoji-id='{EMOJI["cross"]}'>❌</tg-emoji> Неудачно: {failed}
"""
    )

# Статистика
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_servers = await conn.fetchval("SELECT COUNT(*) FROM servers WHERE status != 'deleted'")
        active_servers = await conn.fetchval("SELECT COUNT(*) FROM servers WHERE status = 'active'")
        total_payments = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'")
    
    text = f"""
<tg-emoji emoji-id='{EMOJI["info"]}'>ℹ</tg-emoji> <b>Статистика</b>

<tg-emoji emoji-id='{EMOJI["profile"]}'>👤</tg-emoji> Пользователей: {total_users}
<tg-emoji emoji-id='{EMOJI["server"]}'>🤖</tg-emoji> Всего серверов: {total_servers}
<tg-emoji emoji-id='{EMOJI["check"]}'>✅</tg-emoji> Активных: {active_servers}
<tg-emoji emoji-id='{EMOJI["money"]}'>🪙</tg-emoji> Заработано: {total_payments}₽
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Назад",
                callback_data="close_admin",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await callback.answer()

# Запуск бота
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
