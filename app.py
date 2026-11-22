from urllib.parse import urljoin
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Web Scraper ke Telegram", page_icon="🤖", layout="centered")
st.title("🤖 Web Scraper ke Telegram")

# Ambil konfigurasi dari Streamlit Secrets jika tersedia (opsional)
default_token = ""
default_chat_id = ""
try:
    default_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "AAEdUnWdpv78l2sGcgOJay69zAGFR7lfdvE")
    default_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "5874026623")
except Exception:
    pass

# --- Sidebar: Konfigurasi Telegram ---
with st.sidebar:
    st.header("Konfigurasi Telegram")
    bot_token = st.text_input(
        "Bot Token",
        value=default_token,
        type="password",
        placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    )
    chat_id = st.text_input(
        "Chat ID",
        value=default_chat_id,
        placeholder="Contoh: 987654321 atau -100123456789",
    )
    st.caption("Dapatkan Bot Token dari @BotFather dan Chat ID dari @userinfobot.")


# --- Fungsi Scraping ---
def scrape_website(url: str, css_selector: str, limit: int) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    elements = soup.select(css_selector)

    results = []
    seen = set()

    for el in elements:
        text = el.get_text(strip=True)

        raw_link = None
        if el.name == "a" and el.has_attr("href"):
            raw_link = el["href"]
        else:
            a_tag = el.find("a", href=True)
            if a_tag:
                raw_link = a_tag["href"]

        full_link = urljoin(url, raw_link) if raw_link else None

        if text and text not in seen:
            seen.add(text)
            entry = f"{text}\n🔗 {full_link}" if full_link else text
            results.append(entry)
            if len(results) >= limit:
                break

    return results


# --- Fungsi Kirim ke Telegram ---
def send_to_telegram(token: str, target_chat_id: str, text: str) -> None:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    max_length = 4000
    chunks = [text[i : i + max_length] for i in range(0, len(text), max_length)]

    for chunk in chunks:
        payload = {
            "chat_id": target_chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        res = requests.post(api_url, json=payload, timeout=15)
        res.raise_for_status()


# --- Form Input Utama ---
url_input = st.text_input("URL Website Target", placeholder="https://news.ycombinator.com")

col1, col2 = st.columns([3, 1])
with col1:
    selector_input = st.text_input(
        "CSS Selector",
        value=".titleline > a",
        placeholder="Contoh: h2, .article-title, a",
    )
with col2:
    limit_input = st.number_input("Maks. Hasil", min_value=1, max_value=100, value=10)

if "scraped_data" not in st.session_state:
    st.session_state.scraped_data = []

# --- Langkah 1: Jalankan Scraping ---
if st.button("🔍 Mulai Scraping", use_container_width=True):
    if not url_input or not selector_input:
        st.warning("Harap isi URL Website dan CSS Selector terlebih dahulu.")
    else:
        with st.spinner("Mengambil data dari website..."):
            try:
                data = scrape_website(url_input, selector_input, limit_input)
                st.session_state.scraped_data = data
                if data:
                    st.success(f"Berhasil mengambil {len(data)} item!")
                else:
                    st.info("Tidak ada elemen yang cocok dengan CSS Selector tersebut.")
            except Exception as e:
                st.error(f"Gagal melakukan scraping: {e}")

# --- Langkah 2: Preview & Kirim ke Telegram ---
if st.session_state.scraped_data:
    st.subheader("Hasil Scraping")
    formatted_message = f"📌 Hasil Scraping dari:\n{url_input}\n\n" + "\n\n".join(
        f"{i}. {item}" for i, item in enumerate(st.session_state.scraped_data, start=1)
    )

    edited_message = st.text_area(
        "Edit pesan sebelum dikirim (opsional):",
        value=formatted_message,
        height=250,
    )

    if st.button("📨 Kirim ke Telegram", type="primary", use_container_width=True):
        if not bot_token or not chat_id:
            st.warning("Harap isi Bot Token dan Chat ID di sidebar sebelah kiri.")
        else:
            with st.spinner("Mengirim pesan ke Telegram..."):
                try:
                    send_to_telegram(bot_token, chat_id, edited_message)
                    st.success("Pesan berhasil dikirim ke Telegram!")
                except requests.exceptions.HTTPError as http_err:
                    st.error(f"Error dari API Telegram: {http_err.response.text}")
                except Exception as e:
                    st.error(f"Terjadi kesalahan: {e}")
