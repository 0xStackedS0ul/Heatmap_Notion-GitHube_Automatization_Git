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
    """Витягує всі сторінки"""
    results = []
    has_more = True
    start_cursor = None
    print("⏳ Завантаження історії з Notion...")

    while has_more:
        response = notion.databases.query(
            database_id=DATABASE_ID,
            start_cursor=start_cursor
        )
        results.extend(response["results"])
        has_more = response["has_more"]
        start_cursor = response["next_cursor"]

    return results


def process_history_and_update(pages):
    """
    1. Генерує дані для Heatmap (дати).
    2. Генерує статистику по звичках (назва -> сума).
    3. Оновлює Notion: ставить Enabled=True для виконаних завдань.
    """
    heatmap_counts = defaultdict(int)
    habit_stats = defaultdict(int)

    print("🔄 Обробка даних та оновлення статусів...")

    for page in pages:
        props = page["properties"]
        page_id = page["id"]

        # --- 1. Отримуємо дані ---

        # Назва звички
        habit_name = "Unknown"
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            habit_name = props["Name_Hebits"]["title"][0]["plain_text"]

        # Дата
        date_val = None
        if "Date" in props and props["Date"]["date"]:
            date_val = props["Date"]["date"]["start"]
        else:
            date_val = page["created_time"]
        day = date_val.split("T")[0]

        # Інтенсивність
        intensity = 0
        if "Number_of_intensity" in props and props["Number_of_intensity"]["number"]:
            intensity = props["Number_of_intensity"]["number"]

        # Статус Enabled
        is_enabled = False
        if "Enabled" in props and props["Enabled"]["checkbox"]:
            is_enabled = True

        # Чи це шаблон?
        is_template = False
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            is_template = True

        # --- 2. Логіка агрегації (тільки якщо не шаблон) ---
        if not is_template:
            # Heatmap (сума інтенсивності по днях)
            heatmap_counts[day] += intensity

            # Stats (сума інтенсивності по звичках)
            if intensity > 0:
                habit_stats[habit_name] += intensity

            # --- 3. Логіка оновлення Notion (Problem 2) ---
            # Якщо є інтенсивність (зроблено), але не стоїть галочка Enabled -> ставимо її
            if intensity > 0 and not is_enabled:
                try:
                    print(f"   👉 Маркуємо як виконане: {habit_name} ({day})")
                    notion.pages.update(
                        page_id=page_id,
                        properties={"Enabled": {"checkbox": True}}
                    )
                except Exception as e:
                    print(f"   ❌ Помилка оновлення {habit_name}: {e}")

    # Формуємо фінальний об'єкт для JSON
    return {
        "heatmap": dict(heatmap_counts),
        "stats": dict(habit_stats)
    }


def create_daily_habits(all_pages):
    """Створює нові звички на сьогодні з шаблонів"""
    today = get_today_str()
    print(f"📅 Перевірка шаблонів на {today}...")

    templates = []
    created_today_names = set()

    # Пошук шаблонів та вже створених записів
    for page in all_pages:
        props = page["properties"]

        # Це шаблон?
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            templates.append(page)

        # Це запис за сьогодні?
        page_date = None
        if "Date" in props and props["Date"]["date"]:
            page_date = props["Date"]["date"]["start"]

        habit_name = ""
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            habit_name = props["Name_Hebits"]["title"][0]["plain_text"]

        if page_date == today and habit_name:
            created_today_names.add(habit_name)

    # Створення нових
    for template in templates:
        props = template["properties"]
        name_list = props["Name_Hebits"]["title"]
        if not name_list: continue
        habit_name = name_list[0]["plain_text"]

        if habit_name in created_today_names:
            continue

        max_intensity = None
        if "Max_Number_of_intensity" in props and props["Max_Number_of_intensity"]["number"]:
            max_intensity = props["Max_Number_of_intensity"]["number"]

        new_page_props = {
            "Name_Hebits": {"title": [{"text": {"content": habit_name}}]},
            "Date": {"date": {"start": today}},
            "Enabled": {"checkbox": False},
            "Template_Checkbox": {"checkbox": False},
            "Number_of_intensity": {"number": None}  # Пусто, щоб користувач ввів
        }

        if max_intensity is not None:
            new_page_props["Max_Number_of_intensity"] = {"number": max_intensity}

        try:
            notion.pages.create(
                parent={"database_id": DATABASE_ID},
                properties=new_page_props
            )
            print(f"✅ Створено нове завдання: {habit_name}")
        except Exception as e:
            print(f"❌ Помилка створення {habit_name}: {e}")


def main():
    # 1. Завантажуємо
    pages = fetch_all_database_pages()

    # 2. Обробляємо (оновлюємо Notion + генеруємо статистику)
    full_data = process_history_and_update(pages)

    # 3. Зберігаємо JSON (нову структуру)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2, ensure_ascii=False)
    print("💾 data.json успішно оновлено")

    # 4. Створюємо нові на завтра/сьогодні
    create_daily_habits(pages)


if __name__ == "__main__":
    main()