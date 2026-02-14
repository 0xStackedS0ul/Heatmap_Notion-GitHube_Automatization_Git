import os
import json
from notion_client import Client
from collections import defaultdict
from datetime import datetime, date, timedelta

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise ValueError("Secrets NOTION_TOKEN and DATABASE_ID are required")

notion = Client(auth=NOTION_TOKEN)


def get_today_str():
    # Fix: GitHub Actions працює в UTC. Додаємо 2 години (або 3 влітку),
    # щоб "сьогодні" відповідало реальному дню в Україні, якщо скрипт запускається вночі.
    # Це гарантує, що о 01:00 ночі скрипт вже буде знати, що настав новий день.
    ukraine_time = datetime.utcnow() + timedelta(hours=2)
    return ukraine_time.strftime("%Y-%m-%d")


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
    heatmap_scores = defaultdict(float)
    habit_raw_stats = defaultdict(int)

    print("🔄 Розрахунок інтенсивності...")

    for page in pages:
        props = page["properties"]
        page_id = page["id"]

        habit_name = "Unknown"
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            habit_name = props["Name_Hebits"]["title"][0]["plain_text"]

        date_val = None
        if "Date" in props and props["Date"]["date"]:
            date_val = props["Date"]["date"]["start"]
        else:
            date_val = page["created_time"]
        day = date_val.split("T")[0]

        intensity = 0
        if "Number_of_intensity" in props and props["Number_of_intensity"]["number"]:
            intensity = props["Number_of_intensity"]["number"]

        max_intensity = 0
        if "Max_Number_of_intensity" in props and props["Max_Number_of_intensity"]["number"]:
            max_intensity = props["Max_Number_of_intensity"]["number"]

        is_enabled = False
        if "Enabled" in props and props["Enabled"]["checkbox"]:
            is_enabled = True

        is_template = False
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            is_template = True

        if not is_template and intensity > 0:

            if max_intensity > 0:
                score = (intensity / max_intensity) * 100
            else:
                score = 100.0

            heatmap_scores[day] += round(score, 1)
            habit_raw_stats[habit_name] += intensity

            print(f"   ➕ {habit_name}: {intensity}/{max_intensity} -> {score:.1f}% ({day})")

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
    print(f"📅 Перевірка на дату: {today} (UA Time)")

    templates = []
    created_today_names = set()

    # 1. Шукаємо шаблони та вже існуючі записи за СЬОГОДНІ
    for page in all_pages:
        props = page["properties"]

        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            templates.append(page)

        # Перевіряємо дату існуючого запису
        p_date = None
        if "Date" in props and props["Date"]["date"]:
            p_date = props["Date"]["date"]["start"]

        h_name = ""
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            h_name = props["Name_Hebits"]["title"][0]["plain_text"]

        # Якщо запис з такою назвою вже є за сьогодні - запам'ятовуємо
        if p_date == today and h_name:
            created_today_names.add(h_name)

    # 2. Створюємо відсутні
    for template in templates:
        props = template["properties"]
        name_list = props["Name_Hebits"]["title"]
        if not name_list: continue
        habit_name = name_list[0]["plain_text"]

        # Якщо вже є -> пропускаємо
        if habit_name in created_today_names:
            print(f"   ⏭️ {habit_name} вже існує на сьогодні")
            continue

        max_val = None
        if "Max_Number_of_intensity" in props and props["Max_Number_of_intensity"]["number"]:
            max_val = props["Max_Number_of_intensity"]["number"]

        new_props = {
            "Name_Hebits": {"title": [{"text": {"content": habit_name}}]},
            "Date": {"date": {"start": today}},
            "Enabled": {"checkbox": False},
            "Template_Checkbox": {"checkbox": False},
            # ЗМІНА: Ставимо 0 замість пустоти
            "Number_of_intensity": {"number": 0}
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
    print("💾 data.json saved")

    create_daily_habits(pages)


if __name__ == "__main__":
    main()