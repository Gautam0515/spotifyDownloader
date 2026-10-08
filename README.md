# SpotiSync – Spotify → YouTube Music Converter

## 🚀 Quick Start

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Get Spotify API Keys (FREE)
1. Go to **https://developer.spotify.com/dashboard**
2. Log in → **Create App** → give it any name
3. Copy your **Client ID** and **Client Secret**

### 3. Create Your `.env` File
```bash
copy .env.example .env
```
Then open `.env` and paste your credentials:
```
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
```

### 4. Run the App
```bash
python app.py
```
Open **http://127.0.0.1:5000** in your browser 🎉

---

## ✨ Features
- 🎵 Reads **any public Spotify playlist**
- 🔍 Searches **YouTube Music** for every track (no YT auth needed!)
- 💾 Stores all links in **SQLite** database
- 📊 **Export to CSV or JSON** anytime
- 🔴 Live progress feed while processing
- 🌙 Beautiful dark glassmorphism UI

## 📁 Project Structure
```
songs downloader app/
├── app.py               ← Flask web server (run this)
├── spotify_reader.py    ← Spotify API integration
├── ytmusic_searcher.py  ← YouTube Music search
├── database.py          ← SQLite storage
├── requirements.txt     ← Python packages
├── .env                 ← Your API keys (create this)
├── templates/
│   └── index.html       ← Web UI
└── static/
    ├── style.css        ← Styles
    └── app.js           ← Frontend logic
```
