import os
import json
from notion_client import Client
from collections import defaultdict
from datetime import datetime, timedelta

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    raise ValueError("Secrets NOTION_TOKEN and DATABASE_ID are required")

notion = Client(auth=NOTION_TOKEN)


def get_today_date_obj():
    return (datetime.utcnow() + timedelta(hours=2)).date()


def get_today_str():
    return get_today_date_obj().strftime("%Y-%m-%d")


def get_yesterday_str():
    return (get_today_date_obj() - timedelta(days=1)).strftime("%Y-%m-%d")


def get_prop(props, name, prop_type, nested_key=None):
    """Безпечне отримання властивостей з Notion"""
    if name in props and props[name] and props[name].get(prop_type):
        if nested_key:
            return props[name][prop_type].get(nested_key)
        return props[name][prop_type]
    return None


def calculate_streaks(dates_list):
    if not dates_list: return 0, 0
    sorted_dates = sorted(list(set([datetime.strptime(d, "%Y-%m-%d").date() for d in dates_list])))
    if not sorted_dates: return 0, 0

    today = get_today_date_obj()
    current_streak, best_streak, temp_streak = 0, 0, 0

    for i in range(len(sorted_dates)):
        if i == 0:
            temp_streak = 1
        else:
            if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
                temp_streak += 1
            else:
                best_streak = max(best_streak, temp_streak)
                temp_streak = 1
    best_streak = max(best_streak, temp_streak)

    last_date = sorted_dates[-1]
    if (today - last_date).days > 1:
        current_streak = 0
    else:
        current_streak = 1
        for i in range(len(sorted_dates) - 2, -1, -1):
            if (sorted_dates[i + 1] - sorted_dates[i]).days == 1:
                current_streak += 1
            else:
                break

    return current_streak, best_streak


def fetch_all_database_pages():
    results = []
    has_more, start_cursor = True, None
    print("⏳ Завантаження даних з Notion...")
    while has_more:
        response = notion.databases.query(database_id=DATABASE_ID, start_cursor=start_cursor)
        results.extend(response["results"])
        has_more = response["has_more"]
        start_cursor = response["next_cursor"]
    return results


def process_history_and_update(pages):
    heatmap_scores = defaultdict(float)
    habit_dates = defaultdict(list)
    habit_totals = defaultdict(int)

    # Словник для збереження метаданих для UI (категорії, інтервали на сьогодні)
    habit_meta = {}
    today_str = get_today_str()

    print("🔄 Обробка статистики...")

    for page in pages:
        props = page["properties"]
        page_id = page["id"]

        habit_name = get_prop(props, "Name_Hebits", "title", 0)
        if type(habit_name) is dict: habit_name = habit_name.get("plain_text", "Unknown")
        if not habit_name: continue

        date_val = get_prop(props, "Date", "date", "start") or page["created_time"].split("T")[0]
        day = date_val.split("T")[0]

        intensity = get_prop(props, "Number_of_intensity", "number") or 0
        max_intensity = get_prop(props, "Max_Number_of_intensity", "number") or 0
        is_enabled = get_prop(props, "Enabled", "checkbox") or False
        is_template = get_prop(props, "Template_Checkbox", "checkbox") or False

        vector = get_prop(props, "Vector category", "select", "name")
        architecture = get_prop(props, "Action Architecture", "select", "name")
        interval = get_prop(props, "Maximum interval", "number")

        # Зберігаємо метадані останнього дня (або шаблону) для відображення на сайті
        if habit_name not in habit_meta or day == today_str or is_template:
            habit_meta[habit_name] = {
                "vector": vector,
                "architecture": architecture,
                "current_interval": interval if day == today_str else habit_meta.get(habit_name, {}).get(
                    "current_interval")
            }

        if not is_template and intensity > 0:
            score = (intensity / max_intensity * 100) if max_intensity > 0 else 100.0
            heatmap_scores[day] += round(score, 1)
            habit_totals[habit_name] += intensity
            habit_dates[habit_name].append(day)

            if not is_enabled:
                try:
                    notion.pages.update(page_id=page_id, properties={"Enabled": {"checkbox": True}})
                except Exception as e:
                    print(f"❌ Помилка Notion {habit_name}: {e}")

    final_stats = {}
    for name, total in habit_totals.items():
        curr_streak, best_streak = calculate_streaks(habit_dates[name])
        meta = habit_meta.get(name, {})
        final_stats[name] = {
            "total": total,
            "current_streak": curr_streak,
            "best_streak": best_streak,
            "vector": meta.get("vector"),
            "architecture": meta.get("architecture"),
            "days_to_peak": meta.get("current_interval")
        }

    return {"heatmap": dict(heatmap_scores), "stats": final_stats}


def create_daily_habits(all_pages):
    today_str = get_today_str()
    yesterday_str = get_yesterday_str()
    print(f"📅 Створення звичок на {today_str}...")

    templates, yesterday_pages, created_today_names = [], {}, set()

    # Аналізуємо існуючі записи
    for page in all_pages:
        props = page["properties"]
        is_template = get_prop(props, "Template_Checkbox", "checkbox")
        p_date = get_prop(props, "Date", "date", "start")
        h_name = get_prop(props, "Name_Hebits", "title", 0)
        if type(h_name) is dict: h_name = h_name.get("plain_text", "")

        if is_template: templates.append(page)
        if p_date == today_str and h_name: created_today_names.add(h_name)
        if p_date == yesterday_str and h_name: yesterday_pages[h_name] = page

    # Створюємо нові
    for template in templates:
        t_props = template["properties"]
        h_name = get_prop(t_props, "Name_Hebits", "title", 0)
        if type(h_name) is dict: h_name = h_name.get("plain_text", "")
        if not h_name or h_name in created_today_names: continue

        arch = get_prop(t_props, "Action Architecture", "select", "name")
        vector = get_prop(t_props, "Vector category", "select", "name")
        base_max = get_prop(t_props, "Max_Number_of_intensity", "number")
        base_interval = get_prop(t_props, "Maximum interval", "number")

        # --- ЛОГІКА ПЕРІОДИЗАЦІЇ (НАВЧАННЯ) ---
        new_interval = base_interval

        if arch == "Навчання" and base_interval is not None:
            if h_name in yesterday_pages:
                y_props = yesterday_pages[h_name]["properties"]
                y_num = get_prop(y_props, "Number_of_intensity", "number") or 0
                y_max = get_prop(y_props, "Max_Number_of_intensity", "number") or base_max or 1
                y_interval = get_prop(y_props, "Maximum interval", "number")

                if y_interval is None: y_interval = base_interval

                # Якщо вчора було зроблено ПІК (або більше максимуму) -> СКИДАЄМО інтервал
                if y_num >= y_max:
                    new_interval = base_interval
                    print(f"   ⚡ {h_name}: Пік досягнуто вчора! Скидання інтервалу до {base_interval}.")
                else:
                    # Якщо ні -> ВІДНІМАЄМО 1 (мінімум 0)
                    new_interval = max(0, y_interval - 1)
                    print(f"   ⏳ {h_name}: Мінімальна дія. Інтервал зменшено до {new_interval}.")

        # Формуємо властивості для нової сторінки
        new_props = {
            "Name_Hebits": {"title": [{"text": {"content": h_name}}]},
            "Date": {"date": {"start": today_str}},
            "Enabled": {"checkbox": False},
            "Template_Checkbox": {"checkbox": False},
            "Number_of_intensity": {"number": 0}
        }

        if base_max is not None: new_props["Max_Number_of_intensity"] = {"number": base_max}
        if new_interval is not None: new_props["Maximum interval"] = {"number": new_interval}

        # Додаємо Select-категорії, якщо вони існують
        if arch: new_props["Action Architecture"] = {"select": {"name": arch}}
        if vector: new_props["Vector category"] = {"select": {"name": vector}}

        try:
            notion.pages.create(parent={"database_id": DATABASE_ID}, properties=new_props)
            print(f"🆕 Створено: {h_name}")
        except Exception as e:
            print(f"❌ Помилка створення {h_name}: {e}")


def main():
    pages = fetch_all_database_pages()
    full_data = process_history_and_update(pages)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2, ensure_ascii=False)
    print("💾 data.json оновлено (+Periodization)")

    create_daily_habits(pages)


if __name__ == "__main__":
    main()