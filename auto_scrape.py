import json
import os
import time
from urllib.parse import urlparse

from scraper_engine import (
    load_urls_file,
    poll_and_handle_telegram_commands,
    send_item_to_telegram,
    smart_scrape,
)

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
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()

    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID wajib diisi di GitHub Repository Secrets!")

    # Langkah 1: Proses perintah chat yang masuk dari Telegram
    print("[*] Memeriksa perintah masuk dari Telegram...")
    cmd_count = poll_and_handle_telegram_commands(
        token=token,
        allowed_chat_id=chat_id,
        urls_file=URLS_FILE,
        gh_token=gh_token,
        gh_repo=gh_repo,
    )
    print(f"[*] Perintah Telegram diproses: {cmd_count}")

    # Langkah 2: Auto-Scrape & Auto-Kirim berita baru dari daftar tersimpan
    targets = load_urls_file(URLS_FILE)
    history: list[str] = load_json(HISTORY_FILE, [])
    sent_set = set(history)
    total_new_sent = 0

    for target in targets:
        url = target.get("url", "")
        if not url:
            continue

        name = target.get("name") or urlparse(url).netloc
        selector = target.get("selector", "")
        limit = int(target.get("limit", 4))

        print(f"[*] Mengecek berita baru: {name} ({url})")
        try:
            items, _ = smart_scrape(
                url=url,
                custom_selector=selector,
                limit=limit,
                include_summary=True,
            )
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

    save_json(HISTORY_FILE, history[-500:])
    print(f"[✓] Selesai. Total berita baru terkirim: {total_new_sent}")


if __name__ == "__main__":
    main()
