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


def get_today_date_obj():
    # Час по Києву (UTC+2 / UTC+3)
    return (datetime.utcnow() + timedelta(hours=2)).date()


def get_today_str():
    return get_today_date_obj().strftime("%Y-%m-%d")


def calculate_streaks(dates_list):
    """
    Рахує поточний та найкращий стрік на основі списку дат (рядків YYYY-MM-DD).
    """
    if not dates_list:
        return 0, 0

    # Сортуємо унікальні дати
    sorted_dates = sorted(list(set([
        datetime.strptime(d, "%Y-%m-%d").date() for d in dates_list
    ])))

    if not sorted_dates:
        return 0, 0

    today = get_today_date_obj()
    current_streak = 0
    best_streak = 0
    temp_streak = 0

    # 1. Рахуємо Best Streak (проходимо по всій історії)
    for i in range(len(sorted_dates)):
        if i == 0:
            temp_streak = 1
        else:
            delta = (sorted_dates[i] - sorted_dates[i - 1]).days
            if delta == 1:
                temp_streak += 1
            else:
                best_streak = max(best_streak, temp_streak)
                temp_streak = 1
    best_streak = max(best_streak, temp_streak)

    # 2. Рахуємо Current Streak (від кінця до початку)
    # Перевіряємо, чи останній запис був сьогодні або вчора
    last_date = sorted_dates[-1]
    diff_from_today = (today - last_date).days

    if diff_from_today > 1:
        # Якщо останній запис був позавчора або раніше - стрік перервано
        current_streak = 0
    else:
        # Стрік живий, рахуємо назад
        current_streak = 1
        for i in range(len(sorted_dates) - 2, -1, -1):
            delta = (sorted_dates[i + 1] - sorted_dates[i]).days
            if delta == 1:
                current_streak += 1
            else:
                break

    return current_streak, best_streak


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

    # Словник для збереження дат по кожній звичці: { "Pushups": ["2023-01-01", ...] }
    habit_dates = defaultdict(list)
    # Словник для загальної суми: { "Pushups": 500 }
    habit_totals = defaultdict(int)

    print("🔄 Розрахунок статистики та стріків...")

    for page in pages:
        props = page["properties"]
        page_id = page["id"]

        # --- Отримання даних ---
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

        # --- Логіка ---
        if not is_template and intensity > 0:

            # Heatmap Score
            if max_intensity > 0:
                score = (intensity / max_intensity) * 100
            else:
                score = 100.0

            heatmap_scores[day] += round(score, 1)

            # Збираємо дані для статистики
            habit_totals[habit_name] += intensity
            habit_dates[habit_name].append(day)

            # Оновлення статусу в Notion
            if not is_enabled:
                try:
                    notion.pages.update(
                        page_id=page_id,
                        properties={"Enabled": {"checkbox": True}}
                    )
                    print(f"   ✅ Відмічено: {habit_name}")
                except Exception as e:
                    print(f"   ❌ Помилка Notion {habit_name}: {e}")

    # --- Формування фінальної статистики з стріками ---
    final_stats = {}
    for name, total in habit_totals.items():
        curr_streak, best_streak = calculate_streaks(habit_dates[name])
        final_stats[name] = {
            "total": total,
            "current_streak": curr_streak,
            "best_streak": best_streak
        }
        print(f"   📊 {name}: Total={total}, Streak={curr_streak}🔥")

    return {
        "heatmap": dict(heatmap_scores),
        "stats": final_stats
    }


def create_daily_habits(all_pages):
    today_str = get_today_str()
    print(f"📅 Перевірка шаблонів на: {today_str}")

    templates = []
    created_today_names = set()

    for page in all_pages:
        props = page["properties"]
        if "Template_Checkbox" in props and props["Template_Checkbox"]["checkbox"]:
            templates.append(page)

        p_date = None
        if "Date" in props and props["Date"]["date"]:
            p_date = props["Date"]["date"]["start"]

        h_name = ""
        if "Name_Hebits" in props and props["Name_Hebits"]["title"]:
            h_name = props["Name_Hebits"]["title"][0]["plain_text"]

        if p_date == today_str and h_name:
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
            "Date": {"date": {"start": today_str}},
            "Enabled": {"checkbox": False},
            "Template_Checkbox": {"checkbox": False},
            "Number_of_intensity": {"number": 0}
        }
        if max_val is not None:
            new_props["Max_Number_of_intensity"] = {"number": max_val}

        try:
            notion.pages.create(
                parent={"database_id": DATABASE_ID},
                properties=new_props
            )
            print(f"🆕 Створено: {habit_name}")
        except Exception as e:
            print(f"❌ Error {habit_name}: {e}")


def main():
    pages = fetch_all_database_pages()
    full_data = process_history_and_update(pages)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2, ensure_ascii=False)
    print("💾 data.json оновлено (+Streaks)")

    create_daily_habits(pages)


if __name__ == "__main__":
    main()