import re
import json


def get_couples():
    text = """
    **Понедельник:**
    1. Линейная алгебра: 9:00–10:30.
    2. Геометрия: 10:50–12:30.
    3. Физика: 12:50–14:20.
    4. Иностранный язык: 14:40–16:10.
    
    **Вторник:**
    1. Алгоритмы и структуры данных: 9:00–10:30.
    2. Программирование на Python: 10:50–12:30.
    3. Основы искусственного интеллекта: 13:00–14:30.
    4. Проектная работа: 15:00–16:30.
    
    **Среда:**
    1. Математический анализ: 9:00–10:30.
    2. Дискретная математика: 10:50–12:30.
    3. Теория вероятностей и статистика: 13:00–14:30.
    4. Семинар по программированию: 15:00–16:30.
    
    **Четверг:**
    1. Компьютерная графика: 9:00–10:30.
    2. Базы данных: 10:50–12:30.
    3. Сетевые технологии: 13:00–14:30.
    4. Робототехника и автоматизация: 15:00–16:30.
    
    **Пятница:**
    1. Операционные системы: 9:00–10:30.
    2. Безопасность информационных систем: 10:50–12:30.
    3. Веб-разработка: 13:00–14:30.
    4. Работа над групповым проектом: 15:00–16:30.
    """

    schedule = {}

    day_pattern = r"\*\*(.+?):\*\*(.*?)(?=\*\*|$)"
    days = re.findall(day_pattern, text, flags=re.DOTALL)

    for day, content in days:
        day = day.strip()
        lessons = []
        lesson_pattern = r"\d+\.\s*(.+?):\s*([0-9]{1,2}:[0-9]{2}–[0-9]{1,2}:[0-9]{2})\."
        for subject, time in re.findall(lesson_pattern, content):
            lessons.append({
                "subject": subject.strip(),
                "time": time.strip()
            })
        schedule[day] = lessons

    return schedule
