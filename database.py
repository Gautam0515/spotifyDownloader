from __future__ import annotations
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

if os.environ.get("VERCEL") or os.environ.get("RENDER"):
    DB_PATH = "/tmp/playlists.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "playlists.db")



def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spotify_url TEXT UNIQUE,
            playlist_name TEXT,
            owner TEXT,
            image TEXT,
            description TEXT,
            total_tracks INTEGER,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER,
            spotify_id TEXT,
            track_name TEXT,
            artists TEXT,
            album TEXT,
            album_art TEXT,
            duration_str TEXT,
            spotify_url TEXT,
            youtube_music_url TEXT,
            youtube_url TEXT,
            yt_title TEXT,
            yt_artists TEXT,
            yt_thumbnail TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(playlist_id) REFERENCES playlists(id)
        )
    """)
    conn.commit()
    conn.close()


def save_playlist(spotify_url: str, meta: dict) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO playlists
            (spotify_url, playlist_name, owner, image, description, total_tracks, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        spotify_url,
        meta["playlist_name"],
        meta["owner"],
        meta.get("image", ""),
        meta.get("description", ""),
        meta["total_tracks"],
        datetime.now().isoformat()
    ))
    playlist_id = c.lastrowid
    conn.commit()
    conn.close()
    return playlist_id


def save_track(playlist_id: int, track: dict, yt_result: Optional[dict]):
    conn = get_conn()
    c = conn.cursor()

    yt_url = yt_result["youtube_music_url"] if yt_result else ""
    yt_yt_url = yt_result["youtube_url"] if yt_result else ""
    yt_title = yt_result["title"] if yt_result else ""
    yt_artists = json.dumps(yt_result["artists"]) if yt_result else "[]"
    yt_thumbnail = yt_result.get("thumbnail", "") if yt_result else ""
    status = "found" if yt_result else "not_found"

    c.execute("""
        INSERT OR REPLACE INTO tracks
            (playlist_id, spotify_id, track_name, artists, album, album_art,
             duration_str, spotify_url, youtube_music_url, youtube_url,
             yt_title, yt_artists, yt_thumbnail, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        playlist_id,
        track["id"],
        track["name"],
        json.dumps(track["artists"]),
        track["album"],
        track.get("album_art", ""),
        track["duration_str"],
        track["spotify_url"],
        yt_url,
        yt_yt_url,
        yt_title,
        yt_artists,
        yt_thumbnail,
        status,
    ))
    conn.commit()
    conn.close()


def get_all_playlists() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM playlists ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_playlist_tracks(playlist_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM tracks WHERE playlist_id = ?", (playlist_id,))
    rows = []
    for r in c.fetchall():
        row = dict(r)
        row["artists"] = json.loads(row["artists"])
        row["yt_artists"] = json.loads(row["yt_artists"])
        rows.append(row)
    conn.close()
    return rows


def get_playlist_by_id(playlist_id: int) -> Optional[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_playlist(playlist_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM tracks WHERE playlist_id = ?", (playlist_id,))
    c.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    conn.commit()
    conn.close()
