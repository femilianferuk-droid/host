import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiohttp import ClientSession
from dotenv import load_dotenv
import asyncpg
from contextlib import asynccontextmanager

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [7973988177]
USDT_RATE = 90

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Пул подключений к БД
db_pool: Optional[asyncpg.Pool] = None

# Премиум эмодзи ID
EMOJI = {
    "gear": "5870982283724328568",
    "profile": "5870994129244131212",
    "people": "5870772616305839506",
    "person_check": "5891207662678317861",
    "person_cross": "5893192487324880883",
    "file": "5870528606328852614",
    "smile": "5870764288364252592",
    "growth": "5870930636742595124",
    "stats": "5870921681735781843",
    "house": "5873147866364514353",
    "lock_closed": "6037249452824072506",
    "lock_open": "6037496202990194718",
    "megaphone": "6039422865189638057",
    "check": "5870633910337015697",
    "cross": "5870657884844462243",
    "pencil": "5870676941614354370",
    "trash": "5870875489362513438",
    "down": "5893057118545646106",
    "clip": "6039451237743595514",
    "link": "5769289093221454192",
    "info": "6028435952299413210",
    "bot": "6030400221232501136",
    "eye": "6037397706505195857",
    "eye_hidden": "6037243349675544634",
    "send": "5963103826075456248",
    "download": "6039802767931871481",
    "bell": "6039486778597970865",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
    "celebration": "6041731551845159060",
    "font": "5870801517140775623",
    "write": "5870753782874246579",
    "media": "6035128606563241721",
    "geo": "6042011682497106307",
    "wallet": "5769126056262898415",
    "box": "5884479287171485878",
    "crypto_bot": "5260752406890711732",
    "calendar": "5890937706803894250",
    "tag": "5886285355279193209",
    "time_past": "5775896410780079073",
    "apps": "5778672437122045013",
    "brush": "6050679691004612757",
    "add_text": "5771851822897566479",
    "format": "5778479949572738874",
    "money": "5904462880941545555",
    "send_money": "5890848474563352982",
    "accept_money": "5879814368572478751",
    "code": "5940433880585605708",
    "refresh": "5345906554510012647",
    "back": "5893057118545646106",
    "key": "5870384628593452559",
    "star": "5370599459661045441",
}

# База данных
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Таблица ботов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS bots (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                github_url TEXT NOT NULL,
                env_vars TEXT,
                bot_token TEXT NOT NULL,
                bot_username VARCHAR(255),
                tariff_period VARCHAR(50) NOT NULL,
                tariff_price INTEGER NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                invoice_id INTEGER,
                paid_at TIMESTAMP,
                approved_at TIMESTAMP,
                approved_by BIGINT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Таблица индексов
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_bots_status ON bots(status)')
        
        # Таблица медиа для админа
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_media (
                section VARCHAR(50) PRIMARY KEY,
                file_id TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Таблица логов действий
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                action VARCHAR(50) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Таблица счетов
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                bot_id INTEGER REFERENCES bots(id) ON DELETE CASCADE,
                invoice_id INTEGER NOT NULL,
                pay_url TEXT NOT NULL,
                amount_rub INTEGER NOT NULL,
                amount_usdt DECIMAL(10, 2) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                paid_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

@asynccontextmanager
async def get_db():
    async with db_pool.acquire() as conn:
        yield conn

# Функции работы с БД
async def get_or_create_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    async with get_db() as conn:
        user = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
        if not user:
            user = await conn.fetchrow('''
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    updated_at = NOW()
                RETURNING *
            ''', user_id, username, first_name, last_name)
        return user

async def create_bot(user_id: int, data: dict) -> int:
    async with get_db() as conn:
        bot_record = await conn.fetchrow('''
            INSERT INTO bots (user_id, github_url, env_vars, bot_token, bot_username, tariff_period, tariff_price, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
            RETURNING id
        ''', user_id, data['github_url'], data['env_vars'], data['bot_token'], 
            data['bot_username'], data['tariff_period'], data['tariff_price'])
        return bot_record['id']

async def update_bot_status(bot_id: int, status: str, **kwargs):
    async with get_db() as conn:
        updates = ['status = $1', 'updated_at = NOW()']
        values = [status]
        idx = 2
        
        for key, value in kwargs.items():
            if value is not None:
                updates.append(f'{key} = ${idx}')
                values.append(value)
                idx += 1
        
        values.append(bot_id)
        query = f"UPDATE bots SET {', '.join(updates)} WHERE id = ${idx}"
        await conn.execute(query, *values)

async def get_user_bots(user_id: int) -> List[dict]:
    async with get_db() as conn:
        bots = await conn.fetch('''
            SELECT * FROM bots 
            WHERE user_id = $1 AND status IN ('paid', 'approved', 'active')
            ORDER BY created_at DESC
        ''', user_id)
        return [dict(bot) for bot in bots]

async def get_bot_by_id(bot_id: int) -> Optional[dict]:
    async with get_db() as conn:
        bot = await conn.fetchrow('SELECT * FROM bots WHERE id = $1', bot_id)
        return dict(bot) if bot else None

async def get_admin_media(section: str) -> Optional[str]:
    async with get_db() as conn:
        media = await conn.fetchrow('SELECT file_id FROM admin_media WHERE section = $1', section)
        return media['file_id'] if media else None

async def set_admin_media(section: str, file_id: str):
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO admin_media (section, file_id)
            VALUES ($1, $2)
            ON CONFLICT (section) DO UPDATE SET
                file_id = EXCLUDED.file_id,
                updated_at = NOW()
        ''', section, file_id)

async def create_invoice_record(user_id: int, bot_id: int, invoice_data: dict):
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO invoices (user_id, bot_id, invoice_id, pay_url, amount_rub, amount_usdt, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending')
        ''', user_id, bot_id, invoice_data['invoice_id'], invoice_data['pay_url'],
            invoice_data['amount_rub'], invoice_data['amount_usdt'])

async def update_invoice_status(invoice_id: int, status: str):
    async with get_db() as conn:
        await conn.execute('''
            UPDATE invoices SET status = $1, paid_at = NOW()
            WHERE invoice_id = $2
        ''', status, invoice_id)

async def get_pending_bots_count() -> int:
    async with get_db() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM bots WHERE status = 'pending'")
        return count

async def get_stats() -> dict:
    async with get_db() as conn:
        total_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM users")
        total_bots = await conn.fetchval("SELECT COUNT(*) FROM bots WHERE status IN ('paid', 'approved', 'active')")
        pending_bots = await conn.fetchval("SELECT COUNT(*) FROM bots WHERE status = 'pending'")
        total_revenue = await conn.fetchval("SELECT COALESCE(SUM(amount_rub), 0) FROM invoices WHERE status = 'paid'")
        
        return {
            'total_users': total_users,
            'total_bots': total_bots,
            'pending_bots': pending_bots,
            'total_revenue': total_revenue
        }

async def create_action_log(user_id: int, bot_id: int, action: str):
    async with get_db() as conn:
        await conn.execute('''
            INSERT INTO action_logs (user_id, bot_id, action)
            VALUES ($1, $2, $3)
        ''', user_id, bot_id, action)

# Клавиатуры - исправлено: убраны HTML-теги из текста кнопок
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Загрузить"),
                KeyboardButton(text="Мои сервера")
            ],
            [
                KeyboardButton(text="Профиль")
            ]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Загрузить"),
                KeyboardButton(text="Мои сервера")
            ],
            [
                KeyboardButton(text="Профиль"),
                KeyboardButton(text="Админ панель")
            ]
        ],
        resize_keyboard=True
    )

def get_tariffs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="7 Дней - 10₽",
            callback_data="tariff_7_10"
        )],
        [InlineKeyboardButton(
            text="21 день - 25₽",
            callback_data="tariff_21_25"
        )],
        [InlineKeyboardButton(
            text="30 дней - 30₽",
            callback_data="tariff_30_30"
        )],
        [InlineKeyboardButton(
            text="Навсегда - 50₽",
            callback_data="tariff_forever_50"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main",
            icon_custom_emoji_id=EMOJI["back"]
        )],
    ])

def get_payment_keyboard(invoice_id: int, invoice_url: str, bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Оплатить",
            url=invoice_url,
            icon_custom_emoji_id=EMOJI["wallet"]
        )],
        [InlineKeyboardButton(
            text="Проверить оплату",
            callback_data=f"check_payment_{invoice_id}_{bot_id}",
            icon_custom_emoji_id=EMOJI["refresh"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_tariffs",
            icon_custom_emoji_id=EMOJI["back"]
        )],
    ])

def get_bot_actions_keyboard(bot_id: int, bot_username: str = "") -> InlineKeyboardMarkup:
    buttons = []
    if bot_username:
        buttons.append([InlineKeyboardButton(
            text="Перейти в бота",
            url=f"https://t.me/{bot_username}",
            icon_custom_emoji_id=EMOJI["link"]
        )])
    buttons.extend([
        [InlineKeyboardButton(
            text="Обновить",
            callback_data=f"action_refresh_{bot_id}",
            icon_custom_emoji_id=EMOJI["refresh"]
        )],
        [InlineKeyboardButton(
            text="Перезагрузить",
            callback_data=f"action_restart_{bot_id}",
            icon_custom_emoji_id=EMOJI["refresh"]
        )],
        [InlineKeyboardButton(
            text="Остановить",
            callback_data=f"action_stop_{bot_id}",
            icon_custom_emoji_id=EMOJI["lock_closed"]
        )],
        [InlineKeyboardButton(
            text="Удалить",
            callback_data=f"action_delete_{bot_id}",
            icon_custom_emoji_id=EMOJI["trash"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_servers",
            icon_custom_emoji_id=EMOJI["back"]
        )],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_approve_keyboard(user_id: int, bot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Я поставил на хостинг",
            callback_data=f"admin_approve_{user_id}_{bot_id}",
            icon_custom_emoji_id=EMOJI["check"]
        )],
        [InlineKeyboardButton(
            text="Отклонить",
            callback_data=f"admin_reject_{user_id}_{bot_id}",
            icon_custom_emoji_id=EMOJI["cross"]
        )],
    ])

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Установить медиа для Загрузить",
            callback_data="admin_media_upload",
            icon_custom_emoji_id=EMOJI["media"]
        )],
        [InlineKeyboardButton(
            text="Установить медиа для Мои сервера",
            callback_data="admin_media_servers",
            icon_custom_emoji_id=EMOJI["media"]
        )],
        [InlineKeyboardButton(
            text="Установить медиа для Профиль",
            callback_data="admin_media_profile",
            icon_custom_emoji_id=EMOJI["media"]
        )],
        [InlineKeyboardButton(
            text="Статистика",
            callback_data="admin_stats",
            icon_custom_emoji_id=EMOJI["stats"]
        )],
    ])

# Состояния FSM
class UploadStates(StatesGroup):
    waiting_for_github = State()
    waiting_for_env = State()
    waiting_for_token = State()
    waiting_for_username = State()
    waiting_for_tariff = State()

class AdminMediaStates(StatesGroup):
    waiting_for_media_upload = State()
    waiting_for_media_servers = State()
    waiting_for_media_profile = State()

# Crypto Bot API функции
async def create_crypto_invoice(amount_rub: float) -> Optional[dict]:
    amount_usdt = amount_rub / USDT_RATE
    async with ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        data = {
            "asset": "USDT",
            "amount": f"{amount_usdt:.2f}",
            "description": "Vest Host - Оплата хостинга бота",
            "allow_comments": False,
            "allow_anonymous": False,
            "expires_in": 3600
        }
        async with session.post(
            "https://pay.crypt.bot/api/createInvoice",
            headers=headers,
            json=data
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get("ok"):
                    return {
                        "invoice_id": result["result"]["invoice_id"],
                        "pay_url": result["result"]["pay_url"],
                        "amount_rub": amount_rub,
                        "amount_usdt": amount_usdt
                    }
    return None

async def check_crypto_invoice(invoice_id: int) -> Optional[str]:
    async with ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        data = {"invoice_id": invoice_id}
        async with session.post(
            "https://pay.crypt.bot/api/getInvoice",
            headers=headers,
            json=data
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get("ok"):
                    return result["result"]["status"]
    return None

# Обработчики команд
@router.message(Command("start"))
async def cmd_start(message: Message):
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    if message.from_user.id in ADMIN_IDS:
        keyboard = get_admin_keyboard()
    else:
        keyboard = get_main_keyboard()
    
    welcome_text = f'''
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji><b>Добро пожаловать в Vest Host!</b>

<tg-emoji emoji-id="{EMOJI['house']}"> </tg-emoji>Здесь вы можете разместить своего Telegram бота на хостинге.

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Выберите действие в меню:
<tg-emoji emoji-id="{EMOJI['download']}"> </tg-emoji><b>Загрузить</b> - добавить нового бота
<tg-emoji emoji-id="{EMOJI['box']}"> </tg-emoji><b>Мои сервера</b> - управление ботами
<tg-emoji emoji-id="{EMOJI['profile']}"> </tg-emoji><b>Профиль</b> - информация о профиле
'''
    await message.answer(welcome_text, reply_markup=keyboard)

@router.message(F.text == "Загрузить")
async def upload_start(message: Message, state: FSMContext):
    await state.clear()
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['download']}"> </tg-emoji><b>Загрузка бота на хостинг</b>

<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>Отправьте ссылку на GitHub репозиторий вашего бота.

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Пример: https://github.com/username/repository
'''
    
    media = await get_admin_media("upload")
    if media:
        await message.answer_photo(
            photo=media,
            caption=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="back_to_main",
                    icon_custom_emoji_id=EMOJI["back"]
                )]
            ])
        )
    else:
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="back_to_main",
                    icon_custom_emoji_id=EMOJI["back"]
                )]
            ])
        )
    
    await state.set_state(UploadStates.waiting_for_github)

@router.message(UploadStates.waiting_for_github)
async def upload_github(message: Message, state: FSMContext):
    github_url = message.text.strip()
    
    if not github_url.startswith("https://github.com/"):
        await message.answer(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}"> </tg-emoji>Некорректная ссылка. Отправьте ссылку на GitHub репозиторий.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="back_to_main",
                    icon_custom_emoji_id=EMOJI["back"]
                )]
            ])
        )
        return
    
    await state.update_data(github_url=github_url)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['code']}"> </tg-emoji><b>Переменные окружения</b>

<tg-emoji emoji-id="{EMOJI['write']}"> </tg-emoji>Отправьте переменные окружения для вашего бота в формате:

KEY1=value1
KEY2=value2

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Или напишите "нет", если переменные не требуются.
'''
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_github",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await state.set_state(UploadStates.waiting_for_env)

@router.message(UploadStates.waiting_for_env)
async def upload_env(message: Message, state: FSMContext):
    env_vars = message.text.strip()
    await state.update_data(env_vars=env_vars if env_vars.lower() != "нет" else "")
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji><b>Токен бота</b>

<tg-emoji emoji-id="{EMOJI['key']}"> </tg-emoji>Отправьте токен вашего Telegram бота.

<tg-emoji emoji-id="{EMOJI['eye_hidden']}"> </tg-emoji>Токен будет храниться в безопасности.
'''
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_env",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await state.set_state(UploadStates.waiting_for_token)

@router.message(UploadStates.waiting_for_token)
async def upload_token(message: Message, state: FSMContext):
    bot_token = message.text.strip()
    await message.delete()
    await state.update_data(bot_token=bot_token)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji><b>Username бота</b>

<tg-emoji emoji-id="{EMOJI['write']}"> </tg-emoji>Отправьте username вашего бота (без @).

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Пример: my_super_bot
'''
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_token",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await state.set_state(UploadStates.waiting_for_username)

@router.message(UploadStates.waiting_for_username)
async def upload_username(message: Message, state: FSMContext):
    bot_username = message.text.strip().replace("@", "")
    await state.update_data(bot_username=bot_username)
    
    data = await state.get_data()
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['tag']}"> </tg-emoji><b>Выберите тариф</b>

<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>GitHub: {data.get('github_url', '')}
<tg-emoji emoji-id="{EMOJI['code']}"> </tg-emoji>Переменные: {data.get('env_vars') or 'нет'}
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Username: @{bot_username}
<tg-emoji emoji-id="{EMOJI['key']}"> </tg-emoji>Токен: {data.get('bot_token', '')[:10]}...

<tg-emoji emoji-id="{EMOJI['calendar']}"> </tg-emoji>Доступные тарифы:
'''
    
    await message.answer(text, reply_markup=get_tariffs_keyboard())
    await state.set_state(UploadStates.waiting_for_tariff)

@router.callback_query(F.data.startswith("tariff_"))
async def tariff_selected(callback: CallbackQuery, state: FSMContext):
    tariff_data = callback.data.split("_")
    period = tariff_data[1]
    price = int(tariff_data[2])
    
    await state.update_data(tariff_period=period, tariff_price=price)
    data = await state.get_data()
    
    await get_or_create_user(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
        callback.from_user.last_name
    )
    
    bot_id = await create_bot(callback.from_user.id, data)
    
    invoice = await create_crypto_invoice(price)
    
    if not invoice:
        await callback.message.answer(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}"> </tg-emoji>Ошибка создания счета. Попробуйте позже.',
            reply_markup=get_main_keyboard() if callback.from_user.id not in ADMIN_IDS else get_admin_keyboard()
        )
        await state.clear()
        await callback.answer()
        return
    
    await create_invoice_record(callback.from_user.id, bot_id, invoice)
    await update_bot_status(bot_id, 'pending', invoice_id=invoice['invoice_id'])
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['wallet']}"> </tg-emoji><b>Оплата тарифа</b>

<tg-emoji emoji-id="{EMOJI['calendar']}"> </tg-emoji>Тариф: {period} - {price}₽
<tg-emoji emoji-id="{EMOJI['crypto_bot']}"> </tg-emoji>Счет создан через Crypto Bot

<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>Нажмите кнопку ниже для оплаты.
'''
    
    await callback.message.edit_text(
        text,
        reply_markup=get_payment_keyboard(invoice['invoice_id'], invoice['pay_url'], bot_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    invoice_id = int(parts[2])
    bot_id = int(parts[3])
    
    status = await check_crypto_invoice(invoice_id)
    
    if status == "paid":
        await update_invoice_status(invoice_id, 'paid')
        
        bot_info = await get_bot_by_id(bot_id)
        
        if bot_info:
            await update_bot_status(bot_id, 'paid', paid_at=datetime.now())
            
            admin_text = f'''
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji><b>Новая оплата!</b>

<tg-emoji emoji-id="{EMOJI['profile']}"> </tg-emoji>Пользователь: @{callback.from_user.username or "нет"} (ID: {callback.from_user.id})
<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>GitHub: {bot_info['github_url']}
<tg-emoji emoji-id="{EMOJI['code']}"> </tg-emoji>Переменные: {bot_info['env_vars'] or 'нет'}
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Username: @{bot_info['bot_username']}
<tg-emoji emoji-id="{EMOJI['key']}"> </tg-emoji>Токен: {bot_info['bot_token']}
<tg-emoji emoji-id="{EMOJI['calendar']}"> </tg-emoji>Тариф: {bot_info['tariff_period']} - {bot_info['tariff_price']}₽
<tg-emoji emoji-id="{EMOJI['money']}"> </tg-emoji>Оплачено!
'''
            
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    admin_text,
                    reply_markup=get_admin_approve_keyboard(callback.from_user.id, bot_id)
                )
            
            text = f'''
<tg-emoji emoji-id="{EMOJI['check']}"> </tg-emoji><b>Оплата успешна!</b>

<tg-emoji emoji-id="{EMOJI['clock']}"> </tg-emoji>Бот будет поставлен на хостинг в течение 24 часов!

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>После одобрения администратором вы получите уведомление.
'''
            await callback.message.edit_text(text)
            
        await callback.answer("Оплата подтверждена!", show_alert=True)
    else:
        await callback.answer("Оплата еще не поступила", show_alert=True)

@router.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    parts = callback.data.split("_")
    user_id = int(parts[2])
    bot_id = int(parts[3])
    
    await update_bot_status(bot_id, 'approved', approved_at=datetime.now(), approved_by=callback.from_user.id)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['check']}"> </tg-emoji><b>Бот успешно поставлен на хостинг!</b>

<tg-emoji emoji-id="{EMOJI['celebration']}"> </tg-emoji>Ваш бот теперь активен и работает.
<tg-emoji emoji-id="{EMOJI['box']}"> </tg-emoji>Управлять ботом можно в разделе "Мои сервера".
'''
    
    await bot.send_message(user_id, text)
    
    await callback.message.edit_text(
        callback.message.text + f"\n\n<tg-emoji emoji-id=\"{EMOJI['check']}\"> </tg-emoji><b>Подтверждено!</b>"
    )
    await callback.answer("Подтверждено!")

@router.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    parts = callback.data.split("_")
    user_id = int(parts[2])
    bot_id = int(parts[3])
    
    await update_bot_status(bot_id, 'rejected')
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['cross']}"> </tg-emoji><b>Заявка отклонена</b>

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Свяжитесь с администратором для уточнения деталей.
'''
    
    await bot.send_message(user_id, text)
    
    await callback.message.edit_text(
        callback.message.text + f"\n\n<tg-emoji emoji-id=\"{EMOJI['cross']}\"> </tg-emoji><b>Отклонено!</b>"
    )
    await callback.answer("Отклонено!")

@router.message(F.text == "Мои сервера")
async def my_servers(message: Message):
    user_id = message.from_user.id
    bots = await get_user_bots(user_id)
    
    if not bots:
        text = f'''
<tg-emoji emoji-id="{EMOJI['box']}"> </tg-emoji><b>Мои сервера</b>

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>У вас пока нет активных ботов.

<tg-emoji emoji-id="{EMOJI['download']}"> </tg-emoji>Нажмите "Загрузить" чтобы добавить бота.
'''
        media = await get_admin_media("servers")
        if media:
            await message.answer_photo(photo=media, caption=text)
        else:
            await message.answer(text)
        return
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['box']}"> </tg-emoji><b>Мои сервера</b>

<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Ваши боты:
'''
    
    keyboard_buttons = []
    for bot_info in bots:
        status_text = "Активен" if bot_info.get("approved_at") else "Ожидает"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"Бот @{bot_info['bot_username']} - {status_text}",
                callback_data=f"select_bot_{bot_info['id']}"
            )
        ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main",
            icon_custom_emoji_id=EMOJI["back"]
        )
    ])
    
    media = await get_admin_media("servers")
    if media:
        await message.answer_photo(
            photo=media,
            caption=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        )
    else:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons))

@router.callback_query(F.data.startswith("select_bot_"))
async def select_bot(callback: CallbackQuery):
    bot_id = int(callback.data.split("_")[2])
    
    bot_info = await get_bot_by_id(bot_id)
    
    if not bot_info:
        await callback.answer("Бот не найден", show_alert=True)
        return
    
    status_text = "Активен" if bot_info.get("approved_at") else "Ожидает одобрения"
    status_emoji = EMOJI["check"] if bot_info.get("approved_at") else EMOJI["clock"]
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji><b>Бот @{bot_info['bot_username']}</b>

<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>GitHub: {bot_info['github_url']}
<tg-emoji emoji-id="{EMOJI['calendar']}"> </tg-emoji>Тариф: {bot_info['tariff_period']} - {bot_info['tariff_price']}₽
<tg-emoji emoji-id="{status_emoji}"> </tg-emoji>Статус: {status_text}
<tg-emoji emoji-id="{EMOJI['clock']}"> </tg-emoji>Создан: {bot_info['created_at'].strftime('%d.%m.%Y')}

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Выберите действие:
'''
    
    await callback.message.edit_text(
        text,
        reply_markup=get_bot_actions_keyboard(bot_id, bot_info['bot_username'])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("action_"))
async def bot_action(callback: CallbackQuery):
    action_parts = callback.data.split("_")
    action = action_parts[1]
    bot_id = int(action_parts[2])
    user_id = callback.from_user.id
    
    action_names = {
        "refresh": "Обновить",
        "restart": "Перезагрузить",
        "stop": "Остановить",
        "delete": "Удалить"
    }
    
    action_name = action_names.get(action, action)
    
    await create_action_log(user_id, bot_id, action)
    
    bot_info = await get_bot_by_id(bot_id)
    
    admin_text = f'''
<tg-emoji emoji-id="{EMOJI['gear']}"> </tg-emoji><b>Запрос действия</b>

<tg-emoji emoji-id="{EMOJI['profile']}"> </tg-emoji>Пользователь: @{callback.from_user.username or "нет"} (ID: {user_id})
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Бот: @{bot_info['bot_username']} (ID: {bot_id})
<tg-emoji emoji-id="{EMOJI['write']}"> </tg-emoji>Действие: {action_name}
'''
    
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, admin_text)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['clock']}"> </tg-emoji><b>Запрос отправлен</b>

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Действие "{action_name}" скоро будет совершено.
<tg-emoji emoji-id="{EMOJI['time_past']}"> </tg-emoji>Ожидайте до 2 часов.
'''
    
    await callback.message.edit_text(text)
    await callback.answer("Запрос отправлен администратору")

@router.message(F.text == "Профиль")
async def profile(message: Message):
    user_id = message.from_user.id
    
    await get_or_create_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    bots = await get_user_bots(user_id)
    bots_count = len(bots)
    active_bots = len([b for b in bots if b.get("approved_at")])
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['profile']}"> </tg-emoji><b>Ваш профиль</b>

<tg-emoji emoji-id="{EMOJI['person_check']}"> </tg-emoji>ID: {user_id}
<tg-emoji emoji-id="{EMOJI['people']}"> </tg-emoji>Username: @{message.from_user.username or "не указан"}
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Всего ботов: {bots_count}
<tg-emoji emoji-id="{EMOJI['check']}"> </tg-emoji>Активных: {active_bots}
'''
    
    media = await get_admin_media("profile")
    if media:
        await message.answer_photo(photo=media, caption=text)
    else:
        await message.answer(text)

@router.message(F.text == "Админ панель")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}"> </tg-emoji>У вас нет доступа к админ панели.'
        )
        return
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["gear"]}"> </tg-emoji><b>Админ панель</b>

<tg-emoji emoji-id="{EMOJI["info"]}"> </tg-emoji>Выберите действие:
'''
    
    await message.answer(text, reply_markup=get_admin_panel_keyboard())

@router.callback_query(F.data == "admin_media_upload")
async def admin_media_upload(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["media"]}"> </tg-emoji><b>Установка медиа для "Загрузить"</b>

<tg-emoji emoji-id="{EMOJI["send"]}"> </tg-emoji>Отправьте фото, которое будет показываться в разделе "Загрузить".
'''
    
    await callback.message.edit_text(text)
    await state.set_state(AdminMediaStates.waiting_for_media_upload)
    await callback.answer()

@router.message(AdminMediaStates.waiting_for_media_upload, F.photo)
async def admin_media_upload_received(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    file_id = message.photo[-1].file_id
    await set_admin_media("upload", file_id)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["check"]}"> </tg-emoji><b>Медиа установлено!</b>

<tg-emoji emoji-id="{EMOJI["media"]}"> </tg-emoji>Фото для раздела "Загрузить" сохранено в базе данных.
'''
    
    await message.answer(text)
    await state.clear()

@router.callback_query(F.data == "admin_media_servers")
async def admin_media_servers(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["media"]}"> </tg-emoji><b>Установка медиа для "Мои сервера"</b>

<tg-emoji emoji-id="{EMOJI["send"]}"> </tg-emoji>Отправьте фото, которое будет показываться в разделе "Мои сервера".
'''
    
    await callback.message.edit_text(text)
    await state.set_state(AdminMediaStates.waiting_for_media_servers)
    await callback.answer()

@router.message(AdminMediaStates.waiting_for_media_servers, F.photo)
async def admin_media_servers_received(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    file_id = message.photo[-1].file_id
    await set_admin_media("servers", file_id)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["check"]}"> </tg-emoji><b>Медиа установлено!</b>

<tg-emoji emoji-id="{EMOJI["media"]}"> </tg-emoji>Фото для раздела "Мои сервера" сохранено в базе данных.
'''
    
    await message.answer(text)
    await state.clear()

@router.callback_query(F.data == "admin_media_profile")
async def admin_media_profile(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["media"]}"> </tg-emoji><b>Установка медиа для "Профиль"</b>

<tg-emoji emoji-id="{EMOJI["send"]}"> </tg-emoji>Отправьте фото, которое будет показываться в разделе "Профиль".
'''
    
    await callback.message.edit_text(text)
    await state.set_state(AdminMediaStates.waiting_for_media_profile)
    await callback.answer()

@router.message(AdminMediaStates.waiting_for_media_profile, F.photo)
async def admin_media_profile_received(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    file_id = message.photo[-1].file_id
    await set_admin_media("profile", file_id)
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["check"]}"> </tg-emoji><b>Медиа установлено!</b>

<tg-emoji emoji-id="{EMOJI["media"]}"> </tg-emoji>Фото для раздела "Профиль" сохранено в базе данных.
'''
    
    await message.answer(text)
    await state.clear()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    stats = await get_stats()
    
    text = f'''
<tg-emoji emoji-id="{EMOJI["stats"]}"> </tg-emoji><b>Статистика</b>

<tg-emoji emoji-id="{EMOJI["people"]}"> </tg-emoji>Всего пользователей: {stats['total_users']}
<tg-emoji emoji-id="{EMOJI["bot"]}"> </tg-emoji>Активных ботов: {stats['total_bots']}
<tg-emoji emoji-id="{EMOJI["clock"]}"> </tg-emoji>Ожидают: {stats['pending_bots']}
<tg-emoji emoji-id="{EMOJI["money"]}"> </tg-emoji>Общая выручка: {stats['total_revenue']}₽
'''
    
    await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['house']}"> </tg-emoji><b>Главное меню</b>

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>Выберите действие:
'''
    
    keyboard = get_admin_keyboard() if callback.from_user.id in ADMIN_IDS else get_main_keyboard()
    
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "back_to_github")
async def back_to_github(callback: CallbackQuery, state: FSMContext):
    text = f'''
<tg-emoji emoji-id="{EMOJI['download']}"> </tg-emoji><b>Загрузка бота на хостинг</b>

<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>Отправьте ссылку на GitHub репозиторий вашего бота.
'''
    
    await callback.message.edit_text(text)
    await state.set_state(UploadStates.waiting_for_github)
    await callback.answer()

@router.callback_query(F.data == "back_to_env")
async def back_to_env(callback: CallbackQuery, state: FSMContext):
    text = f'''
<tg-emoji emoji-id="{EMOJI['code']}"> </tg-emoji><b>Переменные окружения</b>

<tg-emoji emoji-id="{EMOJI['write']}"> </tg-emoji>Отправьте переменные окружения или "нет".
'''
    
    await callback.message.edit_text(text)
    await state.set_state(UploadStates.waiting_for_env)
    await callback.answer()

@router.callback_query(F.data == "back_to_token")
async def back_to_token(callback: CallbackQuery, state: FSMContext):
    text = f'''
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji><b>Токен бота</b>

<tg-emoji emoji-id="{EMOJI['key']}"> </tg-emoji>Отправьте токен вашего Telegram бота.
'''
    
    await callback.message.edit_text(text)
    await state.set_state(UploadStates.waiting_for_token)
    await callback.answer()

@router.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['tag']}"> </tg-emoji><b>Выберите тариф</b>

<tg-emoji emoji-id="{EMOJI['link']}"> </tg-emoji>GitHub: {data.get('github_url', '')}
<tg-emoji emoji-id="{EMOJI['code']}"> </tg-emoji>Переменные: {data.get('env_vars') or 'нет'}
<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Username: @{data.get('bot_username', '')}
<tg-emoji emoji-id="{EMOJI['key']}"> </tg-emoji>Токен: {data.get('bot_token', '')[:10]}...

<tg-emoji emoji-id="{EMOJI['calendar']}"> </tg-emoji>Доступные тарифы:
'''
    
    await callback.message.edit_text(text, reply_markup=get_tariffs_keyboard())
    await state.set_state(UploadStates.waiting_for_tariff)
    await callback.answer()

@router.callback_query(F.data == "back_to_servers")
async def back_to_servers(callback: CallbackQuery):
    user_id = callback.from_user.id
    bots = await get_user_bots(user_id)
    
    if not bots:
        text = f'''
<tg-emoji emoji-id="{EMOJI['box']}"> </tg-emoji><b>Мои сервера</b>

<tg-emoji emoji-id="{EMOJI['info']}"> </tg-emoji>У вас пока нет активных ботов.
'''
        await callback.message.edit_text(text)
        await callback.answer()
        return
    
    text = f'''
<tg-emoji emoji-id="{EMOJI['box']}"> </tg-emoji><b>Мои сервера</b>

<tg-emoji emoji-id="{EMOJI['bot']}"> </tg-emoji>Ваши боты:
'''
    
    keyboard_buttons = []
    for bot_info in bots:
        status_text = "Активен" if bot_info.get("approved_at") else "Ожидает"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"Бот @{bot_info['bot_username']} - {status_text}",
                callback_data=f"select_bot_{bot_info['id']}"
            )
        ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main",
            icon_custom_emoji_id=EMOJI["back"]
        )
    ])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    )
    await callback.answer()

# Запуск бота
async def main():
    await init_db()
    logger.info("База данных PostgreSQL подключена!")
    logger.info("Бот Vest Host запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        if db_pool:
            await db_pool.close()
            logger.info("Соединение с БД закрыто")

if __name__ == "__main__":
    asyncio.run(main())
