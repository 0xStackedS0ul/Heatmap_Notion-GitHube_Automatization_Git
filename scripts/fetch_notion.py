import os
import json
from notion_client import Client
from collections import defaultdict
from datetime import datetime, date

# Отримуємо змінні середовища
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise ValueError("Потрібно встановити NOTION_TOKEN та DATABASE_ID в Secrets")

notion = Client(auth=NOTION_TOKEN)


def get_today_str():
    return date.today().isoformat()


def fetch_all_database_pages():
    """Витягує всі сторінки для побудови Heatmap"""
    results = []
    has_more = True
    start_cursor = None
    print("⏳ Завантаження історії для Heatmap...")

    while has_more:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            start_cursor=start_cursor
        )
        results.extend(response["results"])
        has_more = response["has_more"]
        start_cursor = response["next_cursor"]

    return results


def generate_heatmap_data(pages):
    """Генерує JSON на основі Number_of_intensity"""
    counts = defaultdict(int)

    for page in pages:
        props = page["properties"]

        # 1. Отримуємо дату
        # Припускаємо, що є колонка "Date". Якщо немає, беремо час створення
        date_val = None
        if "Date" in props and props["Date"]["date"]:
            date_val = props["Date"]["date"]["start"]
        else:
            date_val = page["created_time"]

        day = date_val.split("T")[0]

        # 2. Отримуємо інтенсивність
        intensity = 0
        if "Number_of_intensity" in props and props["Number_of_intensity"]["number"]:
            intensity = props["Number_of_intensity"]["number"]

        # Додаємо до суми за цей день
        counts[day] += intensity

    return dict(counts)


def create_daily_habits(all_pages):
    """
    Знаходить шаблони (Template_Checkbox) і створює нові записи на СЬОГОДНІ,
    якщо їх ще немає.
    """
    today = get_today_str()
    print(f"🔄 Перевірка необхідності створення звичок на {today}...")

    # 1. Знаходимо шаблони
    templates = []
    # 2. Знаходимо, які звички вже створені на сьогодні (щоб не дублювати)
    created_today_names = set()

    for page in all_pages:
        props = page["properties"]

        # Перевіряємо, чи це шаблон
        is_template = False
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            is_template = True
            templates.append(page)

        # Перевіряємо дату запису
        page_date = None
        if "Date" in props and props["Date"]["date"]:
            page_date = props["Date"]["date"]["start"]

        # Отримуємо назву
        habit_name = ""
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            habit_name = props["Name_Hebits"]["title"][0]["plain_text"]

        # Якщо запис за сьогодні і він НЕ є шаблоном (або навіть якщо є), запам'ятовуємо ім'я
        if page_date == today and habit_name:
            created_today_names.add(habit_name)

    print(f"Found {len(templates)} templates.")

    # 3. Створюємо нові записи
    for template in templates:
        props = template["properties"]

        # Отримуємо назву шаблону
        name_list = props["Name_Hebits"]["title"]
        if not name_list: continue
        habit_name = name_list[0]["plain_text"]

        # Якщо вже є запис з такою назвою за сьогодні — пропускаємо
        if habit_name in created_today_names:
            print(f"⏭️ {habit_name} вже існує на сьогодні.")
            continue

        # Отримуємо Max intensity з шаблону
        max_intensity = None
        if "Max_Number_of_intensity" in props and props["Max_Number_of_intensity"]["number"]:
            max_intensity = props["Max_Number_of_intensity"]["number"]

        # Створення нової сторінки
        new_page_props = {
            "Name_Hebits": {
                "title": [{"text": {"content": habit_name}}]
            },
            "Date": {
                "date": {"start": today}
            },
            "Enabled": {
                "checkbox": False  # Чекбокс знято
            },
            "Template_Checkbox": {
                "checkbox": False  # Це копія, не шаблон
            },
            # Скидаємо інтенсивність на 0
            "Number_of_intensity": {
                "number": None
            }
        }

        # Якщо є Max intensity, переносимо його
        if max_intensity is not None:
            new_page_props["Max_Number_of_intensity"] = {"number": max_intensity}

        try:
            notion.pages.create(
                parent={"database_id": DATABASE_ID},
                properties=new_page_props
            )
            print(f"✅ Створено: {habit_name}")
        except Exception as e:
            print(f"❌ Помилка створення {habit_name}: {e}")


def main():
    # 1. Завантажуємо все
    pages = fetch_all_database_pages()

    # 2. Обробляємо Heatmap
    data = generate_heatmap_data(pages)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("💾 data.json оновлено")

    # 3. Створюємо нові завдання на день
    create_daily_habits(pages)


if __name__ == "__main__":
    main()