import json
import os
import time
from urllib.parse import urlparse

from scraper_engine import send_item_to_telegram, smart_scrape

URLS_FILE = "urls.json"
HISTORY_FILE = "sent_history.json"


def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID wajib diisi di GitHub Repository Secrets!")

    targets = load_json(URLS_FILE, [])
    history: list[str] = load_json(HISTORY_FILE, [])
    sent_set = set(history)
    total_new_sent = 0

    for target in targets:
        url = target.get("url", "")
        if not url:
            continue

        name = target.get("name") or urlparse(url).netloc
        selector = target.get("selector", "")
        limit = int(target.get("limit", 5))

        print(f"[*] Memeriksa: {name} ({url})")
        try:
            items, _ = smart_scrape(url=url, custom_selector=selector, limit=limit, deep_fetch_image=True)
        except Exception as e:
            print(f"[!] Gagal scraping {url}: {e}")
            continue

        for item in items:
            if item["link"] in sent_set:
                continue

            try:
                send_item_to_telegram(
                    token=token,
                    chat_id=chat_id,
                    item=item,
                    source_url=url,
                    badge=f"🤖 Auto-Update • {name}",
                )
                sent_set.add(item["link"])
                history.append(item["link"])
                total_new_sent += 1
                print(f"    [+] Terkirim: {item['title'][:60]}...")
                time.sleep(0.5)
            except Exception as e:
                print(f"    [!] Gagal kirim item: {e}")

    # Simpan maksimal 500 riwayat link terakhir agar tidak mengirim berita duplikat
    save_json(HISTORY_FILE, history[-500:])
    print(f"[✓] Selesai. Total berita baru terkirim: {total_new_sent}")


if __name__ == "__main__":
    main()
