import os
import json
import re
from datetime import datetime, timedelta
import pytz
import feedparser
from dateutil import parser as date_parser
from deep_translator import GoogleTranslator

COUNTRY_NAME = "southafrica"
OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{COUNTRY_NAME}_news.json")
MAX_PER_CATEGORY = 20
MAX_AGE_DAYS = 7

CATEGORIES = ["Diplomacy", "Military", "Energy", "Economy", "Local Events"]

RSS_SOURCES = [
    {
        "name": "News24",
        "url": "https://feeds.24.com/articles/news24/topstories/rss",
        "lang": "en"
    },
    {
        "name": "BBC News Africa",
        "url": "http://feeds.bbci.co.uk/news/world/africa/rss.xml",
        "lang": "en"
    },
    {
        "name": "The Citizen",
        "url": "https://citizen.co.za/feed",
        "lang": "en"
    },
    {
        "name": "Daily Maverick",
        "url": "https://www.dailymaverick.co.za/dmrss",
        "lang": "en"
    }
]

KEYWORD_RULES = {
    "Diplomacy": [
        "diplomat", "ambassador", "foreign affairs", "bilateral", "treaty",
        "summit", "sadc", "african union", "brics", "united nations",
        "embassy", "consulate", "mou", "international relations", "dirco", "state visit"
    ],
    "Military": [
        "military", "defense", "defence", "army", "navy", "air force",
        "armed forces", "sandf", "security forces", "peacekeepers", "troop",
        "drills", "exercise", "warship", "fighter jet"
    ],
    "Energy": [
        "energy", "eskom", "load shedding", "loadshedding", "electricity",
        "coal", "power grid", "nuclear", "renewable", "solar", "wind",
        "green energy", "power station", "koeberg", "medupi"
    ],
    "Economy": [
        "economy", "economic", "trade", "gdp", "inflation", "market",
        "investment", "bank", "rand", "finance", "tax", "export",
        "import", "business", "jse", "commerce", "sars", "treasury", "interest rate"
    ]
}

translator = GoogleTranslator(source='auto', target='en')

def translate_text(text: str, source_lang: str) -> str:
    if not text:
        return ""
    if source_lang == "en":
        return text.strip()
    try:
        return translator.translate(text).strip()
    except Exception:
        return text.strip()

def parse_published_date(entry) -> datetime:
    tz_utc = pytz.UTC
    
    # Try parsing via dateutil parser on raw date strings
    raw_date_str = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if raw_date_str:
        try:
            dt = date_parser.parse(raw_date_str)
            if dt.tzinfo is None:
                return tz_utc.localize(dt)
            return dt.astimezone(tz_utc)
        except Exception:
            pass

    # Fallback to feedparser time tuples
    parsed_time = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed_time:
        try:
            return datetime(*parsed_time[:6], tzinfo=tz_utc)
        except Exception:
            pass

    return datetime.now(tz_utc)

def is_host_country_relevant(title: str, summary: str) -> bool:
    content = f"{title} {summary}".lower()
    keywords = [
        "south africa", "south african", "pretoria", "johannesburg",
        "cape town", "durban", "soweto", "rand", "ramaphosa", "eskom", "anc", "da"
    ]
    return any(re.search(rf"\b{kw}\b", content) for kw in keywords)

def categorize_story(title: str, summary: str) -> str:
    content = f"{title} {summary}".lower()
    for category, keywords in KEYWORD_RULES.items():
        if any(re.search(rf"\b{kw}\b", content) for kw in keywords):
            return category
    return "Local Events"

def clean_old_entries(stories: list, max_days: int) -> list:
    cutoff = datetime.now(pytz.UTC) - timedelta(days=max_days)
    valid_stories = []
    for s in stories:
        try:
            pdate = date_parser.parse(s["published_date"])
            if pdate.tzinfo is None:
                pdate = pytz.UTC.localize(pdate)
            if pdate >= cutoff:
                valid_stories.append(s)
        except Exception:
            continue
    return valid_stories

def update_category_entries(existing_entries: list, new_entries: list, limit: int) -> list:
    combined_dict = {}
    for story in existing_entries + new_entries:
        combined_dict[story["url"]] = story

    all_stories = list(combined_dict.values())

    def get_sort_key(item):
        try:
            dt = date_parser.parse(item["published_date"])
            return dt if dt.tzinfo else pytz.UTC.localize(dt)
        except Exception:
            return datetime.min.replace(tzinfo=pytz.UTC)

    all_stories.sort(key=get_sort_key, reverse=True)
    return all_stories[:limit]

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now_utc = datetime.now(pytz.UTC)
    seven_days_ago = now_utc - timedelta(days=MAX_AGE_DAYS)

    existing_data = {cat: [] for cat in CATEGORIES}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for cat in CATEGORIES:
                    if cat in loaded and isinstance(loaded[cat], list):
                        existing_data[cat] = clean_old_entries(loaded[cat], MAX_AGE_DAYS)
        except Exception:
            pass

    new_data = {cat: [] for cat in CATEGORIES}

    # Browser User-Agent header prevents 403 HTTP blocks in GitHub Actions runner
    agent_header = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"], agent=agent_header)
            for entry in feed.entries:
                pub_date = parse_published_date(entry)
                if pub_date < seven_days_ago:
                    continue

                raw_title = getattr(entry, "title", "")
                raw_summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                url = getattr(entry, "link", "")

                if not raw_title or not url:
                    continue

                translated_title = translate_text(raw_title, source["lang"])
                translated_summary = translate_text(raw_summary, source["lang"])

                if not is_host_country_relevant(translated_title, translated_summary):
                    continue

                category = categorize_story(translated_title, translated_summary)

                story_obj = {
                    "title": translated_title,
                    "source": source["name"],
                    "url": url,
                    "published_date": pub_date.isoformat(),
                    "category": category
                }
                new_data[category].append(story_obj)
        except Exception as e:
            print(f"Error parsing source {source['name']}: {e}")

    final_output = {}
    for cat in CATEGORIES:
        updated_list = update_category_entries(existing_data[cat], new_data[cat], MAX_PER_CATEGORY)
        final_output[cat] = updated_list

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
