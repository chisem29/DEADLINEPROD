import logging
import datetime
import os
import sqlite3
import re
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils import executor
from dotenv import load_dotenv
from pydub import AudioSegment
import speech_recognition as sr

from couples import get_couples
from speech2text import recognize_voice
from task import Task

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

task = Task()

conn = sqlite3.connect("schedule.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    start_time TEXT,
    end_time TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    scheduled_time TEXT
)
""")
conn.commit()


cursor.execute("PRAGMA table_info(tasks)")
columns = [info[1] for info in cursor.fetchall()]
if "execution_date" not in columns:
    cursor.execute("ALTER TABLE tasks ADD COLUMN execution_date TEXT")
    conn.commit()
if "completed" not in columns:
    cursor.execute("ALTER TABLE tasks ADD COLUMN completed INTEGER DEFAULT 0")
    conn.commit()


main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(
    KeyboardButton("➕ Добавить задачу"),
    KeyboardButton("🗣️ Голосовой ввод"),
    KeyboardButton("📋 Список задач"),
)


def get_russian_weekday(date_obj):
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[date_obj.weekday()]


class TaskCreation(StatesGroup):
    waiting_for_task_name = State()
    waiting_for_voice = State()
    waiting_for_duration_confirmation = State()
    waiting_for_duration_modification = State()
    waiting_for_execution_date = State()


class TaskTimeModification(StatesGroup):
    waiting_for_new_time = State()


@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.reply("Привет! Я помогу тебе планировать личное время! Вот, что я могу:\n"
                        "/addtask - добавить задачу\n"
                        "/voice_addtask - добавить задачу голосом\n"
                        "/tasks - посмотреть все задачи", reply_markup=main_keyboard)


@dp.message_handler(commands=['addtask'])
async def add_task(message: types.Message):
    await TaskCreation.waiting_for_task_name.set()
    await message.reply("Введите название задачи:")


@dp.message_handler(commands=['voice_addtask'])
async def voice_add_task_command(message: types.Message):
    await TaskCreation.waiting_for_voice.set()
    await message.reply("Отправьте голосовое сообщение с названием задачи в следующем формате:\n\n"
                        "<b>Поставь задачу 'посмотреть фильм' на 10 февраля</b>", parse_mode="HTML")


@dp.message_handler(lambda message: message.text == "➕ Голосовой ввод")
async def voice_add_task_command(message: types.Message):
    await TaskCreation.waiting_for_voice.set()
    await message.reply("Отправьте голосовое сообщение с названием задачи в следующем формате:\n\n"
                        "<b>Поставь задачу 'посмотреть фильм' на 10 февраля</b>", parse_mode="HTML")


@dp.message_handler(content_types=types.ContentType.VOICE, state=TaskCreation.waiting_for_voice)
async def process_voice_message(message: types.Message, state: FSMContext):
    file_id = message.voice.file_id
    local_filename = f"voice_{message.from_user.id}.ogg"
    await message.voice.download(destination=local_filename)
    logging.info(f"Файл сохранен как {local_filename}")
    mess = await message.answer("Файл получен. Начинаем обработку. Подождите пару секунд...")

    try:
        recognized_text = recognize_voice(local_filename)
    except Exception as e:
        logging.error(f"Ошибка при распознавании голоса: {e}")
        await message.reply("Ошибка при обработке голосового сообщения.")
        await mess.delete()
        try:
            os.remove(local_filename)
            os.remove(local_filename.replace(".ogg", ".wav"))
        except:
            pass
        return

    if not recognized_text:
        await message.reply("Не удалось распознать голосовое сообщение.")
        await mess.delete()
        try:
            os.remove(local_filename)
            os.remove(local_filename.replace(".ogg", ".wav"))
        except:
            pass
        return

    try:
        answer = task.get_answer(recognized_text, system_prompt="Предоставь ответ в следующем формате:\nЗадача: текст задачи\nДата: 02-10")
    except Exception as e:
        await mess.delete()
        try:
            os.remove(local_filename)
            os.remove(local_filename.replace(".ogg", ".wav"))
        except:
            pass
        logging.error(f"Ошибка при обработке распознанного текста: {e}")
        await message.reply("Ошибка при обработке распознанного текста.")
        return

    await mess.delete()
    try:
        os.remove(local_filename)
        os.remove(local_filename.replace(".ogg", ".wav"))
    except:
        pass
    await message.reply(f"Распознанный текст:\n{answer}")

    task_name = None
    date_text = None
    answer = answer.replace("Задача", "\nЗадача").replace("Дата", "\nДата")
    for i, line in enumerate(answer.split(":")):
        if "задача" in line.lower():
            task_name = answer.split(":")[i+1].strip().replace("\n\nДата", "")
        elif "дата" in line.lower():
            date_text = answer.split(":")[i+1].strip().replace(".", "-")[:5]
    if not task_name or not date_text:
        await message.reply("Не удалось извлечь название задачи или дату из распознанного текста.")
        return

    try:
        print(date_text)
        day, month = map(int, date_text.split("-"))
        current_year = datetime.date.today().year
        execution_date = datetime.date(current_year, month, day)

        if execution_date < datetime.date.today():
            execution_date = datetime.date(current_year + 1, month, day)
        execution_date_str = execution_date.strftime("%Y-%m-%d")
    except Exception as e:
        logging.error(f"Ошибка парсинга даты: {e}")
        await message.reply("Неверный формат даты в распознанном тексте.")
        return

    try:
        mess = await message.reply("Обработка задачи, подождите пару секунд...")
        answer = task.get_answer(task_name)
        print(answer)
        predicted_duration = int(re.findall(r'\d+', task.get_answer(answer))[0])
        await mess.delete()
    except Exception as e:
        predicted_duration = 60
        logging.error(f"Ошибка получения времени выполнения: {e}")

    await state.update_data(task_name=task_name, task_duration=predicted_duration,
                            execution_date=execution_date_str, from_voice=True)

    user_id = message.from_user.id
    start_end = find_available_time(user_id, execution_date, predicted_duration)
    if start_end[0] and start_end[1]:
        scheduled_time_str = f"{start_end[0]} - {start_end[1]}"
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("Назначить", callback_data="voice_set"),
            InlineKeyboardButton("Отмена", callback_data="voice_cancel")
        )
        await message.reply(
            f"Задача '{task_name}' займет {predicted_duration} минут с {start_end[0]} до {start_end[1]}.\n",
            reply_markup=keyboard
        )
    else:
        await message.reply("Нет свободного времени для выполнения этой задачи в выбранный день.")
        await state.finish()


@dp.message_handler(lambda message: message.text == "➕ Добавить задачу")
async def add_task_text(message: types.Message):
    await TaskCreation.waiting_for_task_name.set()
    await message.reply("Введите название задачи:")


@dp.message_handler(state=TaskCreation.waiting_for_task_name)
async def process_task_name(message: types.Message, state: FSMContext):
    task_name = message.text.strip()
    if not task_name:
        await message.reply("Название не может быть пустым. Введите название задачи:")
        return
    if "/tasks" in task_name or "📋 Список задач" in task_name or "/addtask" in task_name or "➕ Добавить задачу:" in task_name or "/voice_addtask" in task_name or "➕ Голосовой ввод" in task_name:
        await state.finish()
        await show_calendar(message=message, state=state)
        return

    try:
        mess = await message.reply("Обработка задачи, подождите пару секунд...")
        answer = task.get_answer(task_name)
        predicted_duration = int(re.findall(r'\d+', task.get_answer(answer))[0])
        await mess.delete()
    except Exception as e:
        predicted_duration = 60
        logging.error(f"Ошибка получения времени выполнения: {e}")

    await state.update_data(task_name=task_name, task_duration=predicted_duration)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("Назначить", callback_data="set"),
        InlineKeyboardButton("Отмена", callback_data="cancel")
    )
    await TaskCreation.waiting_for_duration_confirmation.set()
    await message.reply(f"Данная задача займет {predicted_duration} минут.", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data in ["set", "cancel"],
                           state=TaskCreation.waiting_for_duration_confirmation)
async def process_duration_confirmation_callback(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "cancel":
        await callback_query.message.delete()
        await state.finish()
    elif callback_query.data == "set":
        await TaskCreation.waiting_for_execution_date.set()
        today = datetime.date.today()
        await send_calendar(callback_query.message.chat.id, today.year, today.month, for_task_creation=True)
        await callback_query.message.delete()
    await callback_query.answer()


@dp.callback_query_handler(lambda c: c.data in ["voice_set", "voice_cancel"], state=TaskCreation.waiting_for_voice)
async def process_voice_duration_confirmation(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback_query.data == "voice_set":
        task_name = data.get("task_name")
        task_duration = data.get("task_duration")
        execution_date_str = data.get("execution_date")
        execution_date = datetime.datetime.strptime(execution_date_str, "%Y-%m-%d").date()
        user_id = callback_query.from_user.id
        start_end = find_available_time(user_id, execution_date, task_duration)
        if start_end[0] and start_end[1]:
            scheduled_time_str = f"{start_end[0]} - {start_end[1]}"
            cursor.execute("INSERT INTO tasks (user_id, name, execution_date, scheduled_time, completed) VALUES (?, ?, ?, ?, ?)",
                           (user_id, task_name, execution_date_str, scheduled_time_str, 0))
            conn.commit()
            await callback_query.answer(f"Задача '{task_name}' добавлена с {start_end[0]} до {start_end[1]}.", show_alert=True)
            await state.finish()
        else:
            await callback_query.answer("Нет свободного времени для выполнения этой задачи в выбранный день.", show_alert=True)
            await state.finish()
    elif callback_query.data == "voice_cancel":
        await TaskCreation.waiting_for_duration_modification.set()
        await callback_query.message.edit_text("Задача отменена")
        await callback_query.answer()
        await state.finish()


@dp.message_handler(state=TaskCreation.waiting_for_duration_modification)
async def process_duration_modification(message: types.Message, state: FSMContext):
    try:
        new_duration = int(message.text.strip())
        if new_duration <= 0:
            raise ValueError("Длительность должна быть положительной.")
    except ValueError:
        await message.reply("Пожалуйста, введите корректное число минут.")
        return
    print(2)
    data = await state.get_data()
    await state.update_data(task_duration=new_duration)

    if data.get("from_voice"):
        execution_date_str = data.get("execution_date")
        execution_date = datetime.datetime.strptime(execution_date_str, "%Y-%m-%d").date()
        user_id = message.from_user.id
        start_end = find_available_time(user_id, execution_date, new_duration)
        if start_end[0] and start_end[1]:
            scheduled_time_str = f"{start_end[0]} - {start_end[1]}"
            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton("Подходит", callback_data="voice_set"),
                InlineKeyboardButton("Изменить", callback_data="voice_cancel")
            )
            await message.reply(f"Новая длительность: {new_duration} минут. Время выполнения: {scheduled_time_str}. Устраивает ли вас это время?", reply_markup=keyboard)
            await state.finish()
        else:
            await message.reply("Нет свободного времени для выполнения этой задачи в выбранный день.")
            await state.finish()
    else:
        await TaskCreation.waiting_for_execution_date.set()
        today = datetime.date.today()
        await send_calendar(message.chat.id, today.year, today.month, for_task_creation=True)


@dp.message_handler(state=TaskCreation.waiting_for_execution_date)
async def process_execution_date_text(message: types.Message, state: FSMContext):
    today = datetime.date.today()
    await send_calendar(message.chat.id, today.year, today.month, for_task_creation=True)
    await message.reply("Пожалуйста, выберите дату выполнения задачи из календаря.")


def find_available_time(user_id, target_date, task_duration):
    busy_slots = []
    cursor.execute("SELECT start_time, end_time FROM schedule WHERE user_id = ? ORDER BY start_time", (user_id,))
    for row in cursor.fetchall():
        try:
            s = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M")
            e = datetime.datetime.strptime(row[1], "%Y-%m-%d %H:%M")
            if s.date() == target_date:
                busy_slots.append((s, e))
        except Exception as e:
            logging.error(f"Ошибка обработки расписания: {row}, {e}")
    cursor.execute("SELECT scheduled_time FROM tasks WHERE user_id = ?", (user_id,))
    for row in cursor.fetchall():
        try:
            parts = row[0].split(" - ")
            if len(parts) == 2:
                s = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                e = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M")
                if s.date() == target_date:
                    busy_slots.append((s, e))
        except Exception as e:
            logging.error(f"Ошибка обработки задачи: {row}, {e}")
    russian_day = get_russian_weekday(datetime.datetime.combine(target_date, datetime.time(0, 0)))
    couples = get_couples().get(russian_day, [])
    if couples:
        for couple in couples:
            time_range = couple["time"].replace("–", "-")
            parts = time_range.split("-")
            if len(parts) == 2:
                try:
                    start_str = parts[0].strip()
                    end_str = parts[1].strip()
                    s = datetime.datetime.combine(target_date, datetime.datetime.strptime(start_str, "%H:%M").time())
                    e = datetime.datetime.combine(target_date, datetime.datetime.strptime(end_str, "%H:%M").time())
                    busy_slots.append((s, e))
                except Exception as e:
                    logging.error(f"Ошибка обработки пары: {couple}, {e}")
    busy_slots.sort(key=lambda x: x[0])
    work_start = datetime.datetime.combine(target_date, datetime.time(9, 0))
    work_end = datetime.datetime.combine(target_date, datetime.time(23, 59))
    current = work_start
    task_delta = datetime.timedelta(minutes=task_duration)
    for slot in busy_slots:
        if current + task_delta <= slot[0]:
            return (current.strftime("%Y-%m-%d %H:%M"),
                    (current + task_delta).strftime("%Y-%m-%d %H:%M"))
        if current < slot[1]:
            current = slot[1]
    if current + task_delta <= work_end:
        return (current.strftime("%Y-%m-%d %H:%M"),
                (current + task_delta).strftime("%Y-%m-%d %H:%M"))
    previous_date = target_date - datetime.timedelta(days=1)
    if previous_date >= datetime.date.today():
        return find_available_time(user_id, previous_date, task_duration)
    else:
        return (None, None)


@dp.callback_query_handler(lambda c: c.data.startswith("day_"), state=TaskCreation.waiting_for_execution_date)
async def process_execution_date_callback(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        _, year, month, day = callback_query.data.split("_")
        selected_date = datetime.date(int(year), int(month), int(day))
    except Exception as e:
        await callback_query.answer("Неверный формат даты.", show_alert=True)
        return
    today = datetime.date.today()
    if selected_date < today:
        await callback_query.answer("Нельзя выбрать прошедшую дату.", show_alert=True)
        return
    user_id = callback_query.from_user.id
    data = await state.get_data()
    task_name = data.get("task_name")
    task_duration = data.get("task_duration")
    start_end = find_available_time(user_id, selected_date, task_duration)
    if start_end[0] and start_end[1]:
        scheduled_time_str = f"{start_end[0]} - {start_end[1]}"
        cursor.execute("INSERT INTO tasks (user_id, name, execution_date, scheduled_time, completed) VALUES (?, ?, ?, ?, ?)",
                       (user_id, task_name, selected_date, scheduled_time_str, 0))
        conn.commit()
        await callback_query.answer(f"Задача '{task_name}' добавлена в расписание с {start_end[0]} до {start_end[1]}.", show_alert=True)
    else:
        await callback_query.answer("Нет свободного времени для выполнения этой задачи в выбранный день.", show_alert=True)
        return
    await state.finish()
    await callback_query.answer()


def send_calendar(chat_id, year, month, for_task_creation=False):
    markup = generate_calendar_markup(year, month)
    if for_task_creation:
        header_text = "Выберите дату выполнения задачи:"
    else:
        header_text = f"\U0001F4C5 {year} - {month:02d}\nВыберите день:"
    return bot.send_message(chat_id, header_text, reply_markup=markup)


def generate_calendar_markup(year, month):
    markup = InlineKeyboardMarkup(row_width=7)
    header = f"\U0001F4C6 {datetime.date(year, month, 1).strftime('%B %Y')}"
    markup.add(InlineKeyboardButton(header, callback_data="ignore"))
    days_of_week = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    markup.add(*[InlineKeyboardButton(day, callback_data="ignore") for day in days_of_week])
    first_day = datetime.date(year, month, 1).weekday()
    days_in_month = (datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)).day if month < 12 else 31
    buttons = []
    for _ in range(first_day):
        buttons.append(InlineKeyboardButton(" ", callback_data="ignore"))
    for day in range(1, days_in_month + 1):
        buttons.append(InlineKeyboardButton(str(day), callback_data=f"day_{year}_{month}_{day}"))
    markup.add(*buttons)
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    markup.row(
        InlineKeyboardButton("← Назад", callback_data=f"month_{prev_year}_{prev_month}"),
        InlineKeyboardButton("Вперёд →", callback_data=f"month_{next_year}_{next_month}")
    )
    return markup


@dp.callback_query_handler(lambda c: c.data.startswith("month_"), state="*")
async def change_month(callback_query: types.CallbackQuery, state: FSMContext):
    _, year, month = callback_query.data.split("_")
    year, month = int(year), int(month)
    markup = generate_calendar_markup(year, month)
    current_state = await state.get_state()
    if current_state == TaskCreation.waiting_for_execution_date.state:
        header_text = "Выберите дату выполнения задачи:"
    else:
        header_text = f"\U0001F4C5 {year} - {month:02d}\nВыберите день:"
    await callback_query.message.edit_text(header_text, reply_markup=markup)
    await callback_query.answer()


@dp.message_handler(commands=['tasks'], state="*")
async def show_calendar(message: types.Message, state: FSMContext = None):
    today = datetime.date.today()
    await send_calendar(message.chat.id, today.year, today.month, for_task_creation=False)


@dp.message_handler(lambda message: message.text == "📋 Список задач", state="*")
async def show_calendar_text(message: types.Message, state: FSMContext = None):
    today = datetime.date.today()
    await send_calendar(message.chat.id, today.year, today.month, for_task_creation=False)


@dp.callback_query_handler(lambda c: c.data.startswith("day_"), state=None)
async def show_tasks_for_day(callback_query: types.CallbackQuery):
    try:
        _, year, month, day = callback_query.data.split("_")
        year, month, day = int(year), int(month), int(day)
    except Exception as e:
        await callback_query.answer("Неверный формат даты.", show_alert=True)
        return
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    selected_date = datetime.date(year, month, day)
    user_id = callback_query.from_user.id
    cursor.execute("""
        SELECT id, name, scheduled_time, completed FROM tasks 
        WHERE user_id = ? AND (execution_date = ? OR DATE(scheduled_time) = ?)
        ORDER BY scheduled_time
    """, (user_id, date_str, date_str))
    tasks = cursor.fetchall()
    markup = InlineKeyboardMarkup()
    for task in tasks:
        task_id, task_name, scheduled_time, completed = task
        try:
            parts = scheduled_time.split(" - ")
            if len(parts) == 2:
                start_time = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M").strftime("%H:%M")
                end_time = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M").strftime("%H:%M")
                time_range_str = f"{start_time} - {end_time}"
            else:
                time_range_str = ""
        except Exception as e:
            time_range_str = ""
        status_icon = "✅" if completed else "❌"
        toggle_button_text = f"{status_icon} {task_name}"
        toggle_callback_data = f"toggle_task_{task_id}_{year}_{month}_{day}"
        delete_callback_data = f"delete_task_{task_id}_{year}_{month}_{day}"
        markup.add(InlineKeyboardButton(toggle_button_text, callback_data=toggle_callback_data))
        markup.row(
            InlineKeyboardButton(time_range_str, callback_data=f"edit_time_{task_id}_{year}_{month}_{day}"),
            InlineKeyboardButton("🗑️", callback_data=delete_callback_data)
        )
    markup.add(InlineKeyboardButton("🔙 Назад", callback_data=f"month_{year}_{month}"))
    couples_texts = []
    russian_day = get_russian_weekday(selected_date)
    couples = get_couples().get(russian_day, [])
    for couple in couples:
        time_range = couple["time"].replace("–", "-")
        parts = time_range.split("-")
        if len(parts) == 2:
            try:
                start_time_str = parts[0].strip()
                end_time_str = parts[1].strip()
                couples_texts.append(f"🔔 {couple['subject']} ({start_time_str} - {end_time_str})")
            except Exception as e:
                logging.error(f"Ошибка обработки пары: {couple}, {e}")
    header_text = f"\U0001F4C5 Задачи на {date_str}:\n(нажмите на первую кнопку для изменения статуса; на время для редактирования времени)"
    if couples_texts:
        header_text += "\n\nПары:\n" + "\n".join(couples_texts)
    await callback_query.message.edit_text(header_text, reply_markup=markup)
    await callback_query.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("edit_time_"))
async def edit_task_time(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        _, _, task_id, year, month, day = callback_query.data.split("_")
        task_id = int(task_id)
        year = int(year)
        month = int(month)
        day = int(day)
    except Exception as e:
        print(e)
        await callback_query.answer("Ошибка в данных задачи для редактирования времени", show_alert=True)
        return

    user_id = callback_query.from_user.id
    cursor.execute("SELECT scheduled_time FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    result = cursor.fetchone()
    if not result:
        await callback_query.answer("Задача не найдена", show_alert=True)
        return
    scheduled_time = result[0]
    try:
        parts = scheduled_time.split(" - ")
        old_start = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
        old_end = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M")
    except Exception as e:
        await callback_query.answer("Невозможно обработать время задачи", show_alert=True)
        return

    await state.update_data(edit_task_id=task_id, edit_year=year, edit_month=month, edit_day=day,
                            old_start=old_start.strftime("%Y-%m-%d %H:%M"),
                            old_end=old_end.strftime("%Y-%m-%d %H:%M"))
    await callback_query.message.answer("Введите новое время начала задачи в формате HH:MM (например, 14:00):")
    await TaskTimeModification.waiting_for_new_time.set()
    await callback_query.answer()


@dp.message_handler(state=TaskTimeModification.waiting_for_new_time)
async def process_new_time(message: types.Message, state: FSMContext):
    new_time_str = message.text.strip()
    try:
        new_time = datetime.datetime.strptime(new_time_str, "%H:%M").time()
    except Exception as e:
        await message.reply("Неверный формат времени. Введите время в формате HH:MM (например, 14:00).")
        return
    data = await state.get_data()
    try:
        task_id = data.get("edit_task_id")
        year = int(data.get("edit_year"))
        month = int(data.get("edit_month"))
        day = int(data.get("edit_day"))
        old_start_str = data.get("old_start")
        old_end_str = data.get("old_end")
        old_start = datetime.datetime.strptime(old_start_str, "%Y-%m-%d %H:%M")
        old_end = datetime.datetime.strptime(old_end_str, "%Y-%m-%d %H:%M")
    except Exception as e:
        await message.reply("Ошибка обработки данных задачи для редактирования времени.")
        await state.finish()
        return

    duration = old_end - old_start
    new_start = datetime.datetime.combine(old_start.date(), new_time)
    new_end = new_start + duration
    delta = new_start - old_start

    user_id = message.from_user.id
    date_str = new_start.strftime("%Y-%m-%d")
    new_scheduled_time = f"{new_start.strftime('%Y-%m-%d %H:%M')} - {new_end.strftime('%Y-%m-%d %H:%M')}"
    cursor.execute("UPDATE tasks SET scheduled_time = ? WHERE id = ? AND user_id = ?",
                   (new_scheduled_time, task_id, user_id))

    cursor.execute("""
        SELECT id, scheduled_time FROM tasks 
        WHERE user_id = ? AND execution_date = ? 
        ORDER BY scheduled_time
    """, (user_id, date_str))
    tasks = cursor.fetchall()

    for t in tasks:
        tid, sched = t
        if tid == task_id:
            continue
        try:
            parts = sched.split(" - ")
            t_start = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
            t_end = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M")
        except Exception as e:
            continue
        if t_start > old_start:
            new_t_start = t_start + delta
            new_t_end = t_end + delta
            new_sched = f"{new_t_start.strftime('%Y-%m-%d %H:%M')} - {new_t_end.strftime('%Y-%m-%d %H:%M')}"
            cursor.execute("UPDATE tasks SET scheduled_time = ? WHERE id = ? AND user_id = ?",
                           (new_sched, tid, user_id))
    conn.commit()
    await message.reply("Время задачи изменено, остальные задачи сдвинуты.")
    await state.finish()
    show_tasks_for_day_callback(message.chat.id, date_str, user_id)


def show_tasks_for_day_callback(chat_id, date_str, user_id):
    try:
        selected_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception as e:
        return
    cursor.execute("""
        SELECT id, name, scheduled_time, completed FROM tasks 
        WHERE user_id = ? AND (execution_date = ? OR DATE(scheduled_time) = ?)
        ORDER BY scheduled_time
    """, (user_id, date_str, date_str))
    tasks = cursor.fetchall()
    markup = InlineKeyboardMarkup()
    for task in tasks:
        task_id, task_name, scheduled_time, completed = task
        try:
            parts = scheduled_time.split(" - ")
            if len(parts) == 2:
                start_time = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M").strftime("%H:%M")
                end_time = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M").strftime("%H:%M")
                time_range_str = f"{start_time} - {end_time}"
            else:
                time_range_str = ""
        except Exception as e:
            time_range_str = ""
        status_icon = "✅" if completed else "❌"
        toggle_button_text = f"{status_icon} {task_name}"
        toggle_callback_data = f"toggle_task_{task_id}_{selected_date.year}_{selected_date.month}_{selected_date.day}"
        delete_callback_data = f"delete_task_{task_id}_{selected_date.year}_{selected_date.month}_{selected_date.day}"
        markup.add(InlineKeyboardButton(toggle_button_text, callback_data=toggle_callback_data))
        markup.row(
            InlineKeyboardButton(time_range_str, callback_data=f"edit_time_{task_id}_{selected_date.year}_{selected_date.month}_{selected_date.day}"),
            InlineKeyboardButton("🗑️", callback_data=delete_callback_data)
        )

    markup.add(InlineKeyboardButton("🔙 Назад", callback_data=f"month_{selected_date.year}_{selected_date.month}"))

    couples_texts = []
    russian_day = get_russian_weekday(selected_date)
    couples = get_couples().get(russian_day, [])
    for couple in couples:
        time_range = couple["time"].replace("–", "-")
        parts = time_range.split("-")
        if len(parts) == 2:
            try:
                start_time_str = parts[0].strip()
                end_time_str = parts[1].strip()
                couples_texts.append(f"🔔 {couple['subject']} ({start_time_str} - {end_time_str})")
            except Exception as e:
                logging.error(f"Ошибка обработки пары: {couple}, {e}")
    header_text = f"\U0001F4C5 Задачи на {date_str}:\n(нажмите на первую кнопку для изменения статуса; на время для редактирования)"
    if couples_texts:
        header_text += "\n\nПары:\n" + "\n".join(couples_texts)
    bot.send_message(chat_id, header_text, reply_markup=markup)


@dp.callback_query_handler(lambda c: c.data.startswith("toggle_task_"))
async def toggle_task_status(callback_query: types.CallbackQuery):
    try:
        parts = callback_query.data.split("_")
        task_id = int(parts[2])
        year = int(parts[3])
        month = int(parts[4])
        day = int(parts[5])
    except Exception as e:
        await callback_query.answer("Ошибка в данных задачи", show_alert=True)
        return
    user_id = callback_query.from_user.id
    cursor.execute("SELECT completed FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    result = cursor.fetchone()
    if not result:
        await callback_query.answer("Задача не найдена", show_alert=True)
        return
    current_status = result[0]
    new_status = 0 if current_status else 1
    cursor.execute("UPDATE tasks SET completed = ? WHERE id = ? AND user_id = ?", (new_status, task_id, user_id))
    conn.commit()
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    cursor.execute("""
        SELECT id, name, scheduled_time, completed FROM tasks 
        WHERE user_id = ? AND (execution_date = ? OR DATE(scheduled_time) = ?)
        ORDER BY scheduled_time
    """, (user_id, date_str, date_str))
    tasks = cursor.fetchall()
    markup = InlineKeyboardMarkup()
    for task in tasks:
        tid, tname, scheduled_time, completed = task
        try:
            parts = scheduled_time.split(" - ")
            if len(parts) == 2:
                start_time = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M").strftime("%H:%M")
                end_time = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M").strftime("%H:%M")
                time_range_str = f"{start_time} - {end_time}"
            else:
                time_range_str = ""
        except Exception as e:
            time_range_str = ""
        status_icon = "✅" if completed else "❌"
        toggle_button_text = f"{status_icon} {tname}"
        toggle_callback_data = f"toggle_task_{tid}_{year}_{month}_{day}"
        delete_callback_data = f"delete_task_{tid}_{year}_{month}_{day}"
        markup.add(InlineKeyboardButton(toggle_button_text, callback_data=toggle_callback_data))
        markup.row(
            InlineKeyboardButton(time_range_str, callback_data=f"edit_time_{tid}_{year}_{month}_{day}"),
            InlineKeyboardButton("🗑️", callback_data=delete_callback_data)
        )

    markup.add(InlineKeyboardButton("🔙 Назад", callback_data=f"month_{year}_{month}"))

    selected_date = datetime.date(year, month, day)
    couples_texts = []
    russian_day = get_russian_weekday(selected_date)
    couples = get_couples().get(russian_day, [])
    for couple in couples:
        time_range = couple["time"].replace("–", "-")
        parts = time_range.split("-")
        if len(parts) == 2:
            try:
                start_time_str = parts[0].strip()
                end_time_str = parts[1].strip()
                couples_texts.append(f"🔔 {couple['subject']} ({start_time_str} - {end_time_str})")
            except Exception as e:
                logging.error(f"Ошибка обработки пары: {couple}, {e}")
    header_text = f"\U0001F4C5 Задачи на {year:04d}-{month:02d}-{day:02d}:\n(нажмите на первую кнопку для изменения статуса)"
    if couples_texts:
        header_text += "\n\nПары:\n" + "\n".join(couples_texts)
    await callback_query.message.edit_text(header_text, reply_markup=markup)
    await callback_query.answer("Статус задачи обновлен")


@dp.callback_query_handler(lambda c: c.data.startswith("delete_task_"))
async def delete_task(callback_query: types.CallbackQuery):
    try:
        parts = callback_query.data.split("_")
        task_id = int(parts[2])
        year = int(parts[3])
        month = int(parts[4])
        day = int(parts[5])
    except Exception as e:
        await callback_query.answer("Ошибка в данных задачи", show_alert=True)
        return
    user_id = callback_query.from_user.id
    cursor.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    conn.commit()
    await callback_query.answer("Задача удалена")
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    cursor.execute("""
        SELECT id, name, scheduled_time, completed FROM tasks 
        WHERE user_id = ? AND (execution_date = ? OR DATE(scheduled_time) = ?)
        ORDER BY scheduled_time
    """, (user_id, date_str, date_str))
    tasks = cursor.fetchall()
    markup = InlineKeyboardMarkup()
    for task in tasks:
        tid, tname, scheduled_time, completed = task
        try:
            parts = scheduled_time.split(" - ")
            if len(parts) == 2:
                start_time = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M").strftime("%H:%M")
                end_time = datetime.datetime.strptime(parts[1], "%Y-%m-%d %H:%M").strftime("%H:%M")
                time_range_str = f"{start_time} - {end_time}"
            else:
                time_range_str = ""
        except Exception as e:
            time_range_str = ""
        status_icon = "✅" if completed else "❌"
        toggle_button_text = f"{status_icon} {tname}"
        toggle_callback_data = f"toggle_task_{tid}_{year}_{month}_{day}"
        delete_callback_data = f"delete_task_{tid}_{year}_{month}_{day}"
        markup.add(InlineKeyboardButton(toggle_button_text, callback_data=toggle_callback_data))
        markup.row(
            InlineKeyboardButton(time_range_str, callback_data=f"edit_time_{tid}_{year}_{month}_{day}"),
            InlineKeyboardButton("🗑️", callback_data=delete_callback_data)
        )
    markup.add(InlineKeyboardButton("🔙 Назад", callback_data=f"month_{year}_{month}"))
    selected_date = datetime.date(year, month, day)
    couples_texts = []
    russian_day = get_russian_weekday(selected_date)
    couples = get_couples().get(russian_day, [])
    for couple in couples:
        time_range = couple["time"].replace("–", "-")
        parts = time_range.split("-")
        if len(parts) == 2:
            try:
                start_time_str = parts[0].strip()
                end_time_str = parts[1].strip()
                couples_texts.append(f"🔔 {couple['subject']} ({start_time_str} - {end_time_str})")
            except Exception as e:
                logging.error(f"Ошибка об2работки пары: {couple}, {e}")
    header_text = f"\U0001F4C5 Задачи на {date_str}:\n(нажмите на первую кнопку для изменения статуса)"
    if couples_texts:
        header_text += "\n\nПары:\n" + "\n".join(couples_texts)
    await callback_query.message.edit_text(header_text, reply_markup=markup)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
