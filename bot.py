import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import asyncpg
from aiohttp import ClientSession
import os

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7973988177
ADMIN_IDS = [ADMIN_ID]
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

USDT_RATE = 90

TARIFFS = {
    "7_days": {"name": "7 Дней", "price": 10, "days": 7},
    "21_days": {"name": "21 день", "price": 25, "days": 21},
    "30_days": {"name": "30 дней", "price": 30, "days": 30},
    "forever": {"name": "Навсегда", "price": 50, "days": 36500},
}

EMOJI = {
    "gear": "5870982283724328568",
    "profile": "5870994129244131212",
    "people": "5870772616305839506",
    "check_person": "5891207662678317861",
    "cross_person": "5893192487324880883",
    "file": "5870528606328852614",
    "smile": "5870764288364252592",
    "graph": "5870930636742595124",
    "stats": "5870921681735781843",
    "home": "5873147866364514353",
    "lock": "6037249452824072506",
    "unlock": "6037496202990194718",
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
    "hidden": "6037243349675544634",
    "send": "5963103826075456248",
    "download": "6039802767931871481",
    "bell": "6039486778597970865",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
    "hooray": "6041731551845159060",
    "font": "5870801517140775623",
    "write": "5870753782874246579",
    "media": "6035128606563241721",
    "geo": "6042011682497106307",
    "wallet": "5769126056262898415",
    "box": "5884479287171485878",
    "cryptobot": "5260752406890711732",
    "calendar": "5890937706803894250",
    "tag": "5886285355279193209",
    "past": "5775896410780079073",
    "apps": "5778672437122045013",
    "brush": "6050679691004612757",
    "add_text": "5771851822897566479",
    "format": "5778479949572738874",
    "money": "5904462880941545555",
    "send_money": "5890848474563352982",
    "receive_money": "5879814368572478751",
    "code": "5940433880585605708",
    "loading": "5345906554510012647",
    "back": "◁",
    "upload": "5345906554510012647",
    "servers": "6030400221232501136",
}

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db_pool: Optional[asyncpg.Pool] = None

class UploadStates(StatesGroup):
    waiting_github = State()
    waiting_env = State()
    waiting_bot_token = State()
    waiting_tariff = State()

class AdminMediaStates(StatesGroup):
    waiting_media_for = State()
    waiting_media_file = State()

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                github_url TEXT NOT NULL,
                env_vars TEXT,
                bot_token TEXT NOT NULL,
                tariff TEXT NOT NULL,
                price INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,
                crypto_invoice_id TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS media_settings (
                section TEXT PRIMARY KEY,
                media_type TEXT,
                file_id TEXT,
                caption TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id BIGINT,
                server_data TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        sections = ['upload', 'my_servers', 'profile']
        for s in sections:
            await conn.execute("""
                INSERT INTO media_settings (section) VALUES ($1) ON CONFLICT (section) DO NOTHING
            """, s)

async def get_user(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

async def create_user(user_id: int, username: str, full_name: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name) VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET username = $2, full_name = $3
        """, user_id, username, full_name)

async def get_servers(user_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT * FROM servers WHERE user_id = $1 AND status IN ('pending', 'active')
            ORDER BY created_at DESC
        """, user_id)

async def get_server(server_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM servers WHERE id = $1", server_id)

async def create_server(user_id: int, github_url: str, env_vars: str, bot_token: str, tariff: str, price: int, expires_at: datetime):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO servers (user_id, github_url, env_vars, bot_token, tariff, price, expires_at, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
            RETURNING id
        """, user_id, github_url, env_vars, bot_token, tariff, price, expires_at)

async def update_server_status(server_id: int, status: str):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE servers SET status = $1 WHERE id = $2", status, server_id)

async def save_crypto_invoice(invoice_id: str, user_id: int, server_data: dict):
    async with db_pool.acquire() as conn:
        import json
        await conn.execute("""
            INSERT INTO payment_invoices (invoice_id, user_id, server_data)
            VALUES ($1, $2, $3)
        """, invoice_id, user_id, json.dumps(server_data))

async def get_invoice(invoice_id: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM payment_invoices WHERE invoice_id = $1", invoice_id)

async def update_invoice_status(invoice_id: str, status: str):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE payment_invoices SET status = $1 WHERE invoice_id = $2", status, invoice_id)

async def get_media_settings(section: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM media_settings WHERE section = $1", section)

async def update_media_settings(section: str, media_type: str, file_id: str, caption: str = None):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE media_settings SET media_type = $1, file_id = $2, caption = $3
            WHERE section = $4
        """, media_type, file_id, caption, section)

def em(text: str) -> str:
    return f'<tg-emoji emoji-id="{text}"> </tg-emoji>'

def main_menu_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=f"{em(EMOJI['upload'])} Загрузить"),
        KeyboardButton(text=f"{em(EMOJI['servers'])} Мои сервера")
    )
    builder.row(
        KeyboardButton(text=f"{em(EMOJI['profile'])} Профиль")
    )
    return builder.as_markup(resize_keyboard=True)

def back_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=f"◁ Назад"))
    return builder.as_markup(resize_keyboard=True)

def tariff_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="7 Дней - 10₽",
            callback_data="tariff_7_days",
            icon_custom_emoji_id=EMOJI['money']
        )],
        [InlineKeyboardButton(
            text="21 день - 25₽",
            callback_data="tariff_21_days",
            icon_custom_emoji_id=EMOJI['calendar']
        )],
        [InlineKeyboardButton(
            text="30 дней - 30₽",
            callback_data="tariff_30_days",
            icon_custom_emoji_id=EMOJI['gift']
        )],
        [InlineKeyboardButton(
            text="Навсегда - 50₽",
            callback_data="tariff_forever",
            icon_custom_emoji_id=EMOJI['hooray']
        )],
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_upload",
            icon_custom_emoji_id=EMOJI['cross']
        )],
    ])

def server_actions_keyboard(server_id: int, bot_username: str = None):
    buttons = [
        [InlineKeyboardButton(
            text="Перейти в бота",
            url=f"https://t.me/{bot_username}" if bot_username else "https://t.me/",
            icon_custom_emoji_id=EMOJI['bot']
        )],
        [InlineKeyboardButton(
            text="Обновить",
            callback_data=f"server_update_{server_id}",
            icon_custom_emoji_id=EMOJI['loading']
        )],
        [InlineKeyboardButton(
            text="Перезагрузить",
            callback_data=f"server_restart_{server_id}",
            icon_custom_emoji_id=EMOJI['loading']
        )],
        [InlineKeyboardButton(
            text="Остановить",
            callback_data=f"server_stop_{server_id}",
            icon_custom_emoji_id=EMOJI['cross']
        )],
        [InlineKeyboardButton(
            text="Удалить",
            callback_data=f"server_delete_{server_id}",
            icon_custom_emoji_id=EMOJI['trash']
        )],
        [InlineKeyboardButton(
            text="◁ Назад к списку",
            callback_data="back_to_servers",
            icon_custom_emoji_id=EMOJI['back']
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_approve_keyboard(server_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Я поставил на хостинг",
            callback_data=f"admin_approve_{server_id}",
            icon_custom_emoji_id=EMOJI['check']
        )],
    ])

def admin_menu_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=f"{em(EMOJI['media'])} Медиа"))
    builder.row(KeyboardButton(text=f"{em(EMOJI['stats'])} Статистика"))
    builder.row(KeyboardButton(text=f"◁ Назад"))
    return builder.as_markup(resize_keyboard=True)

def admin_media_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Загрузить",
            callback_data="set_media_upload",
            icon_custom_emoji_id=EMOJI['upload']
        )],
        [InlineKeyboardButton(
            text="Мои сервера",
            callback_data="set_media_my_servers",
            icon_custom_emoji_id=EMOJI['servers']
        )],
        [InlineKeyboardButton(
            text="Профиль",
            callback_data="set_media_profile",
            icon_custom_emoji_id=EMOJI['profile']
        )],
        [InlineKeyboardButton(
            text="Закрыть",
            callback_data="close_admin_media",
            icon_custom_emoji_id=EMOJI['cross']
        )],
    ])

async def create_crypto_invoice(amount_rub: int) -> Optional[dict]:
    amount_usdt = amount_rub / USDT_RATE
    async with ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        data = {
            "asset": "USDT",
            "amount": str(amount_usdt),
            "description": "Vest Host - Хостинг бота",
            "paid_btn_name": "callback",
            "paid_btn_url": "https://t.me/VestHostBot",
            "expires_in": 3600
        }
        async with session.post("https://pay.crypt.bot/api/createInvoice", json=data, headers=headers) as resp:
            result = await resp.json()
            if result.get("ok"):
                return result["result"]
            return None

async def check_crypto_invoice(invoice_id: int) -> Optional[str]:
    async with ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        async with session.get(f"https://pay.crypt.bot/api/getInvoice", params={"invoice_id": invoice_id}, headers=headers) as resp:
            result = await resp.json()
            if result.get("ok"):
                return result["result"]["status"]
            return None

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            f"{em(EMOJI['smile'])} Добро пожаловать в <b>Vest Host</b>!\n\n"
            f"{em(EMOJI['info'])} Вы вошли как <b>администратор</b>.",
            reply_markup=admin_menu_keyboard()
        )
    else:
        await message.answer(
            f"{em(EMOJI['smile'])} Добро пожаловать в <b>Vest Host</b>!\n\n"
            f"{em(EMOJI['upload'])} Загрузите своего бота и мы разместим его на хостинге.\n"
            f"{em(EMOJI['clock'])} Хостинг активируется в течение 24 часов после оплаты.",
            reply_markup=main_menu_keyboard()
        )

@dp.message(F.text == "◁ Назад")
async def back_to_main(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("Главное меню:", reply_markup=admin_menu_keyboard())
    else:
        await message.answer("Главное меню:", reply_markup=main_menu_keyboard())

@dp.message(F.text == "◁ Отмена")
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu_keyboard())

@dp.message(F.text.contains("Загрузить"))
async def upload_start(message: Message, state: FSMContext):
    media = await get_media_settings("upload")
    if media and media["file_id"]:
        if media["media_type"] == "photo":
            await message.answer_photo(
                media["file_id"],
                caption=media["caption"] or f"{em(EMOJI['link'])} Отправьте ссылку на GitHub репозиторий:",
                reply_markup=back_keyboard()
            )
        else:
            await message.answer(media["caption"] or f"{em(EMOJI['link'])} Отправьте ссылку на GitHub репозиторий:", reply_markup=back_keyboard())
    else:
        await message.answer(
            f"{em(EMOJI['link'])} Отправьте ссылку на <b>GitHub репозиторий</b> вашего бота:",
            reply_markup=back_keyboard()
        )
    await state.set_state(UploadStates.waiting_github)

@dp.message(UploadStates.waiting_github)
async def upload_github(message: Message, state: FSMContext):
    if message.text == "◁ Назад":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_keyboard())
        return

    await state.update_data(github_url=message.text)
    await message.answer(
        f"{em(EMOJI['code'])} Отправьте <b>переменные окружения</b> (env) в формате:\n"
        f"<code>KEY1=value1\nKEY2=value2</code>\n\n"
        f"{em(EMOJI['info'])} Или напишите 'нет', если переменные не нужны.",
        reply_markup=back_keyboard()
    )
    await state.set_state(UploadStates.waiting_env)

@dp.message(UploadStates.waiting_env)
async def upload_env(message: Message, state: FSMContext):
    if message.text == "◁ Назад":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_keyboard())
        return

    env_vars = message.text if message.text.lower() != "нет" else ""
    await state.update_data(env_vars=env_vars)
    await message.answer(
        f"{em(EMOJI['key'])} Отправьте <b>токен вашего бота</b>:",
        reply_markup=back_keyboard()
    )
    await state.set_state(UploadStates.waiting_bot_token)

@dp.message(UploadStates.waiting_bot_token)
async def upload_bot_token(message: Message, state: FSMContext):
    if message.text == "◁ Назад":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_keyboard())
        return

    await state.update_data(bot_token=message.text)
    await message.answer(
        f"{em(EMOJI['money'])} Выберите <b>тариф</b>:",
        reply_markup=tariff_keyboard()
    )
    await state.set_state(UploadStates.waiting_tariff)

@dp.callback_query(F.data == "cancel_upload")
async def cancel_upload_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Загрузка отменена.", reply_markup=main_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("tariff_"), UploadStates.waiting_tariff)
async def select_tariff(callback: CallbackQuery, state: FSMContext):
    tariff_key = callback.data.replace("tariff_", "")
    tariff = TARIFFS[tariff_key]

    data = await state.get_data()
    await state.clear()

    expires_at = datetime.now() + timedelta(days=tariff["days"])

    server_id = await create_server(
        callback.from_user.id,
        data["github_url"],
        data["env_vars"],
        data["bot_token"],
        tariff["name"],
        tariff["price"],
        expires_at
    )

    invoice = await create_crypto_invoice(tariff["price"])

    if not invoice:
        await callback.message.edit_text(
            f"{em(EMOJI['cross'])} Ошибка создания счета. Попробуйте позже."
        )
        await callback.answer()
        return

    await save_crypto_invoice(str(invoice["invoice_id"]), callback.from_user.id, {
        "server_id": server_id,
        "user_id": callback.from_user.id
    })

    pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Оплатить {tariff['price']}₽",
            url=invoice["pay_url"],
            icon_custom_emoji_id=EMOJI['wallet']
        )],
        [InlineKeyboardButton(
            text="Проверить оплату",
            callback_data=f"check_payment_{invoice['invoice_id']}",
            icon_custom_emoji_id=EMOJI['loading']
        )],
    ])

    await callback.message.edit_text(
        f"{em(EMOJI['wallet'])} <b>Счет на оплату</b>\n\n"
        f"{em(EMOJI['tag'])} Тариф: {tariff['name']}\n"
        f"{em(EMOJI['money'])} Сумма: {tariff['price']}₽\n\n"
        f"{em(EMOJI['info'])} Нажмите кнопку ниже для оплаты через Crypto Bot.",
        reply_markup=pay_keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    invoice_id = callback.data.replace("check_payment_", "")
    status = await check_crypto_invoice(int(invoice_id))

    if status == "paid":
        invoice_data = await get_invoice(invoice_id)
        if invoice_data and invoice_data["status"] != "paid":
            await update_invoice_status(invoice_id, "paid")
            import json
            data = json.loads(invoice_data["server_data"])
            server = await get_server(data["server_id"])

            await update_server_status(data["server_id"], "pending_payment_done")

            await callback.message.edit_text(
                f"{em(EMOJI['check'])} <b>Оплата успешна!</b>\n\n"
                f"{em(EMOJI['clock'])} Бот будет поставлен на хостинг в течение 24 часов!"
            )

            admin_text = (
                f"{em(EMOJI['bot'])} <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
                f"{em(EMOJI['profile'])} Пользователь: @{callback.from_user.username or 'Нет'} (ID: {callback.from_user.id})\n"
                f"{em(EMOJI['link'])} GitHub: {server['github_url']}\n"
                f"{em(EMOJI['code'])} ENV: {server['env_vars'] or 'Нет'}\n"
                f"{em(EMOJI['key'])} Токен: <code>{server['bot_token']}</code>\n"
                f"{em(EMOJI['tag'])} Тариф: {server['tariff']}\n"
                f"{em(EMOJI['money'])} Цена: {server['price']}₽"
            )
            await bot.send_message(
                ADMIN_ID,
                admin_text,
                reply_markup=admin_approve_keyboard(server['id'])
            )
        else:
            await callback.answer("Оплата уже обработана!")
    elif status == "active":
        await callback.answer("Счет активен, ожидайте оплату", show_alert=True)
    else:
        await callback.answer("Оплата еще не получена", show_alert=True)

@dp.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return

    server_id = int(callback.data.replace("admin_approve_", ""))
    server = await get_server(server_id)

    await update_server_status(server_id, "active")

    await callback.message.edit_text(
        callback.message.text + f"\n\n{em(EMOJI['check'])} <b>Статус: Установлен на хостинг</b>"
    )

    try:
        await bot.send_message(
            server["user_id"],
            f"{em(EMOJI['check'])} <b>Бот успешно поставлен на хостинг!</b>\n\n"
            f"{em(EMOJI['bot'])} Ваш бот теперь активен и работает!"
        )
    except:
        pass

    await callback.answer("Подтверждено!")

@dp.message(F.text.contains("Мои сервера"))
async def my_servers(message: Message):
    media = await get_media_settings("my_servers")
    servers = await get_servers(message.from_user.id)

    if not servers:
        text = f"{em(EMOJI['info'])} У вас пока нет активных серверов.\n{em(EMOJI['upload'])} Используйте 'Загрузить' чтобы добавить бота."
        if media and media["file_id"] and media["media_type"] == "photo":
            await message.answer_photo(media["file_id"], caption=text)
        else:
            await message.answer(text)
        return

    for server in servers:
        status_emoji = EMOJI['check'] if server["status"] == "active" else EMOJI['clock']
        status_text = "Активен" if server["status"] == "active" else "Ожидает"

        text = (
            f"{em(EMOJI['bot'])} <b>Бот #{server['id']}</b>\n"
            f"{em(EMOJI['tag'])} Тариф: {server['tariff']}\n"
            f"{em(status_emoji)} Статус: {status_text}\n"
            f"{em(EMOJI['calendar'])} Истекает: {server['expires_at'].strftime('%d.%m.%Y') if server['expires_at'] else 'Н/Д'}"
        )

        if server["status"] == "active":
            bot_username = None
            try:
                bot_info = await Bot(token=server["bot_token"]).get_me()
                bot_username = bot_info.username
            except:
                pass

            if media and media["file_id"] and media["media_type"] == "photo":
                await message.answer_photo(
                    media["file_id"],
                    caption=text,
                    reply_markup=server_actions_keyboard(server["id"], bot_username)
                )
            else:
                await message.answer(
                    text,
                    reply_markup=server_actions_keyboard(server["id"], bot_username)
                )
        else:
            await message.answer(text)

@dp.callback_query(F.data == "back_to_servers")
async def back_to_servers(callback: CallbackQuery):
    await callback.message.delete()
    servers = await get_servers(callback.from_user.id)

    if not servers:
        await callback.message.answer(f"{em(EMOJI['info'])} У вас пока нет активных серверов.")
        await callback.answer()
        return

    for server in servers:
        status_emoji = EMOJI['check'] if server["status"] == "active" else EMOJI['clock']
        status_text = "Активен" if server["status"] == "active" else "Ожидает"

        text = (
            f"{em(EMOJI['bot'])} <b>Бот #{server['id']}</b>\n"
            f"{em(EMOJI['tag'])} Тариф: {server['tariff']}\n"
            f"{em(status_emoji)} Статус: {status_text}\n"
            f"{em(EMOJI['calendar'])} Истекает: {server['expires_at'].strftime('%d.%m.%Y') if server['expires_at'] else 'Н/Д'}"
        )

        if server["status"] == "active":
            bot_username = None
            try:
                bot_info = await Bot(token=server["bot_token"]).get_me()
                bot_username = bot_info.username
            except:
                pass
            await callback.message.answer(text, reply_markup=server_actions_keyboard(server["id"], bot_username))
        else:
            await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data.startswith("server_update_"))
@dp.callback_query(F.data.startswith("server_restart_"))
@dp.callback_query(F.data.startswith("server_stop_"))
@dp.callback_query(F.data.startswith("server_delete_"))
async def server_action(callback: CallbackQuery):
    action_map = {
        "update": "Обновить",
        "restart": "Перезагрузить",
        "stop": "Остановить",
        "delete": "Удалить"
    }

    parts = callback.data.split("_")
    action = parts[1]
    server_id = int(parts[2])

    server = await get_server(server_id)

    action_text = action_map.get(action, action)

    await bot.send_message(
        ADMIN_ID,
        f"{em(EMOJI['bell'])} <b>Запрос на действие</b>\n\n"
        f"{em(EMOJI['profile'])} Пользователь: @{callback.from_user.username} (ID: {callback.from_user.id})\n"
        f"{em(EMOJI['bot'])} Бот #{server_id}\n"
        f"{em(EMOJI['gear'])} Действие: <b>{action_text}</b>"
    )

    await callback.message.edit_text(
        f"{em(EMOJI['clock'])} Действие '{action_text}' скоро будет совершено.\n"
        f"Ожидайте до 2 часов.",
        reply_markup=None
    )
    await callback.answer("Запрос отправлен администратору")

@dp.message(F.text.contains("Профиль"))
async def profile(message: Message):
    media = await get_media_settings("profile")
    user = await get_user(message.from_user.id)
    servers = await get_servers(message.from_user.id)

    active_count = sum(1 for s in servers if s["status"] == "active")
    pending_count = sum(1 for s in servers if s["status"] == "pending")

    text = (
        f"{em(EMOJI['profile'])} <b>Профиль</b>\n\n"
        f"{em(EMOJI['people'])} ID: <code>{message.from_user.id}</code>\n"
        f"{em(EMOJI['write'])} Имя: {message.from_user.full_name}\n"
        f"{em(EMOJI['link'])} Username: @{message.from_user.username or 'Не указан'}\n\n"
        f"{em(EMOJI['stats'])} <b>Статистика:</b>\n"
        f"{em(EMOJI['bot'])} Активных ботов: {active_count}\n"
        f"{em(EMOJI['clock'])} В ожидании: {pending_count}\n"
        f"{em(EMOJI['calendar'])} На сайте с: {user['registered_at'].strftime('%d.%m.%Y') if user else datetime.now().strftime('%d.%m.%Y')}"
    )

    if media and media["file_id"]:
        if media["media_type"] == "photo":
            await message.answer_photo(media["file_id"], caption=text)
        else:
            await message.answer(text)
    else:
        await message.answer(text)

@dp.message(F.text.contains("Медиа"))
async def admin_media(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        f"{em(EMOJI['media'])} Выберите раздел для установки медиа:",
        reply_markup=admin_media_keyboard()
    )

@dp.callback_query(F.data.startswith("set_media_"))
async def set_media_section(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return

    section = callback.data.replace("set_media_", "")
    section_names = {"upload": "Загрузить", "my_servers": "Мои сервера", "profile": "Профиль"}

    await state.update_data(media_section=section)
    await callback.message.edit_text(
        f"{em(EMOJI['media'])} Отправьте медиа (фото/видео/GIF) для раздела <b>{section_names[section]}</b>\n\n"
        f"{em(EMOJI['write'])} Можете добавить подпись к медиа в тексте сообщения.\n"
        f"{em(EMOJI['info'])} Отправьте /skip чтобы пропустить подпись.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="close_admin_media",
                icon_custom_emoji_id=EMOJI['cross']
            )]
        ])
    )
    await state.set_state(AdminMediaStates.waiting_media_file)
    await callback.answer()

@dp.callback_query(F.data == "close_admin_media")
async def close_admin_media(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()

@dp.message(AdminMediaStates.waiting_media_file)
async def receive_media_file(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()
    section = data["media_section"]

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.animation:
        file_id = message.animation.file_id
        media_type = "animation"
    else:
        await message.answer(f"{em(EMOJI['cross'])} Отправьте фото, видео или GIF!")
        return

    caption = message.caption or message.text or ""
    if caption == "/skip":
        caption = ""

    await update_media_settings(section, media_type, file_id, caption)
    await state.clear()

    await message.answer(f"{em(EMOJI['check'])} Медиа для раздела установлено!")
    await message.answer("Админ-панель:", reply_markup=admin_menu_keyboard())

@dp.message(F.text.contains("Статистика"))
async def admin_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_servers = await conn.fetchval("SELECT COUNT(*) FROM servers")
        active_servers = await conn.fetchval("SELECT COUNT(*) FROM servers WHERE status = 'active'")
        total_revenue = await conn.fetchval("SELECT COALESCE(SUM(price), 0) FROM servers WHERE status IN ('active', 'pending')")

    text = (
        f"{em(EMOJI['stats'])} <b>Статистика бота</b>\n\n"
        f"{em(EMOJI['people'])} Всего пользователей: {total_users}\n"
        f"{em(EMOJI['bot'])} Всего серверов: {total_servers}\n"
        f"{em(EMOJI['check'])} Активных серверов: {active_servers}\n"
        f"{em(EMOJI['money'])} Общая выручка: {total_revenue}₽"
    )

    await message.answer(text)

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    await message.answer(f"{em(EMOJI['check'])} Спасибо за оплату!")

async def on_startup():
    await init_db()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logging.info("Bot started!")

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
