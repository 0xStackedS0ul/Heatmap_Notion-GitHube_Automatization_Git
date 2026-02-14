import os
import json
from notion_client import Client
from collections import defaultdict
from datetime import datetime, date

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise ValueError("Secrets NOTION_TOKEN and DATABASE_ID are required")

notion = Client(auth=NOTION_TOKEN)


def get_today_str():
    return date.today().isoformat()


def fetch_all_database_pages():
    results = []
    has_more = True
    start_cursor = None
    print("⏳ Завантаження даних з Notion...")

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
    # Heatmap тепер зберігає "Бали ефективності" (сума відсотків)
    heatmap_scores = defaultdict(float)
    # Stats зберігає реальні суми повторень (для списку внизу)
    habit_raw_stats = defaultdict(int)

    print("🔄 Розрахунок інтенсивності (нормалізація)...")

    for page in pages:
        props = page["properties"]
        page_id = page["id"]

        # --- 1. Отримання даних ---
        habit_name = "Unknown"
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            habit_name = props["Name_Hebits"]["title"][0]["plain_text"]

        date_val = None
        if "Date" in props and props["Date"]["date"]:
            date_val = props["Date"]["date"]["start"]
        else:
            date_val = page["created_time"]
        day = date_val.split("T")[0]

        # Поточне значення
        intensity = 0
        if "Number_of_intensity" in props and props["Number_of_intensity"]["number"]:
            intensity = props["Number_of_intensity"]["number"]

        # Максимальне значення (Ціль)
        max_intensity = 0
        if "Max_Number_of_intensity" in props and props["Max_Number_of_intensity"]["number"]:
            max_intensity = props["Max_Number_of_intensity"]["number"]

        is_enabled = False
        if "Enabled" in props and props["Enabled"]["checkbox"]:
            is_enabled = True

        is_template = False
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            is_template = True

        # --- 2. Логіка розрахунку ---
        if not is_template and intensity > 0:

            # А. Розрахунок балів для графіку (Heatmap)
            # Якщо є Максимум -> рахуємо відсоток (напр. 25/50 = 50 балів)
            if max_intensity > 0:
                score = (intensity / max_intensity) * 100
            else:
                # Якщо Максимуму немає, але звичка зроблена -> даємо фіксовані 100 балів
                score = 100.0

            # Округлимо до 1 знаку
            heatmap_scores[day] += round(score, 1)

            # Б. Розрахунок статистики (сумуємо реальні повтори)
            habit_raw_stats[habit_name] += intensity

            print(f"   ➕ {habit_name}: {intensity}/{max_intensity} -> {score:.1f}% ({day})")

            # --- 3. Оновлення статусу (Enabled) ---
            if not is_enabled:
                try:
                    notion.pages.update(
                        page_id=page_id,
                        properties={"Enabled": {"checkbox": True}}
                    )
                    print(f"   ✅ Відмічено виконаним: {habit_name}")
                except Exception as e:
                    print(f"   ❌ Помилка оновлення {habit_name}: {e}")

    return {
        "heatmap": dict(heatmap_scores),
        "stats": dict(habit_raw_stats)
    }


def create_daily_habits(all_pages):
    today = get_today_str()
    print(f"📅 Перевірка шаблонів на {today}...")

    templates = []
    created_today_names = set()

    for page in all_pages:
        props = page["properties"]
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            templates.append(page)

        p_date = props["Date"]["date"]["start"] if (props.get("Date") and props["Date"]["date"]) else None

        h_name = ""
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            h_name = props["Name_Hebits"]["title"][0]["plain_text"]

        if p_date == today and h_name:
            created_today_names.add(h_name)

    for template in templates:
        props = template["properties"]
        name_list = props["Name_Hebits"]["title"]
        if not name_list: continue
        habit_name = name_list[0]["plain_text"]

        if habit_name in created_today_names:
            continue

        max_val = None
        if "Max_Number_of_intensity" in props and props["Max_Number_of_intensity"]["number"]:
            max_val = props["Max_Number_of_intensity"]["number"]

        new_props = {
            "Name_Hebits": {"title": [{"text": {"content": habit_name}}]},
            "Date": {"date": {"start": today}},
            "Enabled": {"checkbox": False},
            "Template_Checkbox": {"checkbox": False},
            "Number_of_intensity": {"number": None}
        }
        if max_val is not None:
            new_props["Max_Number_of_intensity"] = {"number": max_val}

        try:
            notion.pages.create(
                parent={"database_id": DATABASE_ID},
                properties=new_props
            )
            print(f"🆕 Створено на сьогодні: {habit_name}")
        except Exception as e:
            print(f"❌ Error creating {habit_name}: {e}")


def main():
    pages = fetch_all_database_pages()
    full_data = process_history_and_update(pages)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2, ensure_ascii=False)
    print("💾 data.json saved (Normalized Scores)")

    create_daily_habits(pages)


if __name__ == "__main__":
    main()