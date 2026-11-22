import html
import io
import time
from urllib.parse import urljoin, urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from PIL import Image

# --- Konfigurasi Halaman ---
st.set_page_config(
    page_title="ScrapGram • Web Scraper ke Telegram",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS untuk Tampilan Modern ---
st.markdown(
    """
    <style>
    /* Header Banner */
    .hero-banner {
        background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #0284c7 100%);
        padding: 2rem 2.2rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 10px 25px -5px rgba(2, 132, 199, 0.25);
        border: 1px solid rgba(255, 255, 255, 0.12);
    }
    .hero-banner h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #ffffff;
    }
    .hero-banner p {
        margin: 0.5rem 0 0 0;
        font-size: 1rem;
        color: #e0f2fe;
        opacity: 0.92;
    }

    /* Kartu Statistik */
    .stat-card {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 12px;
        padding: 1rem 1.2rem;
        text-align: center;
    }
    .stat-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #38bdf8;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #94a3b8;
        margin-top: 0.2rem;
    }

    /* Kartu Hasil Scraping */
    .scrape-card {
        background: rgba(30, 41, 59, 0.45);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 14px;
        padding: 1rem;
        margin-bottom: 1rem;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .scrape-card:hover {
        border-color: #38bdf8;
    }
    .card-badge {
        display: inline-block;
        background: rgba(56, 189, 248, 0.15);
        color: #38bdf8;
        font-size: 0.75rem;
        font-weight: 600;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        margin-bottom: 0.5rem;
    }
    .card-title {
        font-size: 1rem;
        font-weight: 600;
        line-height: 1.4;
        margin-bottom: 0.6rem;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .card-link {
        font-size: 0.82rem;
        color: #38bdf8 !important;
        text-decoration: none;
        font-weight: 500;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Ambil Secrets jika tersedia di Streamlit Cloud ---
default_token = ""
default_chat_id = ""
try:
    default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "AAEdUnWdpv78l2sGcgOJay69zAGFR7lfdvE")
    default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "5874026623")
except Exception:
    pass

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# --- Fungsi Helper Gambar ---
def extract_image_url(element, base_url: str) -> str | None:
    """Mencari URL gambar dari tag <img> di dalam elemen maupun atribut lazy-load."""
    img_tag = element if element.name == "img" else element.find("img")
    if not img_tag:
        return None

    for attr in ["src", "data-src", "data-lazy-src", "data-original", "data-url"]:
        val = img_tag.get(attr)
        if val and not val.startswith("data:image"):
            return urljoin(base_url, val.strip())

    srcset = img_tag.get("srcset") or img_tag.get("data-srcset")
    if srcset:
        first_candidate = srcset.split(",")[0].strip().split(" ")[0]
        if first_candidate and not first_candidate.startswith("data:image"):
            return urljoin(base_url, first_candidate)

    return None


def download_and_convert_image(img_url: str, referer: str) -> io.BytesIO | None:
    """Mengunduh gambar dan mengonversinya ke JPEG agar 100% kompatibel dengan Telegram."""
    try:
        req_headers = {**HEADERS, "Referer": referer}
        resp = requests.get(img_url, headers=req_headers, timeout=12)
        resp.raise_for_status()

        img = Image.open(io.BytesIO(resp.content))
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize jika dimensi terlalu besar (Telegram max dimensi foto 10000px / 10MB)
        img.thumbnail((1600, 1600))

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=88)
        output.seek(0)
        return output
    except Exception:
        return None


# --- Fungsi Scraping ---
def scrape_website(
    url: str,
    item_selector: str,
    title_selector: str,
    img_selector: str,
    limit: int,
    use_og_fallback: bool,
) -> tuple[list[dict], str | None]:
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Ambil OpenGraph cover image website sebagai cadangan
    og_meta = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    cover_image = urljoin(url, og_meta["content"].strip()) if og_meta and og_meta.get("content") else None

    elements = soup.select(item_selector)
    results = []
    seen_titles = set()

    for el in elements:
        # 1. Ekstrak Judul / Teks
        if title_selector.strip():
            title_el = el.select_one(title_selector.strip())
            title = title_el.get_text(" ", strip=True) if title_el else ""
        else:
            title = el.get_text(" ", strip=True)

        if not title or title in seen_titles:
            continue

        # 2. Ekstrak Tautan
        raw_link = None
        if el.name == "a" and el.has_attr("href"):
            raw_link = el["href"]
        else:
            a_tag = el.find("a", href=True)
            if a_tag:
                raw_link = a_tag["href"]
        full_link = urljoin(url, raw_link) if raw_link else None

        # 3. Ekstrak Gambar
        img_url = None
        if img_selector.strip():
            custom_img_el = el.select_one(img_selector.strip())
            if custom_img_el:
                img_url = extract_image_url(custom_img_el, url)
        else:
            img_url = extract_image_url(el, url)

        if not img_url and use_og_fallback:
            img_url = cover_image

        seen_titles.add(title)
        results.append(
            {
                "title": title,
                "link": full_link,
                "image": img_url,
            }
        )

        if len(results) >= limit:
            break

    return results, cover_image


# --- Fungsi Telegram ---
def test_telegram_bot(token: str, target_chat_id: str) -> tuple[bool, str]:
    try:
        me_res = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        if not me_res.get("ok"):
            return False, f"Token tidak valid: {me_res.get('description', 'Error')}"
        bot_name = me_res["result"].get("username", "Bot")

        msg_res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": target_chat_id,
                "text": f"✅ Koneksi berhasil! @{bot_name} siap menerima hasil scraping.",
            },
            timeout=10,
        ).json()
        if not msg_res.get("ok"):
            return False, f"Gagal kirim ke Chat ID: {msg_res.get('description', 'Error')}"

        return True, f"Terhubung ke @{bot_name}!"
    except Exception as e:
        return False, str(e)


def send_item_with_photo(token: str, target_chat_id: str, item: dict, index: int, source_url: str) -> bool:
    """Mengirim satu item hasil scraping beserta gambarnya ke Telegram."""
    safe_title = html.escape(item["title"][:700])
    caption_parts = [f"<b>{index}. {safe_title}</b>"]
    if item.get("link"):
        safe_link = html.escape(item["link"], quote=True)
        caption_parts.append(f'🔗 <a href="{safe_link}">Buka Tautan</a>')
    caption = "\n\n".join(caption_parts)

    if item.get("image"):
        img_bytes = download_and_convert_image(item["image"], referer=source_url)
        if img_bytes:
            res = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={
                    "chat_id": target_chat_id,
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                },
                files={"photo": ("scraped.jpg", img_bytes, "image/jpeg")},
                timeout=20,
            )
            if res.ok:
                return True

    # Fallback jika gambar tidak tersedia atau gagal diunduh
    res = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": target_chat_id,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    res.raise_for_status()
    return False


def send_summary_with_cover(
    token: str,
    target_chat_id: str,
    items: list[dict],
    source_url: str,
    cover_image: str | None,
) -> None:
    """Mengirim 1 gambar cover diikuti daftar teks lengkap."""
    header_caption = f"📌 <b>Hasil Scraping Website</b>\n🌐 {html.escape(source_url)}\n📊 Total: {len(items)} item"

    if cover_image:
        img_bytes = download_and_convert_image(cover_image, referer=source_url)
        if img_bytes:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={
                    "chat_id": target_chat_id,
                    "caption": header_caption[:1024],
                    "parse_mode": "HTML",
                },
                files={"photo": ("cover.jpg", img_bytes, "image/jpeg")},
                timeout=20,
            )

    lines = []
    for idx, item in enumerate(items, start=1):
        t = html.escape(item["title"])
        if item.get("link"):
            l = html.escape(item["link"], quote=True)
            lines.append(f'<b>{idx}.</b> <a href="{l}">{t}</a>')
        else:
            lines.append(f"<b>{idx}.</b> {t}")

    full_text = f"{header_caption}\n\n" + "\n\n".join(lines)
    max_len = 4000
    for i in range(0, len(full_text), max_len):
        res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": target_chat_id,
                "text": full_text[i : i + max_len],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        res.raise_for_status()


# --- Inisialisasi Session State ---
if "scraped_items" not in st.session_state:
    st.session_state.scraped_items = []
if "cover_image" not in st.session_state:
    st.session_state.cover_image = None
if "last_url" not in st.session_state:
    st.session_state.last_url = ""

# --- SIDEBAR: Pengaturan Telegram ---
with st.sidebar:
    st.markdown("## 🤖 Koneksi Telegram")
    bot_token = st.text_input(
        "Bot Token",
        value=default_token,
        type="password",
        placeholder="123456:ABC-DEF1234...",
        help="Dapatkan dari @BotFather di Telegram",
    )
    chat_id = st.text_input(
        "Chat ID / Channel ID",
        value=default_chat_id,
        placeholder="987654321 atau -100123...",
        help="Dapatkan dari @userinfobot",
    )

    if st.button("🔌 Tes Koneksi Bot", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Isi Bot Token dan Chat ID terlebih dahulu.")
        else:
            with st.spinner("Menguji koneksi..."):
                ok, msg = test_telegram_bot(bot_token, chat_id)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    st.divider()
    st.markdown("## 🖼️ Mode Pengiriman")
    send_mode = st.radio(
        "Pilih format pesan Telegram:",
        options=[
            "Kartu Bergambar (1 Foto + Caption per Item)",
            "Ringkasan Teks + 1 Gambar Cover",
        ],
        index=0,
    )
    st.caption(
        "Mode Kartu Bergambar mengirim setiap item sebagai foto terpisah. "
        "Jika item tidak memiliki gambar, otomatis dikirim sebagai teks."
    )

# --- HEADER UTAMA ---
st.markdown(
    """
    <div class="hero-banner">
        <h1>🚀 ScrapGram Visual Scraper</h1>
        <p>Ekstrak judul, tautan, dan gambar dari website mana pun, lalu kirim langsung ke Telegram dalam bentuk kartu visual.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- PANEL INPUT SCRAPING ---
with st.container(border=True):
    col_url, col_limit = st.columns([4, 1])
    with col_url:
        url_input = st.text_input(
            "🌐 URL Website Target",
            placeholder="https://books.toscrape.com",
            value="https://books.toscrape.com",
        )
    with col_limit:
        limit_input = st.number_input("🔢 Maks. Item", min_value=1, max_value=50, value=6)

    col_sel, col_opt = st.columns([3, 2])
    with col_sel:
        item_selector = st.text_input(
            "🎯 CSS Selector Wadah Item (Card / Artikel)",
            value="article.product_pod",
            placeholder="Contoh: article, .post-card, .product_pod",
            help="Pilih elemen pembungkus yang memuat judul, link, dan gambar sekaligus.",
        )
    with col_opt:
        st.write("")
        st.write("")
        use_og_fallback = st.checkbox(
            "Gunakan gambar cover web jika item tanpa foto",
            value=True,
        )

    with st.expander("⚙️ Pengaturan Selector Lanjutan (Opsional)"):
        adv_col1, adv_col2 = st.columns(2)
        with adv_col1:
            title_selector = st.text_input(
                "CSS Selector Khusus Judul (di dalam wadah)",
                value="h3 a",
                placeholder="Kosongkan untuk ambil semua teks wadah",
            )
        with adv_col2:
            img_selector = st.text_input(
                "CSS Selector Khusus Gambar (di dalam wadah)",
                value="img",
                placeholder="Default: otomatis cari tag <img>",
            )

    scrape_clicked = st.button("🔍 Mulai Scraping Website", type="primary", use_container_width=True)

if scrape_clicked:
    if not url_input or not item_selector:
        st.warning("Harap isi URL Website dan CSS Selector Wadah Item.")
    else:
        with st.spinner("Sedang mengekstrak konten & gambar..."):
            try:
                items, cover = scrape_website(
                    url=url_input,
                    item_selector=item_selector,
                    title_selector=title_selector,
                    img_selector=img_selector,
                    limit=limit_input,
                    use_og_fallback=use_og_fallback,
                )
                st.session_state.scraped_items = items
                st.session_state.cover_image = cover
                st.session_state.last_url = url_input

                if not items:
                    st.info("Tidak ditemukan elemen yang cocok dengan CSS Selector tersebut.")
            except Exception as e:
                st.error(f"Gagal melakukan scraping: {e}")

# --- TAMPILAN HASIL & KIRIM KE TELEGRAM ---
items = st.session_state.scraped_items
if items:
    img_count = sum(1 for it in items if it.get("image"))
    domain_name = urlparse(st.session_state.last_url).netloc

    # Baris Statistik
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(
            f'<div class="stat-card"><div class="stat-value">{len(items)}</div>'
            f'<div class="stat-label">Total Item Diambil</div></div>',
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            f'<div class="stat-card"><div class="stat-value">{img_count}</div>'
            f'<div class="stat-label">Item dengan Gambar</div></div>',
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f'<div class="stat-card"><div class="stat-value">{domain_name}</div>'
            f'<div class="stat-label">Sumber Website</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # Tab Pratinjau Visual vs Daftar Teks
    tab_visual, tab_raw = st.tabs(["🖼️ Pratinjau Kartu Visual", "📝 Daftar Teks & URL Gambar"])

    with tab_visual:
        cols_per_row = 3
        for row_start in range(0, len(items), cols_per_row):
            row_cols = st.columns(cols_per_row)
            for idx_offset, col in enumerate(row_cols):
                item_idx = row_start + idx_offset
                if item_idx >= len(items):
                    break
                item = items[item_idx]
                with col:
                    with st.container(border=True):
                        if item.get("image"):
                            st.image(item["image"], use_container_width=True)
                        else:
                            st.info("Tanpa gambar")

                        st.markdown(f'<span class="card-badge">Item #{item_idx + 1}</span>', unsafe_allow_html=True)
                        st.markdown(f'<div class="card-title">{html.escape(item["title"])}</div>', unsafe_allow_html=True)
                        if item.get("link"):
                            st.markdown(
                                f'<a class="card-link" href="{html.escape(item["link"], quote=True)}" target="_blank">Buka Tautan ↗</a>',
                                unsafe_allow_html=True,
                            )

    with tab_raw:
        for idx, item in enumerate(items, start=1):
            st.markdown(f"**{idx}. {item['title']}**")
            st.caption(f"Link: {item.get('link') or '-'} | Gambar: {item.get('image') or '-'}")

    st.divider()

    # Tombol Kirim ke Telegram
    if st.button("📨 Kirim Semua Hasil ke Telegram Sekarang", type="primary", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Harap isi Bot Token dan Chat ID di sidebar sebelah kiri.")
        else:
            try:
                if send_mode.startswith("Kartu Bergambar"):
                    progress_bar = st.progress(0, text="Memulai pengiriman ke Telegram...")
                    photo_sent = 0
                    for idx, item in enumerate(items, start=1):
                        progress_bar.progress(
                            idx / len(items),
                            text=f"Mengirim item {idx} dari {len(items)} ke Telegram...",
                        )
                        is_photo = send_item_with_photo(
                            token=bot_token,
                            target_chat_id=chat_id,
                            item=item,
                            index=idx,
                            source_url=st.session_state.last_url,
                        )
                        if is_photo:
                            photo_sent += 1
                        time.sleep(0.35)  # Jeda aman agar tidak terkena rate-limit Telegram
                    progress_bar.empty()
                    st.success(f"Selesai! {len(items)} item terkirim ke Telegram ({photo_sent} dengan foto).")
                else:
                    with st.spinner("Mengirim ringkasan & gambar cover ke Telegram..."):
                        cover_to_use = st.session_state.cover_image or next(
                            (it["image"] for it in items if it.get("image")), None
                        )
                        send_summary_with_cover(
                            token=bot_token,
                            target_chat_id=chat_id,
                            items=items,
                            source_url=st.session_state.last_url,
                            cover_image=cover_to_use,
                        )
                    st.success("Ringkasan & gambar cover berhasil dikirim ke Telegram!")
            except requests.exceptions.HTTPError as http_err:
                st.error(f"Error dari API Telegram: {http_err.response.text}")
            except Exception as e:
                st.error(f"Terjadi kesalahan saat mengirim: {e}")
