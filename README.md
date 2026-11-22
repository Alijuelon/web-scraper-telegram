# Web Scraper ke Telegram (Streamlit)

Aplikasi berbasis Python dan Streamlit untuk mengambil konten dari halaman web menggunakan CSS Selector dan mengirimkannya langsung ke Telegram Bot.

## Menjalankan Aplikasi Tanpa Laptop (100% Cloud via GitHub)

### Opsi A: Deploy Gratis ke Streamlit Community Cloud
1. Buka [share.streamlit.io](https://share.streamlit.io) dan login menggunakan akun GitHub.
2. Klik **New app** dan pilih repository ini.
3. Pastikan **Main file path** terisi `app.py`, lalu klik **Deploy**.
4. *(Opsional)* Agar tidak perlu mengetik token berulang kali, buka **App settings** -> **Secrets** di dashboard Streamlit dan isi:
   ```toml
   TELEGRAM_BOT_TOKEN = "isi_token_bot_kamu"
   TELEGRAM_CHAT_ID = "isi_chat_id_kamu"
