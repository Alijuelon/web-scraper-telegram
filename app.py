import html
import threading
import time
from urllib.parse import urlparse

import streamlit as st

from scraper_engine import (
    load_urls_file,
    poll_and_handle_telegram_commands,
    save_urls_file,
    send_item_to_telegram,
    smart_scrape,
    test_telegram_connection,
)

st.set_page_config(
    page_title="ScrapGram Pro • Auto Web Scraper ke Telegram",
    page_icon="⚡",
    layout="wide",
)

# --- Custom CSS ---
st.markdown(
    """
    <style>
    .hero-box {
        background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 55%, #06b6d4 100%);
        padding: 1.7rem 2rem;
        border-radius: 16px;
        color: #ffffff;
        margin-bottom: 1.3rem;
        box-shadow: 0 10px 25px -5px rgba(6, 182, 212, 0.25);
    }
    .hero-box h1 {
        margin: 0;
        font-size: 1.85rem;
        font-weight: 800;
        color: #ffffff;
    }
    .hero-box p {
        margin: 0.4rem 0 0 0;
        color: #e0f2fe;
        font-size: 0.96rem;
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
        font-size: 1rem;
        font-weight: 700;
        line-height: 1.35;
        margin-bottom: 0.5rem;
    }
    .card-summary {
        font-size: 0.86rem;
        color: #cbd5e1;
        line-height: 1.45;
        margin-bottom: 0.65rem;
        display: -webkit-box;
        -webkit-line-clamp: 4;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .card-link {
        font-size: 0.82rem;
        color: #38bdf8 !important;
        text-decoration: none;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

URLS_FILE = "urls.json"

# --- Ambil Secrets ---
default_token = ""
default_chat_id = ""
gh_token = ""
gh_repo = ""
try:
    default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "8754619232:AAH6FR7HO8s0CdGdnU6JflELl94IKHM2FTg")
    default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "5874026623")
    gh_token = st.secrets.get("GITHUB_TOKEN", "")
    gh_repo = st.secrets.get("GITHUB_REPO", "")
except Exception:
    pass


# --- Background Thread Listener Telegram ---
@st.cache_resource
def start_telegram_listener_worker(token: str, chat_id: str, g_token: str, g_repo: str) -> bool:
    if not token or not chat_id:
        return False

    def _worker():
        while True:
            try:
                poll_and_handle_telegram_commands(
                    token=token,
                    allowed_chat_id=chat_id,
                    urls_file=URLS_FILE,
                    gh_token=g_token,
                    gh_repo=g_repo,
                )
            except Exception:
                pass
            time.sleep(4)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return True


def dispatch_items_to_telegram(token: str, target_chat_id: str, items: list[dict], source_url: str) -> int:
    """Mengirim daftar item (gambar + judul + ringkasan) ke Telegram dengan progress bar."""
    progress = st.progress(0, text="Mengirim otomatis ke Telegram...")
    sent_photos = 0
    domain_badge = urlparse(source_url).netloc

    for i, item in enumerate(items, start=1):
        progress.progress(i / len(items), text=f"Mengirim berita {i}/{len(items)} ke Telegram...")
        is_photo = send_item_to_telegram(
            token=token,
            chat_id=target_chat_id,
            item=item,
            source_url=source_url,
            badge=f"📌 {domain_badge}",
        )
        if is_photo:
            sent_photos += 1
        time.sleep(0.4)

    progress.empty()
    return sent_photos


# --- Session State ---
if "saved_urls" not in st.session_state:
    st.session_state.saved_urls = load_urls_file(URLS_FILE)
if "active_url" not in st.session_state:
    st.session_state.active_url = st.session_state.saved_urls[0]["url"]
if "active_selector" not in st.session_state:
    st.session_state.active_selector = st.session_state.saved_urls[0].get("selector", "")
if "active_limit" not in st.session_state:
    st.session_state.active_limit = st.session_state.saved_urls[0].get("limit", 4)
if "scraped_items" not in st.session_state:
    st.session_state.scraped_items = []
if "last_scraped_url" not in st.session_state:
    st.session_state.last_scraped_url = ""

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("## 🤖 Koneksi Telegram")
    bot_token = st.text_input("Bot Token", value=default_token, type="password", placeholder="123456:ABC-DEF...")
    chat_id = st.text_input("Chat ID / Channel ID", value=default_chat_id, placeholder="987654321 atau -100123...")

    listener_active = start_telegram_listener_worker(bot_token, chat_id, gh_token, gh_repo)
    if listener_active:
        st.success("🟢 Listener Perintah Telegram Aktif")

    if st.button("🔌 Tes Koneksi Bot", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Isi Bot Token dan Chat ID dahulu.")
        else:
            with st.spinner("Menguji koneksi..."):
                ok, msg = test_telegram_connection(bot_token, chat_id)
                st.success(msg) if ok else st.error(msg)

    st.divider()
    st.markdown("## 📌 Website Tersimpan")
    st.session_state.saved_urls = load_urls_file(URLS_FILE)
    for idx, entry in enumerate(st.session_state.saved_urls):
        c1, c2 = st.columns([4, 1])
        with c1:
            if st.button(f"🌐 {entry['name']}", key=f"load_{idx}", use_container_width=True):
                st.session_state.active_url = entry["url"]
                st.session_state.active_selector = entry.get("selector", "")
                st.session_state.active_limit = entry.get("limit", 4)
                st.rerun()
        with c2:
            if len(st.session_state.saved_urls) > 1:
                if st.button("🗑️", key=f"del_{idx}", help="Hapus"):
                    st.session_state.saved_urls.pop(idx)
                    save_urls_file(st.session_state.saved_urls, URLS_FILE, gh_token, gh_repo)
                    st.rerun()

    if st.button("🚀 Scrape & Kirim Semua Favorit", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Isi Bot Token dan Chat ID dahulu.")
        else:
            for entry in st.session_state.saved_urls:
                with st.spinner(f"Memproses {entry['name']}..."):
                    try:
                        batch_items, _ = smart_scrape(
                            url=entry["url"],
                            custom_selector=entry.get("selector", ""),
                            limit=int(entry.get("limit", 4)),
                            include_summary=True,
                        )
                        if batch_items:
                            dispatch_items_to_telegram(bot_token, chat_id, batch_items, entry["url"])
                    except Exception as e:
                        st.error(f"Gagal pada {entry['name']}: {e}")
            st.success("Semua website tersimpan selesai di-scrape dan dikirim ke Telegram!")

    st.divider()
    with st.expander("💬 Perintah via Chat Telegram"):
        st.markdown(
            "- `/scrape` — Scrape semua web tersimpan\n"
            "- `https://...` — Langsung tempel link di chat\n"
            "- `/list` — Lihat daftar tersimpan\n"
            "- `/add https://...` — Tambah web baru\n"
            "- `/del 1` — Hapus web nomor 1"
        )

# --- HEADER ---
st.markdown(
    """
    <div class="hero-box">
        <h1>⚡ ScrapGram Auto-Sender + Ringkasan Berita</h1>
        <p>Tempel URL website — otomatis mengekstrak gambar, judul, ringkasan isi berita, dan langsung mengirimkannya ke Telegram.</p>
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
            max_value=20,
            value=int(st.session_state.active_limit),
        )

    auto_send_tg = st.toggle(
        "📨 Auto-Kirim ke Telegram langsung setelah scraping selesai",
        value=True,
    )

    with st.expander("⚙️ Opsi Lanjutan"):
        custom_sel_input = st.text_input(
            "CSS Selector Manual (Kosong = Deteksi Otomatis)",
            value=st.session_state.active_selector,
            placeholder="Kosongkan untuk auto-detect",
        )
        include_summary_opt = st.checkbox(
            "Ambil ringkasan isi berita dari setiap halaman artikel",
            value=True,
        )

    btn_col1, btn_col2 = st.columns([3, 1])
    with btn_col1:
        btn_label = "🚀 Mulai Scraping & Auto-Kirim ke Telegram" if auto_send_tg else "🔍 Mulai Scraping Saja"
        run_btn = st.button(btn_label, type="primary", use_container_width=True)
    with btn_col2:
        save_btn = st.button("💾 Simpan Website", use_container_width=True)

if save_btn:
    if url_input:
        domain_label = urlparse(url_input).netloc.replace("www.", "") or url_input
        saved = load_urls_file(URLS_FILE)
        existing = next((item for item in saved if item["url"] == url_input), None)
        if existing:
            existing["selector"] = custom_sel_input
            existing["limit"] = int(limit_input)
        else:
            saved.append(
                {
                    "name": domain_label,
                    "url": url_input,
                    "selector": custom_sel_input,
                    "limit": int(limit_input),
                }
            )
        synced = save_urls_file(saved, URLS_FILE, gh_token, gh_repo)
        st.session_state.saved_urls = saved
        extra_note = " & tersinkron ke GitHub!" if synced else "."
        st.success(f"Website **{domain_label}** berhasil disimpan{extra_note}")

if run_btn:
    if not url_input:
        st.warning("Harap tempel URL website terlebih dahulu.")
    else:
        with st.spinner("Mengekstrak gambar, judul, dan merangkum isi setiap berita..."):
            try:
                items, _ = smart_scrape(
                    url=url_input,
                    custom_selector=custom_sel_input,
                    limit=int(limit_input),
                    include_summary=include_summary_opt,
                )
                st.session_state.scraped_items = items
                st.session_state.last_scraped_url = url_input

                if not items:
                    st.warning("Tidak ada artikel yang terdeteksi otomatis pada halaman ini.")
                elif auto_send_tg:
                    if not bot_token or not chat_id:
                        st.warning(
                            f"Berhasil mengambil {len(items)} berita, tetapi Bot Token / Chat ID di sidebar masih kosong sehingga belum terkirim."
                        )
                    else:
                        sent_photos = dispatch_items_to_telegram(bot_token, chat_id, items, url_input)
                        st.success(
                            f"Selesai! {len(items)} berita otomatis di-scrape & terkirim ke Telegram ({sent_photos} lengkap dengan foto)."
                        )
                else:
                    st.success(f"Berhasil mengambil {len(items)} berita lengkap dengan gambar & ringkasan!")
            except Exception as e:
                st.error(f"Gagal memproses website: {e}")

# --- PREVIEW & KIRIM ULANG ---
items = st.session_state.scraped_items
if items:
    st.subheader(f"📰 Pratinjau Hasil ({len(items)} Berita)")

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
                    if item.get("summary"):
                        st.markdown(
                            f'<div class="card-summary">{html.escape(item["summary"])}</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f'<a class="card-link" href="{html.escape(item["link"], quote=True)}" target="_blank">Baca Selengkapnya ↗</a>',
                        unsafe_allow_html=True,
                    )

    st.divider()
    if st.button("📨 Kirim Ulang Semua Berita ke Telegram", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Harap isi Bot Token dan Chat ID di sidebar sebelah kiri.")
        else:
            try:
                sent_photos = dispatch_items_to_telegram(
                    bot_token, chat_id, items, st.session_state.last_scraped_url
                )
                st.success(f"Terkirim ulang! {len(items)} berita masuk ke Telegram ({sent_photos} dengan foto).")
            except Exception as e:
                st.error(f"Gagal mengirim ke Telegram: {e}")
