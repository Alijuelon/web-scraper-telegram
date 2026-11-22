import base64
import html
import io
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

BAD_IMAGE_KEYWORDS = ("icon", "logo", "avatar", "spinner", "loader", "pixel", "1x1", "spacer", "badge")
NOISE_PREFIXES = (
    "baca juga",
    "lihat juga",
    "simak juga",
    "simak video",
    "advertisement",
    "scroll to continue",
    "foto:",
    "video:",
    "dok.",
    "sumber:",
    "penulis:",
    "editor:",
)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _is_valid_image_url(img_url: str | None) -> bool:
    if not img_url or img_url.startswith("data:image"):
        return False
    lower = img_url.lower()
    return not any(bad in lower for bad in BAD_IMAGE_KEYWORDS)


def extract_image_from_tag(element, base_url: str) -> str | None:
    img_tag = element if element.name == "img" else element.find("img")
    if not img_tag:
        return None

    for attr in ["src", "data-src", "data-lazy-src", "data-original", "data-url", "data-image"]:
        val = img_tag.get(attr)
        if val:
            full = urljoin(base_url, val.strip())
            if _is_valid_image_url(full):
                return full

    srcset = img_tag.get("srcset") or img_tag.get("data-srcset")
    if srcset:
        candidates = [c.strip().split(" ")[0] for c in srcset.split(",") if c.strip()]
        for cand in reversed(candidates):
            full = urljoin(base_url, cand)
            if _is_valid_image_url(full):
                return full

    return None


def _summarize_paragraphs(paragraphs: list[str], max_chars: int = 480) -> str:
    """Menyusun ringkasan 2-3 kalimat pertama yang informatif agar pas di caption Telegram."""
    if not paragraphs:
        return ""

    combined = " ".join(paragraphs)
    sentences = re.split(r"(?<=[.!?])\s+", combined)
    summary_parts = []
    current_len = 0

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 25:
            continue
        if current_len + len(sent) + 1 > max_chars:
            if not summary_parts:
                summary_parts.append(sent[: max_chars - 3].rstrip() + "...")
            break
        summary_parts.append(sent)
        current_len += len(sent) + 1
        if len(summary_parts) >= 3:
            break

    return " ".join(summary_parts)


def fetch_article_content_and_image(article_url: str) -> tuple[str, str | None]:
    """Membuka halaman artikel untuk mengambil ringkasan isi berita dan gambar utama (og:image)."""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=12)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # 1. Ambil gambar utama artikel
        og_image = None
        meta = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if meta and meta.get("content"):
            cand = urljoin(article_url, meta["content"].strip())
            if _is_valid_image_url(cand):
                og_image = cand

        # 2. Hapus elemen pengganggu
        for noisy in soup(["script", "style", "nav", "footer", "header", "aside", "figcaption", "form"]):
            noisy.decompose()

        # 3. Cari wadah utama isi artikel (mendukung struktur portal berita Indonesia & umum)
        body_selectors = [
            ".detail__body-text",
            ".read__content",
            ".post-content",
            ".entry-content",
            ".article-content",
            "[itemprop='articleBody']",
            "article",
            "main",
        ]
        content_container = None
        for sel in body_selectors:
            found = soup.select_one(sel)
            if found and len(found.find_all("p")) >= 2:
                content_container = found
                break

        target_scope = content_container if content_container else soup
        valid_paragraphs = []

        for p in target_scope.find_all("p"):
            # Abaikan paragraf di dalam kotak "Baca Juga"
            parent_classes = " ".join(p.parent.get("class", [])).lower() if p.parent else ""
            if any(k in parent_classes for k in ("baca-juga", "related", "sisip", "embed", "caption")):
                continue

            text = _clean_text(p.get_text(" "))
            lower = text.lower()

            if len(text) < 45:
                continue
            if any(lower.startswith(prefix) for prefix in NOISE_PREFIXES):
                continue
            if "baca juga:" in lower or "lihat juga:" in lower:
                continue

            valid_paragraphs.append(text)
            if len(valid_paragraphs) >= 5:
                break

        summary = _summarize_paragraphs(valid_paragraphs, max_chars=480)

        # Fallback ke meta description jika paragraf tidak terbaca
        if not summary:
            desc_meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
                "meta", property="og:description"
            )
            if desc_meta and desc_meta.get("content"):
                summary = _clean_text(desc_meta["content"])[:450]

        return summary, og_image
    except Exception:
        return "", None


def _extract_best_headline(container, base_url: str) -> tuple[str, str | None]:
    for tag_name in ["h1", "h2", "h3", "h4"]:
        heading = container.find(tag_name)
        if heading:
            a_tag = heading.find("a", href=True) or container.find("a", href=True)
            title = _clean_text(heading.get_text(" "))
            if len(title) >= 15 and a_tag:
                return title, urljoin(base_url, a_tag["href"])

    best_title = ""
    best_link = None
    for a_tag in container.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = _clean_text(a_tag.get_text(" "))
        if len(text) > len(best_title):
            best_title = text
            best_link = urljoin(base_url, href)

    return best_title, best_link


def smart_scrape(
    url: str,
    custom_selector: str = "",
    limit: int = 5,
    include_summary: bool = True,
) -> tuple[list[dict], str | None]:
    """Mengambil judul, ringkasan isi berita, tautan, dan gambar secara otomatis."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    og_meta = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    site_cover = urljoin(url, og_meta["content"].strip()) if og_meta and og_meta.get("content") else None

    for noisy in soup(["nav", "footer", "header", "script", "style", "aside"]):
        noisy.decompose()

    if custom_selector.strip():
        containers = soup.select(custom_selector.strip())
    else:
        containers = soup.find_all("article")
        if len(containers) < 3:
            extra = [
                el
                for el in soup.find_all(["div", "li"])
                if el.find("a", href=True) and el.find("img") and len(el.find_all("article")) == 0
            ]
            containers.extend(extra)

    results = []
    seen_urls = set()
    seen_titles = set()

    for el in containers:
        title, link = _extract_best_headline(el, url)
        if not title or len(title) < 18 or not link:
            continue

        clean_link = link.split("#")[0]
        if clean_link in seen_urls or title in seen_titles:
            continue

        parsed_link = urlparse(clean_link)
        if parsed_link.path in ("", "/"):
            continue

        img_url = extract_image_from_tag(el, url)
        summary = ""

        # Buka halaman artikel untuk mengambil ringkasan isi & gambar HD (og:image)
        if include_summary or not img_url:
            fetched_summary, fetched_img = fetch_article_content_and_image(clean_link)
            if include_summary:
                summary = fetched_summary
            if fetched_img:
                img_url = fetched_img

        if not img_url:
            img_url = site_cover

        seen_urls.add(clean_link)
        seen_titles.add(title)
        results.append(
            {
                "title": title,
                "summary": summary,
                "link": clean_link,
                "image": img_url,
            }
        )

        if len(results) >= limit:
            break

    return results, site_cover


def download_and_convert_image(img_url: str, referer: str) -> io.BytesIO | None:
    try:
        req_headers = {**HEADERS, "Referer": referer}
        resp = requests.get(img_url, headers=req_headers, timeout=12)
        resp.raise_for_status()

        img = Image.open(io.BytesIO(resp.content))
        if img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        buf.seek(0)
        return buf
    except Exception:
        return None


def send_telegram_text(token: str, chat_id: str, text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )


def send_item_to_telegram(
    token: str,
    chat_id: str,
    item: dict,
    source_url: str,
    badge: str = "",
) -> bool:
    """Mengirim 1 kartu berita lengkap: Gambar + Judul + Ringkasan Isi + Link."""
    safe_title = html.escape(item["title"][:220])
    safe_link = html.escape(item["link"], quote=True)
    header_line = f"<i>{html.escape(badge)}</i>\n" if badge else ""

    summary_text = item.get("summary", "").strip()
    summary_block = f"\n\n📝 {html.escape(summary_text[:520])}" if summary_text else ""

    caption = f'{header_line}<b>{safe_title}</b>{summary_block}\n\n🔗 <a href="{safe_link}">Baca Selengkapnya</a>'

    if item.get("image"):
        img_bytes = download_and_convert_image(item["image"], referer=source_url)
        if img_bytes:
            res = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                },
                files={"photo": ("news.jpg", img_bytes, "image/jpeg")},
                timeout=20,
            )
            if res.ok:
                return True

    res = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    res.raise_for_status()
    return False


def test_telegram_connection(token: str, chat_id: str) -> tuple[bool, str]:
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        if not me.get("ok"):
            return False, f"Token tidak valid: {me.get('description', 'Error')}"
        bot_username = me["result"].get("username", "Bot")

        send = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": (
                    f"✅ Koneksi sukses! @{bot_username} aktif.\n"
                    f"Ketik /help di chat ini untuk melihat daftar perintah scraping."
                ),
            },
            timeout=10,
        ).json()
        if not send.get("ok"):
            return False, f"Gagal kirim ke Chat ID: {send.get('description', 'Error')}"
        return True, f"Terhubung ke @{bot_username}"
    except Exception as e:
        return False, str(e)


# --- MANAJEMEN URL & PEMROSES PERINTAH DARI TELEGRAM ---
def load_urls_file(urls_file: str = "urls.json") -> list[dict]:
    if os.path.exists(urls_file):
        try:
            with open(urls_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [{"name": "Detik News", "url": "https://news.detik.com/", "selector": "", "limit": 4}]


def save_urls_file(
    urls_data: list[dict],
    urls_file: str = "urls.json",
    gh_token: str = "",
    gh_repo: str = "",
) -> bool:
    with open(urls_file, "w", encoding="utf-8") as f:
        json.dump(urls_data, f, indent=2, ensure_ascii=False)

    if not gh_token or not gh_repo:
        return False

    try:
        api_url = f"https://api.github.com/repos/{gh_repo}/contents/{urls_file}"
        headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"}
        sha = None
        get_res = requests.get(api_url, headers=headers, timeout=10)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")

        content_b64 = base64.b64encode(
            json.dumps(urls_data, indent=2, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": "Update urls.json via Telegram/App", "content": content_b64}
        if sha:
            payload["sha"] = sha

        put_res = requests.put(api_url, headers=headers, json=payload, timeout=15)
        return put_res.status_code in (200, 201)
    except Exception:
        return False


def poll_and_handle_telegram_commands(
    token: str,
    allowed_chat_id: str,
    urls_file: str = "urls.json",
    gh_token: str = "",
    gh_repo: str = "",
) -> int:
    """
    Mengecek pesan perintah baru dari Telegram dan langsung mengeksekusinya.
    Mengembalikan jumlah perintah yang diproses.
    """
    if not token or not allowed_chat_id:
        return 0

    try:
        res = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"timeout": 2, "allowed_updates": '["message"]'},
            timeout=8,
        ).json()
    except Exception:
        return 0

    if not res.get("ok"):
        return 0

    updates = res.get("result", [])
    if not updates:
        return 0

    # Langsung tandai semua update sebagai sudah dibaca agar tidak diproses ganda
    max_update_id = max(u["update_id"] for u in updates)
    try:
        requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": max_update_id + 1, "timeout": 1},
            timeout=5,
        )
    except Exception:
        pass

    handled_count = 0
    for upd in updates:
        msg = upd.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()

        # Hanya layani perintah dari Chat ID pemilik
        if not text or chat_id != str(allowed_chat_id).strip():
            continue

        handled_count += 1
        lower_text = text.lower()

        # 1. Perintah /help atau /start
        if lower_text in ("/start", "/help"):
            help_msg = (
                "🤖 <b>Perintah ScrapGram Bot</b>\n\n"
                "• <code>/scrape</code> — Scrape semua website tersimpan sekarang\n"
                "• <code>https://contoh.com</code> — Kirim link langsung untuk di-scrape instan\n"
                "• <code>/list</code> — Lihat daftar website tersimpan\n"
                "• <code>/add https://contoh.com</code> — Simpan website baru\n"
                "• <code>/del 1</code> — Hapus website nomor 1 dari daftar"
            )
            send_telegram_text(token, chat_id, help_msg)

        # 2. Perintah /list
        elif lower_text == "/list":
            saved = load_urls_file(urls_file)
            if not saved:
                send_telegram_text(token, chat_id, "📭 Belum ada website tersimpan.")
            else:
                lines = [f"<b>{i}. {html.escape(u['name'])}</b>\n{html.escape(u['url'])}" for i, u in enumerate(saved, 1)]
                send_telegram_text(token, chat_id, "📌 <b>Daftar Website Tersimpan:</b>\n\n" + "\n\n".join(lines))

        # 3. Perintah /add <url>
        elif lower_text.startswith("/add "):
            new_url = text.split(" ", 1)[1].strip()
            if not new_url.startswith(("http://", "https://")):
                new_url = "https://" + new_url
            domain = urlparse(new_url).netloc.replace("www.", "") or new_url
            saved = load_urls_file(urls_file)
            if any(u["url"] == new_url for u in saved):
                send_telegram_text(token, chat_id, f"ℹ️ <b>{html.escape(domain)}</b> sudah ada di daftar.")
            else:
                saved.append({"name": domain, "url": new_url, "selector": "", "limit": 4})
                synced = save_urls_file(saved, urls_file, gh_token, gh_repo)
                note = " (tersinkron ke GitHub)" if synced else ""
                send_telegram_text(token, chat_id, f"✅ Berhasil menyimpan <b>{html.escape(domain)}</b>{note}.")

        # 4. Perintah /del <nomor>
        elif lower_text.startswith("/del "):
            arg = text.split(" ", 1)[1].strip()
            saved = load_urls_file(urls_file)
            if arg.isdigit() and 1 <= int(arg) <= len(saved):
                removed = saved.pop(int(arg) - 1)
                save_urls_file(saved, urls_file, gh_token, gh_repo)
                send_telegram_text(token, chat_id, f"🗑️ Dihapus: <b>{html.escape(removed['name'])}</b>")
            else:
                send_telegram_text(token, chat_id, "⚠️ Nomor tidak valid. Cek nomor dengan /list.")

        # 5. Perintah /scrape atau kirim URL langsung
        elif lower_text.startswith("/scrape") or lower_text.startswith(("http://", "https://")):
            parts = text.split(" ", 1)
            target_url = ""

            if lower_text.startswith(("http://", "https://")):
                target_url = text.strip()
            elif len(parts) > 1 and parts[1].strip():
                target_url = parts[1].strip()
                if not target_url.startswith(("http://", "https://")):
                    target_url = "https://" + target_url

            if target_url:
                domain = urlparse(target_url).netloc
                send_telegram_text(token, chat_id, f"⏳ Sedang men-scrape <b>{html.escape(domain)}</b> + merangkum isi...")
                try:
                    items, _ = smart_scrape(url=target_url, limit=4, include_summary=True)
                    if not items:
                        send_telegram_text(token, chat_id, "⚠️ Tidak ditemukan artikel pada URL tersebut.")
                    else:
                        for item in items:
                            send_item_to_telegram(token, chat_id, item, target_url, badge=f"⚡ Instant • {domain}")
                            time.sleep(0.35)
                except Exception as e:
                    send_telegram_text(token, chat_id, f"❌ Gagal scraping: {html.escape(str(e))}")
            else:
                # Scrape semua website yang tersimpan di urls.json
                saved = load_urls_file(urls_file)
                send_telegram_text(token, chat_id, f"⏳ Memulai scraping untuk {len(saved)} website tersimpan...")
                for entry in saved:
                    u_url = entry["url"]
                    u_name = entry.get("name") or urlparse(u_url).netloc
                    u_limit = int(entry.get("limit", 4))
                    u_sel = entry.get("selector", "")
                    try:
                        items, _ = smart_scrape(url=u_url, custom_selector=u_sel, limit=u_limit, include_summary=True)
                        for item in items:
                            send_item_to_telegram(token, chat_id, item, u_url, badge=f"📌 {u_name}")
                            time.sleep(0.35)
                    except Exception as e:
                        send_telegram_text(token, chat_id, f"❌ Error pada {html.escape(u_name)}: {html.escape(str(e))}")

    return handled_count
