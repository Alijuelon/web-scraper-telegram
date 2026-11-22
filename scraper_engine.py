import html
import io
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


def fetch_og_image(article_url: str) -> str | None:
    """Mengambil gambar utama (og:image) dari dalam halaman artikel jika thumbnail tidak ditemukan."""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        meta = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if meta and meta.get("content"):
            full = urljoin(article_url, meta["content"].strip())
            if _is_valid_image_url(full):
                return full
    except Exception:
        pass
    return None


def _extract_best_headline(container, base_url: str) -> tuple[str, str | None]:
    """Mencari judul berita dan link paling relevan di dalam sebuah kartu."""
    # Prioritas 1: Heading (h1-h4) yang memiliki tautan
    for tag_name in ["h1", "h2", "h3", "h4"]:
        heading = container.find(tag_name)
        if heading:
            a_tag = heading.find("a", href=True) or container.find("a", href=True)
            title = _clean_text(heading.get_text(" "))
            if len(title) >= 15 and a_tag:
                return title, urljoin(base_url, a_tag["href"])

    # Prioritas 2: Tag <a> dengan teks terpanjang di dalam kartu
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
    limit: int = 6,
    deep_fetch_image: bool = True,
) -> tuple[list[dict], str | None]:
    """
    Mengambil artikel beserta gambar secara otomatis hanya bermodal URL,
    atau memakai custom_selector jika diisi.
    """
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Cover image halaman utama sebagai cadangan terakhir
    og_meta = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    site_cover = urljoin(url, og_meta["content"].strip()) if og_meta and og_meta.get("content") else None

    # Hapus elemen navigasi/footer agar tidak ikut terscrap
    for noisy in soup(["nav", "footer", "header", "script", "style", "aside"]):
        noisy.decompose()

    if custom_selector.strip():
        containers = soup.select(custom_selector.strip())
    else:
        # Mode Otomatis: cari tag <article> terlebih dahulu
        containers = soup.find_all("article")
        # Jika <article> sedikit, cari <div> atau <li> yang membungkus gambar + link
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
    base_domain = urlparse(url).netloc

    for el in containers:
        title, link = _extract_best_headline(el, url)
        if not title or len(title) < 18 or not link:
            continue

        # Normalisasi link (buang fragment #)
        clean_link = link.split("#")[0]
        if clean_link in seen_urls or title in seen_titles:
            continue

        # Abaikan halaman kategori/indeks pendek jika tidak terlihat seperti artikel
        parsed_link = urlparse(clean_link)
        if parsed_link.path in ("", "/"):
            continue

        img_url = extract_image_from_tag(el, url)

        # Jika thumbnail tidak ada di halaman depan, ambil og:image dari link artikel
        if not img_url and deep_fetch_image and parsed_link.netloc == base_domain:
            img_url = fetch_og_image(clean_link)

        if not img_url:
            img_url = site_cover

        seen_urls.add(clean_link)
        seen_titles.add(title)
        results.append(
            {
                "title": title,
                "link": clean_link,
                "image": img_url,
            }
        )

        if len(results) >= limit:
            break

    return results, site_cover


def download_and_convert_image(img_url: str, referer: str) -> io.BytesIO | None:
    """Mengunduh gambar dan mengonversi ke JPEG agar kompatibel dengan Telegram."""
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


def send_item_to_telegram(
    token: str,
    chat_id: str,
    item: dict,
    source_url: str,
    badge: str = "",
) -> bool:
    """Mengirim 1 item hasil scraping beserta foto ke Telegram."""
    safe_title = html.escape(item["title"][:650])
    safe_link = html.escape(item["link"], quote=True)
    header_line = f"<i>{html.escape(badge)}</i>\n" if badge else ""
    caption = f'{header_line}<b>{safe_title}</b>\n\n🔗 <a href="{safe_link}">Baca Selengkapnya</a>'

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
                "text": f"✅ Koneksi sukses! @{bot_username} terhubung dan siap menerima hasil scraping.",
            },
            timeout=10,
        ).json()
        if not send.get("ok"):
            return False, f"Gagal kirim ke Chat ID: {send.get('description', 'Error')}"
        return True, f"Terhubung ke @{bot_username}"
    except Exception as e:
        return False, str(e)
