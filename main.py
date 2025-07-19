from typing import Final, Optional
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from datetime import datetime, timedelta
import sqlite3
import re

TOKEN: Final = '8164683944:AAFblJC8b6i_2_poEqb7qnMnLd0WElfgG6Q'
BOT_USERNAME: Final = '@MepiDonor_bot'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

def init_db():
    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS donors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        phone TEXT NOT NULL,
        full_name TEXT NOT NULL,
        category TEXT,
        group_name TEXT,
        dkm_member BOOLEAN DEFAULT FALSE,
        consent BOOLEAN DEFAULT FALSE,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS donations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER,
        date DATE,
        center TEXT,
        gave_dkm_sample BOOLEAN DEFAULT FALSE,
        type TEXT,
        FOREIGN KEY (donor_id) REFERENCES donors (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS donation_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE UNIQUE,
        center TEXT,
        external_link TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER,
        text TEXT,
        answer TEXT,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (donor_id) REFERENCES donors (id)
    )
    ''')

    conn.commit()
    conn.close()

init_db()

class RegistrationStates(StatesGroup):
    phone = State()
    full_name = State()
    category = State()
    group = State()
    consent = State()

class DonationDayStates(StatesGroup):
    select_day = State()
    confirm = State()

class QuestionStates(StatesGroup):
    input_question = State()

def validate_full_name(full_name: str) -> bool:
    pattern = r'^[А-ЯЁ][а-яё]+\s[А-ЯЁ][а-яё]+(?:\s[А-ЯЁ][а-яё]+)?$'
    return re.fullmatch(pattern, full_name) is not None

async def is_user_registered(telegram_id: int) -> bool:
    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM donors WHERE telegram_id = ?', (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

async def get_user_info(telegram_id: int) -> Optional[dict]:
    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT full_name, category, group_name, dkm_member 
        FROM donors WHERE telegram_id = ?
    ''', (telegram_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'full_name': result[0],
            'category': result[1],
            'group': result[2],
            'dkm_member': bool(result[3])
        }
    return None

async def get_upcoming_donation_days() -> list:
    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, date, center 
        FROM donation_days 
        WHERE date >= date('now') 
        ORDER BY date
    ''')
    days = cursor.fetchall()
    conn.close()

    return [{'id': day[0], 'date': day[1], 'center': day[2]} for day in days]

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    if await is_user_registered(message.from_user.id):
        await show_personal_cabinet(message)
    else:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Отправить номер", request_contact=True)]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "👋 Привет! Я бот для организации Дня Донора в НИЯУ МИФИ.\n\n"
            "Я помогу тебе:\n"
            "✅ Зарегистрироваться как донор\n"
            "📅 Записаться на День Донора\n"
            "📊 Следить за своей историей донаций\n\n"
            "Для начала отправь мне свой номер телефона:",
            reply_markup=kb
        )
        await state.set_state(RegistrationStates.phone)

@dp.message(RegistrationStates.phone, F.contact)
async def contact_received(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await message.answer(
        "Спасибо! Теперь введи своё ФИО (Фамилия Имя Отчество):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RegistrationStates.full_name)

@dp.message(RegistrationStates.full_name)
async def full_name_received(message: types.Message, state: FSMContext):
    full_name = message.text.strip()

    if not validate_full_name(full_name):
        await message.answer(
            "❌ Неверный формат ФИО. Пожалуйста, введи своё полное имя в формате:\n"
            "<b>Фамилия Имя Отчество</b> (если есть) с заглавных букв.\n"
            "Пример: <i>Иванов Иван Иванович</i> или <i>Петрова Анна</i>"
        )
        return

    await state.update_data(full_name=full_name)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Студент")],
            [KeyboardButton(text="Сотрудник")],
            [KeyboardButton(text="Внешний донор")]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "Выбери свою категорию:",
        reply_markup=kb
    )
    await state.set_state(RegistrationStates.category)

@dp.message(RegistrationStates.category)
async def category_received(message: types.Message, state: FSMContext):
    category = message.text.lower()
    valid_categories = ['студент', 'сотрудник', 'внешний донор']

    if category not in valid_categories:
        await message.answer("Пожалуйста, выбери одну из предложенных категорий.")
        return

    await state.update_data(category=category)

    if category == 'студент':
        await message.answer(
            "Введи номер своей учебной группы:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(RegistrationStates.group)
    else:
        await state.update_data(group=None)
        await ask_for_consent(message, state)

@dp.message(RegistrationStates.group)
async def group_received(message: types.Message, state: FSMContext):
    group = message.text.strip()
    await state.update_data(group=group)
    await ask_for_consent(message, state)

async def ask_for_consent(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Даю согласие", callback_data="consent_yes")],
            [InlineKeyboardButton(text="❌ Не согласен", callback_data="consent_no")]
        ]
    )

    await message.answer(
        "❗ Перед завершением регистрации необходимо дать согласие:\n\n"
        "Я согласен на обработку моих персональных данных и получение "
        "информационных сообщений, связанных с донорством крови.",
        reply_markup=kb
    )
    await state.set_state(RegistrationStates.consent)

@dp.callback_query(RegistrationStates.consent, F.data.startswith("consent_"))
async def consent_received(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "consent_no":
        await callback.message.answer(
            "❌ Регистрация отменена. Без согласия на обработку персональных данных "
            "мы не можем зарегистрировать вас как донора."
        )
        await state.clear()
        return

    data = await state.get_data()

    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO donors (
                telegram_id, phone, full_name, category, group_name, consent
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            callback.from_user.id,
            data['phone'],
            data['full_name'],
            data['category'],
            data.get('group'),
            True
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        await callback.message.answer("❌ Этот номер телефона уже зарегистрирован.")
        conn.close()
        await state.clear()
        return

    conn.close()

    await callback.message.answer(
        "🎉 Регистрация успешно завершена!\n\n"
        f"<b>ФИО:</b> {data['full_name']}\n"
        f"<b>Категория:</b> {data['category']}\n"
        f"<b>Группа:</b> {data.get('group', 'не указана')}\n\n"
        "Теперь ты можешь записаться на День Донора или посмотреть свою информацию.",
        reply_markup=ReplyKeyboardRemove()
    )

    await show_personal_cabinet(callback.message)
    await state.clear()

@dp.message(Command("cabinet"))
async def cmd_cabinet(message: types.Message):
    if not await is_user_registered(message.from_user.id):
        await message.answer("Сначала нужно зарегистрироваться. Нажми /start")
        return

    await show_personal_cabinet(message)

async def show_personal_cabinet(message: types.Message):
    user_info = await get_user_info(message.from_user.id)
    if not user_info:
        await message.answer("❌ Не удалось загрузить ваши данные. Попробуйте позже.")
        return

    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM donations 
        WHERE donor_id = (
            SELECT id FROM donors WHERE telegram_id = ?
        )
    ''', (message.from_user.id,))
    donation_count = cursor.fetchone()[0]
    conn.close()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Записаться на День Донора", callback_data="register_dd")],
            [InlineKeyboardButton(text="✏️ Мои данные", callback_data="my_data")],
            [InlineKeyboardButton(text="🩸 История донаций", callback_data="donation_history")],
            [InlineKeyboardButton(text="❓ Вопрос организатору", callback_data="ask_question")],
            [InlineKeyboardButton(text="ℹ️ Информация о донорстве", callback_data="donation_info")],
        ]
    )

    await message.answer(
        f"👤 <b>Личный кабинет</b>\n\n"
        f"<b>ФИО:</b> {user_info['full_name']}\n"
        f"<b>Категория:</b> {user_info['category']}\n"
        f"<b>Группа/статус:</b> {user_info['group'] or 'не указано'}\n"
        f"<b>Донаций:</b> {donation_count}\n"
        f"<b>В регистре ДКМ:</b> {'Да' if user_info['dkm_member'] else 'Нет'}\n\n"
        "Выбери действие:",
        reply_markup=kb
    )

@dp.callback_query(F.data.in_(["my_data", "donation_history", "donation_info", "ask_question"]))
async def cabinet_buttons_handler(callback: types.CallbackQuery):
    if callback.data == "my_data":
        await show_user_data(callback)
    elif callback.data == "donation_history":
        await show_donation_history(callback)
    elif callback.data == "donation_info":
        await show_donation_info(callback)
    elif callback.data == "ask_question":
        await ask_question(callback)

async def show_user_data(callback: types.CallbackQuery):
    user_info = await get_user_info(callback.from_user.id)
    if not user_info:
        await callback.message.answer("❌ Не удалось загрузить ваши данные.")
        return

    await callback.message.answer(
        f"📋 <b>Мои данные</b>\n\n"
        f"<b>ФИО:</b> {user_info['full_name']}\n"
        f"<b>Категория:</b> {user_info['category']}\n"
        f"<b>Группа/статус:</b> {user_info['group'] or 'не указано'}\n"
        f"<b>В регистре ДКМ:</b> {'Да' if user_info['dkm_member'] else 'Нет'}\n\n"
        "Чтобы изменить данные, обратитесь к организатору."
    )
    await callback.answer()

async def show_donation_history(callback: types.CallbackQuery):
    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT d.id, d.date, d.center, d.gave_dkm_sample, d.type
        FROM donations d
        JOIN donors dr ON d.donor_id = dr.id
        WHERE dr.telegram_id = ?
        ORDER BY d.date DESC
    ''', (callback.from_user.id,))

    donations = cursor.fetchall()
    conn.close()

    if not donations:
        await callback.message.answer("❌ У вас пока нет донаций.")
        await callback.answer()
        return

    text = "🩸 <b>История донаций</b>\n\n"
    for donation in donations:
        text += (
            f"<b>Дата:</b> {donation[1]}\n"
            f"<b>Центр:</b> {donation[2]}\n"
            f"<b>Тип:</b> {donation[4]}\n"
            f"<b>Сдал пробирку ДКМ:</b> {'Да' if donation[3] else 'Нет'}\n\n"
        )

    await callback.message.answer(text)
    await callback.answer()

async def show_donation_info(callback: types.CallbackQuery):
    text = (
        "ℹ️ <b>Информация о донорстве</b>\n\n"
        "🔹 <b>Перед сдачей крови:</b>\n"
        "- Выспитесь\n"
        "- Питайтесь правильно за 2 дня до донации\n"
        "- Не употребляйте алкоголь за 48 часов\n"
        "- Пейте больше воды\n\n"
        "🔹 <b>После сдачи крови:</b>\n"
        "- Отдохните 10-15 минут\n"
        "- Не курите 2 часа\n"
        "- Не снимайте повязку 3-4 часа\n"
        "- Избегайте физических нагрузок\n\n"
        "📌 Полная информация на сайте <a href='https://mephi.ru'>mephi.ru</a>"
    )
    await callback.message.answer(text, disable_web_page_preview=True)
    await callback.answer()

@dp.callback_query(F.data == "register_dd")
async def register_for_donation_day(callback: types.CallbackQuery, state: FSMContext):
    if not await is_user_registered(callback.from_user.id):
        await callback.message.answer("Сначала нужно зарегистрироваться. Нажми /start")
        await callback.answer()
        return

    days = await get_upcoming_donation_days()
    if not days:
        await callback.message.answer("❌ В ближайшее время нет запланированных Дней Донора.")
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for day in days:
        kb.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{day['date']} ({day['center']})",
                callback_data=f"dd_day_{day['id']}"
            )
        ])

    await callback.message.answer(
        "📅 Выбери День Донора для записи:",
        reply_markup=kb
    )
    await state.set_state(DonationDayStates.select_day)
    await callback.answer()

@dp.callback_query(DonationDayStates.select_day, F.data.startswith("dd_day_"))
async def donation_day_selected(callback: types.CallbackQuery, state: FSMContext):
    day_id = int(callback.data.split("_")[2])
    await state.update_data(day_id=day_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="dd_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="dd_cancel")]
        ]
    )

    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT date, center FROM donation_days WHERE id = ?', (day_id,))
    day = cursor.fetchone()
    conn.close()

    if not day:
        await callback.message.answer("❌ Ошибка выбора дня. Попробуйте снова.")
        await state.clear()
        return

    await callback.message.answer(
        f"Ты выбрал День Донора:\n\n"
        f"<b>Дата:</b> {day[0]}\n"
        f"<b>Центр:</b> {day[1]}\n\n"
        "Подтверди запись:",
        reply_markup=kb
    )
    await state.set_state(DonationDayStates.confirm)
    await callback.answer()

@dp.callback_query(DonationDayStates.confirm, F.data == "dd_confirm")
async def donation_day_confirmed(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    day_id = data['day_id']

    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT id, category FROM donors WHERE telegram_id = ?', (callback.from_user.id,))
    donor = cursor.fetchone()

    if not donor:
        await callback.message.answer("❌ Ошибка: пользователь не найден.")
        await state.clear()
        conn.close()
        return

    donor_id, category = donor

    cursor.execute('SELECT date, center, external_link FROM donation_days WHERE id = ?', (day_id,))
    day = cursor.fetchone()

    if not day:
        await callback.message.answer("❌ Ошибка: день донора не найден.")
        await state.clear()
        conn.close()
        return

    date, center, external_link = day

    if category == 'внешний донор' and external_link:
        await callback.message.answer(
            f"🔗 Для завершения регистрации перейди по ссылке:\n{external_link}"
        )
        await state.clear()
        conn.close()
        return

    try:
        cursor.execute('''
            INSERT INTO donations (donor_id, date, center, type)
            VALUES (?, ?, ?, ?)
        ''', (donor_id, date, center, category))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error registering for donation day: {e}")
        await callback.message.answer("❌ Ошибка при записи. Попробуйте позже.")
        await state.clear()
        conn.close()
        return

    conn.close()

    await callback.message.answer(
        "✅ Ты успешно записался на День Донора!\n\n"
        f"<b>Дата:</b> {date}\n"
        f"<b>Центр:</b> {center}\n\n"
        "Мы пришлем тебе напоминание за день до события."
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(DonationDayStates.confirm, F.data == "dd_cancel")
async def donation_day_canceled(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Запись отменена.")
    await state.clear()
    await callback.answer()
async def ask_question(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✍️ Напиши свой вопрос организатору Дня Донора. "
        "Мы постараемся ответить как можно скорее.",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(QuestionStates.input_question)
    await callback.answer()

@dp.message(QuestionStates.input_question)
async def question_received(message: types.Message, state: FSMContext):
    question = message.text.strip()

    if len(question) < 10:
        await message.answer("❌ Вопрос слишком короткий. Пожалуйста, уточните детали.")
        return

    conn = sqlite3.connect('donor_bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT id FROM donors WHERE telegram_id = ?', (message.from_user.id,))
    donor = cursor.fetchone()

    if not donor:
        await message.answer("❌ Ошибка: пользователь не найден.")
        await state.clear()
        conn.close()
        return

    donor_id = donor[0]

    try:
        cursor.execute('''
            INSERT INTO questions (donor_id, text)
            VALUES (?, ?)
        ''', (donor_id, question))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error saving question: {e}")
        await message.answer("❌ Ошибка при отправке вопроса. Попробуйте позже.")
        await state.clear()
        conn.close()
        return

    conn.close()

    await message.answer(
        "✅ Ваш вопрос отправлен организаторам. "
        "Мы пришлем ответ в этом чате, как только он будет готов."
    )
    await state.clear()

if __name__ == "__main__":
    import asyncio

    logger.info("Starting bot...")
    asyncio.run(dp.start_polling(bot))