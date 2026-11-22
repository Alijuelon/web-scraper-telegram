import base64
import html
import json
import os
import time
from urllib.parse import urlparse

import requests
import streamlit as st

from scraper_engine import (
    send_item_to_telegram,
    smart_scrape,
    test_telegram_connection,
)

st.set_page_config(
    page_title="ScrapGram Auto • Web Scraper ke Telegram",
    page_icon="⚡",
    layout="wide",
)

# --- Custom CSS ---
st.markdown(
    """
    <style>
    .hero-box {
        background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 55%, #06b6d4 100%);
        padding: 1.8rem 2rem;
        border-radius: 16px;
        color: #ffffff;
        margin-bottom: 1.4rem;
        box-shadow: 0 10px 25px -5px rgba(6, 182, 212, 0.25);
    }
    .hero-box h1 {
        margin: 0;
        font-size: 1.9rem;
        font-weight: 800;
        color: #ffffff;
    }
    .hero-box p {
        margin: 0.4rem 0 0 0;
        color: #e0f2fe;
        font-size: 0.98rem;
    }
    .card-badge {
        display: inline-block;
        background: rgba(56, 189, 248, 0.16);
        color: #38bdf8;
        font-size: 0.75rem;
        font-weight: 600;
        padding: 0.18rem 0.6rem;
        border-radius: 999px;
        margin-bottom: 0.45rem;
    }
    .card-title {
        font-size: 0.98rem;
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

URLS_FILE = "urls.json"


# --- Manajemen Bookmark URL ---
def load_saved_urls() -> list[dict]:
    if os.path.exists(URLS_FILE):
        try:
            with open(URLS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [{"name": "Detik News", "url": "https://news.detik.com/", "selector": "", "limit": 5}]


def sync_urls_to_github(urls_data: list[dict]) -> tuple[bool, str]:
    """Menyimpan perubahan urls.json langsung ke repository GitHub jika Secrets tersedia."""
    try:
        gh_token = st.secrets.get("GITHUB_TOKEN", "")
        gh_repo = st.secrets.get("GITHUB_REPO", "")  # contoh: "Alijuelon/web-scraper-telegram"
    except Exception:
        return False, "Tersimpan lokal (tambahkan GITHUB_TOKEN & GITHUB_REPO di Secrets untuk sinkron ke GitHub)."

    if not gh_token or not gh_repo:
        return False, "Tersimpan di sesi aktif. Untuk permanen saat Auto-Schedule, simpan juga di file urls.json GitHub."

    api_url = f"https://api.github.com/repos/{gh_repo}/contents/{URLS_FILE}"
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
    }

    sha = None
    get_res = requests.get(api_url, headers=headers, timeout=10)
    if get_res.status_code == 200:
        sha = get_res.json().get("sha")

    content_b64 = base64.b64encode(json.dumps(urls_data, indent=2, ensure_ascii=False).encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update daftar URL scraping dari aplikasi",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    put_res = requests.put(api_url, headers=headers, json=payload, timeout=15)
    if put_res.status_code in (200, 201):
        return True, "Tersimpan & tersinkron otomatis ke GitHub (ikut jalan di Auto-Schedule)!"
    return False, f"Tersimpan lokal, gagal sinkron GitHub: {put_res.status_code}"


def save_urls(urls_data: list[dict]) -> str:
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(urls_data, f, indent=2, ensure_ascii=False)
    _, status_msg = sync_urls_to_github(urls_data)
    return status_msg


# --- Ambil Secrets ---
default_token = ""
default_chat_id = ""
try:
    default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
except Exception:
    pass

# --- Session State ---
if "saved_urls" not in st.session_state:
    st.session_state.saved_urls = load_saved_urls()
if "active_url" not in st.session_state:
    st.session_state.active_url = st.session_state.saved_urls[0]["url"]
if "active_selector" not in st.session_state:
    st.session_state.active_selector = st.session_state.saved_urls[0].get("selector", "")
if "active_limit" not in st.session_state:
    st.session_state.active_limit = st.session_state.saved_urls[0].get("limit", 5)
if "scraped_items" not in st.session_state:
    st.session_state.scraped_items = []
if "last_scraped_url" not in st.session_state:
    st.session_state.last_scraped_url = ""

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("## 🤖 Koneksi Telegram")
    bot_token = st.text_input("Bot Token", value=default_token, type="password", placeholder="123456:ABC-DEF...")
    chat_id = st.text_input("Chat ID / Channel ID", value=default_chat_id, placeholder="987654321 atau -100123...")

    if st.button("🔌 Tes Koneksi Bot", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Isi Bot Token dan Chat ID dahulu.")
        else:
            with st.spinner("Menguji koneksi..."):
                ok, msg = test_telegram_connection(bot_token, chat_id)
                st.success(msg) if ok else st.error(msg)

    st.divider()
    st.markdown("## 📌 Website Tersimpan")
    for idx, entry in enumerate(st.session_state.saved_urls):
        c1, c2 = st.columns([4, 1])
        with c1:
            if st.button(f"🌐 {entry['name']}", key=f"load_{idx}", use_container_width=True):
                st.session_state.active_url = entry["url"]
                st.session_state.active_selector = entry.get("selector", "")
                st.session_state.active_limit = entry.get("limit", 5)
                st.rerun()
        with c2:
            if len(st.session_state.saved_urls) > 1:
                if st.button("🗑️", key=f"del_{idx}", help="Hapus"):
                    st.session_state.saved_urls.pop(idx)
                    save_urls(st.session_state.saved_urls)
                    st.rerun()

    st.divider()
    st.markdown("## ⏰ Status Auto-Schedule")
    st.info(
        "Jadwal otomatis berjalan lewat tab **Actions** di repository GitHub kamu "
        "meskipun browser & HP dalam keadaan mati."
    )

# --- HEADER ---
st.markdown(
    """
    <div class="hero-box">
        <h1>⚡ ScrapGram Smart Scraper</h1>
        <p>Cukup tempel URL website — deteksi judul & gambar otomatis, simpan favorit, dan kirim ke Telegram.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- FORM UTAMA ---
with st.container(border=True):
    col_u, col_l = st.columns([4, 1])
    with col_u:
        url_input = st.text_input(
            "🔗 Tempel Alamat Website (Tanpa Perlu CSS Selector)",
            value=st.session_state.active_url,
            placeholder="https://news.detik.com/",
        )
    with col_l:
        limit_input = st.number_input(
            "🔢 Jumlah Berita",
            min_value=1,
            max_value=30,
            value=int(st.session_state.active_limit),
        )

    with st.expander("⚙️ Opsi Lanjutan (Opsional — Biarkan Kosong untuk Mode Otomatis)"):
        custom_sel_input = st.text_input(
            "CSS Selector Manual (Kosong = Deteksi Otomatis)",
            value=st.session_state.active_selector,
            placeholder="Kosongkan saja untuk auto-detect",
        )
        deep_img = st.checkbox(
            "Ambil gambar utama artikel jika thumbnail tidak tersedia",
            value=True,
        )

    btn_col1, btn_col2 = st.columns([3, 1])
    with btn_col1:
        run_btn = st.button("🚀 Mulai Scraping Otomatis", type="primary", use_container_width=True)
    with btn_col2:
        save_btn = st.button("💾 Simpan Website", use_container_width=True)

if save_btn:
    if url_input:
        domain_label = urlparse(url_input).netloc.replace("www.", "") or url_input
        existing = next((item for item in st.session_state.saved_urls if item["url"] == url_input), None)
        if existing:
            existing["selector"] = custom_sel_input
            existing["limit"] = int(limit_input)
        else:
            st.session_state.saved_urls.append(
                {
                    "name": domain_label,
                    "url": url_input,
                    "selector": custom_sel_input,
                    "limit": int(limit_input),
                }
            )
        msg = save_urls(st.session_state.saved_urls)
        st.success(f"Website **{domain_label}** berhasil disimpan! {msg}")

if run_btn:
    if not url_input:
        st.warning("Harap tempel URL website terlebih dahulu.")
    else:
        with st.spinner("Mendeteksi berita dan mengambil gambar secara otomatis..."):
            try:
                items, _ = smart_scrape(
                    url=url_input,
                    custom_selector=custom_sel_input,
                    limit=int(limit_input),
                    deep_fetch_image=deep_img,
                )
                st.session_state.scraped_items = items
                st.session_state.last_scraped_url = url_input
                if items:
                    st.success(f"Berhasil mengekstrak {len(items)} berita beserta gambar!")
                else:
                    st.warning(
                        "Tidak ada artikel yang terdeteksi otomatis. Website ini kemungkinan membutuhkan JavaScript."
                    )
            except Exception as e:
                st.error(f"Gagal mengakses website: {e}")

# --- PREVIEW & KIRIM TELEGRAM ---
items = st.session_state.scraped_items
if items:
    st.subheader(f"📰 Pratinjau Hasil ({len(items)} Item)")

    cols_per_row = 3
    for row_start in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row)
        for offset, col in enumerate(cols):
            idx = row_start + offset
            if idx >= len(items):
                break
            item = items[idx]
            with col:
                with st.container(border=True):
                    if item.get("image"):
                        st.image(item["image"], use_container_width=True)
                    st.markdown(f'<span class="card-badge">#{idx + 1}</span>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="card-title">{html.escape(item["title"])}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<a class="card-link" href="{html.escape(item["link"], quote=True)}" target="_blank">Buka Artikel ↗</a>',
                        unsafe_allow_html=True,
                    )

    st.divider()
    if st.button("📨 Kirim Semua Berita + Gambar ke Telegram", type="primary", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Harap isi Bot Token dan Chat ID di sidebar sebelah kiri.")
        else:
            progress = st.progress(0, text="Mengirim ke Telegram...")
            sent_photos = 0
            try:
                domain_badge = urlparse(st.session_state.last_scraped_url).netloc
                for i, item in enumerate(items, start=1):
                    progress.progress(i / len(items), text=f"Mengirim {i}/{len(items)}...")
                    is_photo = send_item_to_telegram(
                        token=bot_token,
                        chat_id=chat_id,
                        item=item,
                        source_url=st.session_state.last_scraped_url,
                        badge=f"📌 {domain_badge}",
                    )
                    if is_photo:
                        sent_photos += 1
                    time.sleep(0.4)
                progress.empty()
                st.success(f"Terkirim! {len(items)} berita masuk ke Telegram ({sent_photos} lengkap dengan gambar).")
            except Exception as e:
                st.error(f"Gagal mengirim ke Telegram: {e}")
