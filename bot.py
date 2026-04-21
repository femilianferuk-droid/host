import asyncio
import os
import logging
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Tuple

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.enums import ParseMode, ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from TikTokApi import TikTokApi
from moviepy.editor import VideoFileClip, CompositeVideoClip, TextClip
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен бота не найден! Укажите BOT_TOKEN в .env файле")

# Файл для хранения настроек пользователей
SETTINGS_FILE = Path("user_settings.json")

# Доступные позиции водяного знака
POSITIONS = {
    "↖️ Верх-Лево": ("left", "top"),
    "⬆️ Верх-Центр": ("center", "top"),
    "↗️ Верх-Право": ("right", "top"),
    "⬅️ Центр-Лево": ("left", "center"),
    "🎯 Центр": ("center", "center"),
    "➡️ Центр-Право": ("right", "center"),
    "↙️ Низ-Лево": ("left", "bottom"),
    "⬇️ Низ-Центр": ("center", "bottom"),
    "↘️ Низ-Право": ("right", "bottom"),
}

# Доступные цвета
COLORS = {
    "⚪️ Белый": "white",
    "⚫️ Чёрный": "black",
    "🔴 Красный": "red",
    "🔵 Синий": "blue",
    "🟢 Зелёный": "green",
    "🟡 Жёлтый": "yellow",
    "🟣 Фиолетовый": "purple",
    "🟠 Оранжевый": "orange",
}

# Размеры шрифта
FONT_SIZES = {
    "🔸 Маленький": 20,
    "🔸🔸 Средний": 35,
    "🔸🔸🔸 Большой": 50,
    "🔸🔸🔸🔸 Огромный": 70,
}

# === ПРЕМИУМ ЭМОДЗИ ID ===
EMOJI = {
    "settings": "5870982283724328568",      # ⚙️
    "profile": "5870994129244131212",       # 👤
    "download": "6039802767931871481",      # ⬇️
    "watermark": "5771851822897566479",     # 🔡
    "position": "5778479949572738874",      # ↔️
    "color": "6050679691004612757",         # 🖌️
    "size": "5884479287171485878",          # 📦
    "opacity": "6037397706505195857",       # 👁️
    "check": "5870633910337015697",         # ✅
    "cross": "5870657884844462243",         # ❌
    "back": "5893057118545646106",          # ◁
    "info": "6028435952299413210",          # ℹ️
    "file": "5870528606328852614",          # 📁
    "link": "5769289093221454192",          # 🔗
    "trash": "5870875489362513438",         # 🗑️
    "edit": "5870676941614354370",          # 🖋️
    "gift": "6032644646587338669",          # 🎁
    "celebrate": "6041731551845159060",     # 🎉
    "clock": "5983150113483134607",         # ⏰
    "robot": "6030400221232501136",         # 🤖
    "media": "6035128606563241721",         # 🖼️
    "money": "5904462880941545555",         # 🪙
    "on": "5891207662678317861",            # 👤✅
    "off": "5893192487324880883",           # 👤❌
    "people": "5870772616305839506",        # 👥
    "stats": "5870930636742595124",         # 📊
    "home": "5873147866364514353",          # 🏘️
}

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Временная папка для обработки файлов
TEMP_DIR = Path("temp_videos")
TEMP_DIR.mkdir(exist_ok=True)

# === РАБОТА С НАСТРОЙКАМИ ПОЛЬЗОВАТЕЛЕЙ ===
def load_settings() -> Dict[int, dict]:
    """Загружает настройки из файла."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}

def save_settings(settings: Dict[int, dict]):
    """Сохраняет настройки в файл."""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

# Загружаем настройки при старте
user_settings = load_settings()

def get_user_settings(user_id: int) -> dict:
    """Получает настройки пользователя или создаёт дефолтные."""
    if user_id not in user_settings:
        user_settings[user_id] = {
            "watermark_enabled": False,
            "watermark_text": "",
            "position": "bottom-right",
            "color": "white",
            "font_size": 30,
            "opacity": 0.7
        }
        save_settings(user_settings)
    return user_settings[user_id]

def get_position_name(position_key: str) -> str:
    """Получает читаемое название позиции."""
    for name, key in POSITIONS.items():
        if f"{key[0]}-{key[1]}" == position_key:
            return name
    return "Низ-Право"

def get_color_name(color: str) -> str:
    """Получает читаемое название цвета."""
    for name, value in COLORS.items():
        if value == color:
            return name
    return "⚪️ Белый"

def get_size_name(size: int) -> str:
    """Получает читаемое название размера."""
    for name, value in FONT_SIZES.items():
        if value == size:
            return name
    return "🔸🔸 Средний"

# === СОСТОЯНИЯ FSM ===
class WatermarkSettings(StatesGroup):
    waiting_for_text = State()
    waiting_for_position = State()
    waiting_for_color = State()
    waiting_for_size = State()
    waiting_for_opacity = State()

# === ФУНКЦИЯ ДОБАВЛЕНИЯ ВОДЯНОГО ЗНАКА ===
def add_watermark(
    input_path: str, 
    output_path: str, 
    text: str,
    position: Tuple[str, str],
    font_size: int,
    color: str,
    opacity: float
):
    """Добавляет текст на видео с пользовательскими настройками."""
    try:
        video = VideoFileClip(input_path)
        
        # Создаем текстовый клип
        txt_clip = TextClip(
            text, 
            fontsize=font_size,
            color=color,
            stroke_color='black' if color == 'white' else 'white',
            stroke_width=2,
            method='caption'
        )
        
        # Устанавливаем прозрачность
        txt_clip = txt_clip.set_opacity(opacity)
        
        # Устанавливаем длительность как у видео
        txt_clip = txt_clip.set_duration(video.duration)
        
        # Позиционируем текст
        txt_clip = txt_clip.set_position(position)
        
        # Объединяем видео и текст
        final = CompositeVideoClip([video, txt_clip])
        
        # Сохраняем результат
        final.write_videofile(
            output_path,
            codec='libx264',
            audio_codec='aac',
            temp_audiofile='temp-audio.m4a',
            remove_temp=True,
            preset='ultrafast'
        )
        
        video.close()
        final.close()
        return True
    except Exception as e:
        logging.error(f"Ошибка при добавлении водяного знака: {e}")
        return False

# === ФУНКЦИЯ СКАЧИВАНИЯ ВИДЕО ИЗ TIKTOK ===
async def download_tiktok_video(url: str, output_path: str) -> bool:
    """Скачивает видео из TikTok без водяного знака."""
    try:
        async with TikTokApi() as api:
            await api.create_sessions(
                ms_tokens=[os.getenv("MS_TOKEN", "")] if os.getenv("MS_TOKEN") else None,
                num_sessions=1,
                sleep_after=3
            )
            
            video = api.video(url=url)
            
            # Получаем прямую ссылку на видео без водяного знака
            video_bytes = await video.bytes()
            
            with open(output_path, "wb") as f:
                f.write(video_bytes)
            
            return True
    except Exception as e:
        logging.error(f"Ошибка при скачивании из TikTok: {e}")
        return False

# === КЛАВИАТУРЫ ===
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура бота с премиум эмодзи."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="⚙️ Настройки",
                    icon_custom_emoji_id=EMOJI["settings"]
                ),
                KeyboardButton(
                    text="👤 Профиль",
                    icon_custom_emoji_id=EMOJI["profile"]
                )
            ],
            [
                KeyboardButton(
                    text="ℹ️ Помощь",
                    icon_custom_emoji_id=EMOJI["info"]
                ),
                KeyboardButton(
                    text="📊 Статистика",
                    icon_custom_emoji_id=EMOJI["stats"]
                )
            ]
        ],
        resize_keyboard=True
    )

def get_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура настроек водяного знака."""
    settings = get_user_settings(user_id)
    status_emoji = EMOJI["on"] if settings["watermark_enabled"] else EMOJI["off"]
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔡 Текст: {settings['watermark_text'] or 'Не задан'}",
            callback_data="set_text",
            icon_custom_emoji_id=EMOJI["edit"]
        )],
        [InlineKeyboardButton(
            text=f"↔️ Позиция: {get_position_name(settings['position'])}",
            callback_data="set_position",
            icon_custom_emoji_id=EMOJI["position"]
        )],
        [InlineKeyboardButton(
            text=f"🖌️ Цвет: {get_color_name(settings['color'])}",
            callback_data="set_color",
            icon_custom_emoji_id=EMOJI["color"]
        )],
        [InlineKeyboardButton(
            text=f"📦 Размер: {get_size_name(settings['font_size'])}",
            callback_data="set_size",
            icon_custom_emoji_id=EMOJI["size"]
        )],
        [InlineKeyboardButton(
            text=f"👁️ Прозрачность: {int(settings['opacity'] * 100)}%",
            callback_data="set_opacity",
            icon_custom_emoji_id=EMOJI["opacity"]
        )],
        [
            InlineKeyboardButton(
                text="✅ Включить" if not settings["watermark_enabled"] else "❌ Выключить",
                callback_data="toggle_watermark",
                icon_custom_emoji_id=status_emoji
            ),
            InlineKeyboardButton(
                text="🗑️ Сбросить",
                callback_data="reset_settings",
                icon_custom_emoji_id=EMOJI["trash"]
            )
        ],
        [InlineKeyboardButton(
            text="◁ Назад",
            callback_data="back_to_main",
            icon_custom_emoji_id=EMOJI["back"]
        )]
    ])

def get_position_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора позиции."""
    buttons = []
    row = []
    for i, (name, _) in enumerate(POSITIONS.items()):
        row.append(InlineKeyboardButton(
            text=name,
            callback_data=f"pos_{name}",
            icon_custom_emoji_id=EMOJI["position"]
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        text="◁ Назад",
        callback_data="back_to_settings",
        icon_custom_emoji_id=EMOJI["back"]
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_color_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора цвета."""
    buttons = []
    row = []
    for i, (name, _) in enumerate(COLORS.items()):
        row.append(InlineKeyboardButton(
            text=name,
            callback_data=f"color_{name}",
            icon_custom_emoji_id=EMOJI["color"]
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        text="◁ Назад",
        callback_data="back_to_settings",
        icon_custom_emoji_id=EMOJI["back"]
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_size_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора размера."""
    buttons = []
    for name, _ in FONT_SIZES.items():
        buttons.append([InlineKeyboardButton(
            text=name,
            callback_data=f"size_{name}",
            icon_custom_emoji_id=EMOJI["size"]
        )])
    
    buttons.append([InlineKeyboardButton(
        text="◁ Назад",
        callback_data="back_to_settings",
        icon_custom_emoji_id=EMOJI["back"]
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_opacity_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора прозрачности."""
    opacities = [0.3, 0.5, 0.7, 0.9]
    buttons = []
    row = []
    for op in opacities:
        row.append(InlineKeyboardButton(
            text=f"{int(op * 100)}%",
            callback_data=f"opacity_{op}",
            icon_custom_emoji_id=EMOJI["opacity"]
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(
        text="◁ Назад",
        callback_data="back_to_settings",
        icon_custom_emoji_id=EMOJI["back"]
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# === ОБРАБОТЧИКИ КОМАНД ===
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start."""
    welcome_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['robot']}\">🤖</tg-emoji> Привет, {message.from_user.first_name}!</b>

<tg-emoji emoji-id=\"{EMOJI['download']}\">⬇️</tg-emoji> Я бот для скачивания видео из TikTok!

<b>Что я умею:</b>
<tg-emoji emoji-id=\"{EMOJI['media']}\">🖼️</tg-emoji> • Скачивать видео без водяного знака TikTok
<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> • Добавлять твой собственный водяной знак
<tg-emoji emoji-id=\"{EMOJI['settings']}\">⚙️</tg-emoji> • Настраивать текст, позицию, цвет и прозрачность

Просто отправь мне ссылку на видео TikTok и я сразу пришлю его тебе!

Используй кнопки меню для настройки водяного знака.
"""
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(F.text.in_({"⚙️ Настройки", "Настройки"}))
async def settings_command(message: types.Message):
    """Показывает настройки пользователя."""
    settings = get_user_settings(message.from_user.id)
    
    status_text = "✅ <b>ВКЛЮЧЕН</b>" if settings["watermark_enabled"] else "❌ <b>ВЫКЛЮЧЕН</b>"
    
    settings_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['settings']}\">⚙️</tg-emoji> Настройки водяного знака</b>

<b>Статус:</b> {status_text}

<b>Текущие настройки:</b>
<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> <b>Текст:</b> {settings['watermark_text'] or '<i>не задан</i>'}
<tg-emoji emoji-id=\"{EMOJI['position']}\">↔️</tg-emoji> <b>Позиция:</b> {get_position_name(settings['position'])}
<tg-emoji emoji-id=\"{EMOJI['color']}\">🖌️</tg-emoji> <b>Цвет:</b> {get_color_name(settings['color'])}
<tg-emoji emoji-id=\"{EMOJI['size']}\">📦</tg-emoji> <b>Размер:</b> {get_size_name(settings['font_size'])}
<tg-emoji emoji-id=\"{EMOJI['opacity']}\">👁️</tg-emoji> <b>Прозрачность:</b> {int(settings['opacity'] * 100)}%

<i>Выбери параметр для настройки:</i>
"""
    await message.answer(
        settings_text,
        reply_markup=get_settings_keyboard(message.from_user.id)
    )

@dp.message(F.text.in_({"👤 Профиль", "Профиль"}))
async def profile_command(message: types.Message):
    """Показывает профиль пользователя."""
    settings = get_user_settings(message.from_user.id)
    
    watermark_status = "✅ Включен" if settings["watermark_enabled"] else "❌ Выключен"
    
    profile_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> Профиль пользователя</b>

<tg-emoji emoji-id=\"{EMOJI['people']}\">👥</tg-emoji> <b>ID:</b> <code>{message.from_user.id}</code>
<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> <b>Водяной знак:</b> {watermark_status}
<tg-emoji emoji-id=\"{EMOJI['file']}\">📁</tg-emoji> <b>Текст:</b> {settings['watermark_text'] or '<i>не задан</i>'}

<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> <i>Настройки сохраняются автоматически</i>
"""
    await message.answer(profile_text)

@dp.message(F.text.in_({"ℹ️ Помощь", "Помощь"}))
async def help_command(message: types.Message):
    """Показывает справку."""
    help_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ️</tg-emoji> Помощь</b>

<tg-emoji emoji-id=\"{EMOJI['download']}\">⬇️</tg-emoji> <b>Как скачать видео:</b>
Просто отправь мне ссылку на видео из TikTok

<tg-emoji emoji-id=\"{EMOJI['settings']}\">⚙️</tg-emoji> <b>Настройка водяного знака:</b>
1. Нажми "⚙️ Настройки"
2. Включи водяной знак
3. Настрой текст, позицию, цвет и размер
4. При скачивании видео знак добавится автоматически

<tg-emoji emoji-id=\"{EMOJI['link']}\">🔗</tg-emoji> <b>Поддерживаемые ссылки:</b>
• https://www.tiktok.com/@user/video/123...
• https://vm.tiktok.com/...
• https://vt.tiktok.com/...

<tg-emoji emoji-id=\"{EMOJI['gift']}\">🎁</tg-emoji> <b>Особенности:</b>
• Видео скачивается без водяного знака TikTok
• Твой водяной знак добавляется только если включен в настройках
• Максимальный размер видео — 50 МБ (ограничение Telegram)
"""
    await message.answer(help_text)

@dp.message(F.text.in_({"📊 Статистика", "Статистика"}))
async def stats_command(message: types.Message):
    """Показывает статистику бота."""
    stats_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['stats']}\">📊</tg-emoji> Статистика бота</b>

<tg-emoji emoji-id=\"{EMOJI['people']}\">👥</tg-emoji> <b>Пользователей:</b> {len(user_settings)}
<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> <b>С водяным знаком:</b> {sum(1 for s in user_settings.values() if s.get('watermark_enabled', False))}
<tg-emoji emoji-id=\"{EMOJI['file']}\">📁</tg-emoji> <b>Без водяного знака:</b> {sum(1 for s in user_settings.values() if not s.get('watermark_enabled', False))}

<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> <i>Статистика обновляется в реальном времени</i>
"""
    await message.answer(stats_text)

# === ОБРАБОТЧИКИ CALLBACK ДЛЯ НАСТРОЕК ===
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню."""
    await callback.message.delete()
    await callback.message.answer(
        f"<b><tg-emoji emoji-id=\"{EMOJI['home']}\">🏘️</tg-emoji> Главное меню</b>\n\nВыбери действие на клавиатуре:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_settings")
async def back_to_settings(callback: CallbackQuery):
    """Возврат к настройкам."""
    settings = get_user_settings(callback.from_user.id)
    status_text = "✅ <b>ВКЛЮЧЕН</b>" if settings["watermark_enabled"] else "❌ <b>ВЫКЛЮЧЕН</b>"
    
    settings_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['settings']}\">⚙️</tg-emoji> Настройки водяного знака</b>

<b>Статус:</b> {status_text}

<b>Текущие настройки:</b>
<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> <b>Текст:</b> {settings['watermark_text'] or '<i>не задан</i>'}
<tg-emoji emoji-id=\"{EMOJI['position']}\">↔️</tg-emoji> <b>Позиция:</b> {get_position_name(settings['position'])}
<tg-emoji emoji-id=\"{EMOJI['color']}\">🖌️</tg-emoji> <b>Цвет:</b> {get_color_name(settings['color'])}
<tg-emoji emoji-id=\"{EMOJI['size']}\">📦</tg-emoji> <b>Размер:</b> {get_size_name(settings['font_size'])}
<tg-emoji emoji-id=\"{EMOJI['opacity']}\">👁️</tg-emoji> <b>Прозрачность:</b> {int(settings['opacity'] * 100)}%

<i>Выбери параметр для настройки:</i>
"""
    await callback.message.edit_text(
        settings_text,
        reply_markup=get_settings_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "toggle_watermark")
async def toggle_watermark(callback: CallbackQuery):
    """Включение/выключение водяного знака."""
    user_id = callback.from_user.id
    settings = get_user_settings(user_id)
    
    # Проверяем, задан ли текст
    if not settings["watermark_enabled"] and not settings["watermark_text"]:
        await callback.answer("❌ Сначала задай текст водяного знака!", show_alert=True)
        return
    
    settings["watermark_enabled"] = not settings["watermark_enabled"]
    user_settings[user_id] = settings
    save_settings(user_settings)
    
    status = "включен ✅" if settings["watermark_enabled"] else "выключен ❌"
    await callback.answer(f"Водяной знак {status}")
    await back_to_settings(callback)

@dp.callback_query(F.data == "set_text")
async def set_text_start(callback: CallbackQuery, state: FSMContext):
    """Начало установки текста."""
    await callback.message.edit_text(
        f"<b><tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> Введи текст для водяного знака:</b>\n\n"
        f"<i>Например: @username или твой никнейм</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="◁ Отмена",
                callback_data="back_to_settings",
                icon_custom_emoji_id=EMOJI["back"]
            )
        ]])
    )
    await state.set_state(WatermarkSettings.waiting_for_text)
    await callback.answer()

@dp.message(WatermarkSettings.waiting_for_text)
async def set_text_done(message: types.Message, state: FSMContext):
    """Сохранение текста."""
    text = message.text.strip()
    if len(text) > 50:
        await message.answer("❌ Текст слишком длинный! Максимум 50 символов.")
        return
    
    user_id = message.from_user.id
    settings = get_user_settings(user_id)
    settings["watermark_text"] = text
    user_settings[user_id] = settings
    save_settings(user_settings)
    
    await state.clear()
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Текст сохранён: <b>{text}</b>",
        reply_markup=get_main_keyboard()
    )
    
    # Показываем обновленные настройки
    settings_text = f"""
<b><tg-emoji emoji-id=\"{EMOJI['settings']}\">⚙️</tg-emoji> Настройки водяного знака</b>

<b>Статус:</b> {'✅ <b>ВКЛЮЧЕН</b>' if settings['watermark_enabled'] else '❌ <b>ВЫКЛЮЧЕН</b>'}

<b>Текущие настройки:</b>
<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> <b>Текст:</b> {settings['watermark_text']}
<tg-emoji emoji-id=\"{EMOJI['position']}\">↔️</tg-emoji> <b>Позиция:</b> {get_position_name(settings['position'])}
<tg-emoji emoji-id=\"{EMOJI['color']}\">🖌️</tg-emoji> <b>Цвет:</b> {get_color_name(settings['color'])}
<tg-emoji emoji-id=\"{EMOJI['size']}\">📦</tg-emoji> <b>Размер:</b> {get_size_name(settings['font_size'])}
<tg-emoji emoji-id=\"{EMOJI['opacity']}\">👁️</tg-emoji> <b>Прозрачность:</b> {int(settings['opacity'] * 100)}%

<i>Выбери параметр для настройки:</i>
"""
    await message.answer(
        settings_text,
        reply_markup=get_settings_keyboard(user_id)
    )

@dp.callback_query(F.data == "set_position")
async def set_position(callback: CallbackQuery):
    """Выбор позиции."""
    await callback.message.edit_text(
        f"<b><tg-emoji emoji-id=\"{EMOJI['position']}\">↔️</tg-emoji> Выбери позицию водяного знака:</b>",
        reply_markup=get_position_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("pos_"))
async def position_selected(callback: CallbackQuery):
    """Сохранение позиции."""
    position_name = callback.data.replace("pos_", "")
    position_value = POSITIONS[position_name]
    
    user_id = callback.from_user.id
    settings = get_user_settings(user_id)
    settings["position"] = f"{position_value[0]}-{position_value[1]}"
    user_settings[user_id] = settings
    save_settings(user_settings)
    
    await callback.answer(f"Позиция: {position_name}")
    await back_to_settings(callback)

@dp.callback_query(F.data == "set_color")
async def set_color(callback: CallbackQuery):
    """Выбор цвета."""
    await callback.message.edit_text(
        f"<b><tg-emoji emoji-id=\"{EMOJI['color']}\">🖌️</tg-emoji> Выбери цвет текста:</b>",
        reply_markup=get_color_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("color_"))
async def color_selected(callback: CallbackQuery):
    """Сохранение цвета."""
    color_name = callback.data.replace("color_", "")
    color_value = COLORS[color_name]
    
    user_id = callback.from_user.id
    settings = get_user_settings(user_id)
    settings["color"] = color_value
    user_settings[user_id] = settings
    save_settings(user_settings)
    
    await callback.answer(f"Цвет: {color_name}")
    await back_to_settings(callback)

@dp.callback_query(F.data == "set_size")
async def set_size(callback: CallbackQuery):
    """Выбор размера."""
    await callback.message.edit_text(
        f"<b><tg-emoji emoji-id=\"{EMOJI['size']}\">📦</tg-emoji> Выбери размер шрифта:</b>",
        reply_markup=get_size_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("size_"))
async def size_selected(callback: CallbackQuery):
    """Сохранение размера."""
    size_name = callback.data.replace("size_", "")
    size_value = FONT_SIZES[size_name]
    
    user_id = callback.from_user.id
    settings = get_user_settings(user_id)
    settings["font_size"] = size_value
    user_settings[user_id] = settings
    save_settings(user_settings)
    
    await callback.answer(f"Размер: {size_name}")
    await back_to_settings(callback)

@dp.callback_query(F.data == "set_opacity")
async def set_opacity(callback: CallbackQuery):
    """Выбор прозрачности."""
    await callback.message.edit_text(
        f"<b><tg-emoji emoji-id=\"{EMOJI['opacity']}\">👁️</tg-emoji> Выбери прозрачность текста:</b>",
        reply_markup=get_opacity_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("opacity_"))
async def opacity_selected(callback: CallbackQuery):
    """Сохранение прозрачности."""
    opacity_value = float(callback.data.replace("opacity_", ""))
    
    user_id = callback.from_user.id
    settings = get_user_settings(user_id)
    settings["opacity"] = opacity_value
    user_settings[user_id] = settings
    save_settings(user_settings)
    
    await callback.answer(f"Прозрачность: {int(opacity_value * 100)}%")
    await back_to_settings(callback)

@dp.callback_query(F.data == "reset_settings")
async def reset_settings(callback: CallbackQuery):
    """Сброс настроек."""
    user_id = callback.from_user.id
    user_settings[user_id] = {
        "watermark_enabled": False,
        "watermark_text": "",
        "position": "bottom-right",
        "color": "white",
        "font_size": 30,
        "opacity": 0.7
    }
    save_settings(user_settings)
    
    await callback.answer("Настройки сброшены")
    await back_to_settings(callback)

# === ОБРАБОТЧИК ССЫЛОК TIKTOK ===
@dp.message(F.text.contains("tiktok.com"))
async def process_tiktok_link(message: types.Message):
    """Обработка ссылки на TikTok."""
    url = message.text.strip()
    
    # Извлекаем URL если он в тексте
    import re
    url_match = re.search(r'https?://[^\s]+', url)
    if url_match:
        url = url_match.group(0)
    
    # Отправляем сообщение о начале загрузки
    status_msg = await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['download']}\">⬇️</tg-emoji> <b>Скачиваю видео...</b>\n"
        f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> <i>Это может занять несколько секунд</i>"
    )
    
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    
    # Создаем временные файлы
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=TEMP_DIR) as tmp_input:
        input_path = tmp_input.name
    
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=TEMP_DIR) as tmp_output:
        output_path = tmp_output.name
    
    try:
        # Скачиваем видео
        success = await download_tiktok_video(url, input_path)
        
        if not success:
            await status_msg.edit_text(
                f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> <b>Не удалось скачать видео!</b>\n"
                f"Проверь ссылку и попробуй снова."
            )
            return
        
        # Проверяем настройки водяного знака
        settings = get_user_settings(message.from_user.id)
        final_path = input_path
        
        if settings["watermark_enabled"] and settings["watermark_text"]:
            await status_msg.edit_text(
                f"<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> <b>Добавляю водяной знак...</b>"
            )
            
            position_parts = settings["position"].split("-")
            position = (position_parts[0], position_parts[1])
            
            watermark_success = add_watermark(
                input_path,
                output_path,
                settings["watermark_text"],
                position,
                settings["font_size"],
                settings["color"],
                settings["opacity"]
            )
            
            if watermark_success:
                final_path = output_path
        
        # Проверяем размер файла
        file_size = os.path.getsize(final_path)
        if file_size > 50 * 1024 * 1024:  # 50 MB
            await status_msg.edit_text(
                f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> <b>Видео слишком большое!</b>\n"
                f"Размер: {file_size / 1024 / 1024:.1f} МБ (максимум 50 МБ)"
            )
            return
        
        # Отправляем видео
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['media']}\">🖼️</tg-emoji> <b>Отправляю видео...</b>"
        )
        
        video_file = FSInputFile(final_path)
        
        caption = f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> <b>Видео готово!</b>"
        if settings["watermark_enabled"] and settings["watermark_text"]:
            caption += f"\n<tg-emoji emoji-id=\"{EMOJI['watermark']}\">🔡</tg-emoji> Водяной знак: {settings['watermark_text']}"
        
        await message.reply_video(
            video=video_file,
            caption=caption,
            reply_markup=get_main_keyboard()
        )
        
        await status_msg.delete()
        
    except Exception as e:
        logging.error(f"Ошибка при обработке видео: {e}")
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> <b>Произошла ошибка!</b>\n"
            f"Попробуй позже или с другим видео."
        )
    
    finally:
        # Удаляем временные файлы
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)
        except:
            pass

# === ОБРАБОТЧИК НЕИЗВЕСТНЫХ СООБЩЕНИЙ ===
@dp.message()
async def unknown_message(message: types.Message):
    """Обработчик неизвестных сообщений."""
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ️</tg-emoji> "
        f"Отправь мне ссылку на видео из TikTok, чтобы я мог его скачать!\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['settings']}\">⚙️</tg-emoji> "
        f"Используй меню для настройки водяного знака.",
        reply_markup=get_main_keyboard()
    )

# === ЗАПУСК БОТА ===
async def main():
    """Запуск бота."""
    logging.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
