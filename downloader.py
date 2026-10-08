"""
downloader.py

Downloads audio from YouTube Music URLs using yt-dlp.
Supports MP3 (requires ffmpeg) and best-quality M4A/WebM (no ffmpeg needed).
"""

import os
import shutil
import tempfile
import threading
import zipfile
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = shutil.which("ffmpeg")

import time
if os.environ.get("VERCEL") or os.environ.get("RENDER"):
    DOWNLOADS_DIR = "/tmp/downloads"
else:
    DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


# In-memory download job tracker
download_jobs: dict = {}


def _has_ffmpeg() -> bool:
    return FFMPEG_PATH is not None


def _sanitize(name: str) -> str:
    """Remove characters that are invalid in filenames."""
    bad = r'\/:*?"<>|'
    for ch in bad:
        name = name.replace(ch, "")
    return name.strip()[:100]

def _build_ydl_opts(out_template: str, quality: str, use_ffmpeg: bool) -> tuple:
    """
    Build yt-dlp options dict for a given quality.
    Returns (ydl_opts, expected_ext).
    """
    base = {
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "nooverwrites": False,         # allow overwrite to avoid stale partials
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if FFMPEG_PATH:
        base["ffmpeg_location"] = FFMPEG_PATH

    if quality.startswith("mp3") and use_ffmpeg:
        bitrate = "320" if quality == "mp3" else "192"
        base["format"] = "bestaudio/best"
        base["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            },
            {
                # Embeds title, artist, album, date into the MP3 ID3 tags
                "key": "FFmpegMetadata",
                "add_metadata": True,
                "add_chapters": False,
            },
        ]
        return base, "mp3"
    else:
        base["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
        if use_ffmpeg:
            # Still embed metadata even without transcoding
            base["postprocessors"] = [{
                "key": "FFmpegMetadata",
                "add_metadata": True,
                "add_chapters": False,
            }]
        return base, None  # ext determined after download


def download_single(youtube_url: str, title: str, artist: str, quality: str = "best") -> str:
    """
    Download a single track from a YouTube Music URL.
    Filename format: "Song Name - Artist.ext"
    Returns the path to the downloaded file.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    # Song first, then artist
    safe_name = _sanitize(f"{title} - {artist}" if artist else title)
    out_template = os.path.join(DOWNLOADS_DIR, f"{safe_name}.%(ext)s")

    use_ffmpeg = _has_ffmpeg()
    ydl_opts, ext = _build_ydl_opts(out_template, quality, use_ffmpeg)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        if ext:
            filepath = os.path.join(DOWNLOADS_DIR, f"{safe_name}.{ext}")
        else:
            actual_ext = info.get("ext", "m4a")
            filepath = os.path.join(DOWNLOADS_DIR, f"{safe_name}.{actual_ext}")

    return filepath


def _playlist_download_worker(job_id: str, tracks: list, folder_name: str, quality: str):
    """Background thread: download all tracks in a playlist."""
    total = len(tracks)
    download_jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": total,
        "done": [],
        "failed": [],
        "folder": "",
        # zip_path removed — ZIP creation is disabled
        "eta_seconds": None,
        "error": None,
    }

    playlist_dir = os.path.join(DOWNLOADS_DIR, _sanitize(folder_name))
    os.makedirs(playlist_dir, exist_ok=True)
    download_jobs[job_id]["folder"] = playlist_dir

    use_ffmpeg = _has_ffmpeg()
    # Build shared ydl_opts using helper (placeholder outtmpl, overridden per-track)
    _shared_opts, _ext = _build_ydl_opts("PLACEHOLDER", quality, use_ffmpeg)
    ydl_opts = {k: v for k, v in _shared_opts.items() if k != "outtmpl"}
    ext = _ext

    start_time = time.time()
    for i, track in enumerate(tracks):
        yt_url = track.get("youtube_music_url") or track.get("youtube_url", "")
        name = track.get("track_name") or track.get("name", "Unknown")
        artists = track.get("artists", [])
        if isinstance(artists, list):
            artist_str = ", ".join(artists)
        else:
            artist_str = str(artists)

        if not yt_url:
            download_jobs[job_id]["failed"].append(name)
            download_jobs[job_id]["progress"] = i + 1
            continue

        # Song name first, then artist — e.g. "Song Name - Artist.mp3"
        safe_name = _sanitize(f"{name} - {artist_str}" if artist_str else name)
        out_template = os.path.join(playlist_dir, f"{safe_name}.%(ext)s")

        try:
            opts = {**ydl_opts, "outtmpl": out_template}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([yt_url])
            download_jobs[job_id]["done"].append(name)
        except Exception as e:
            download_jobs[job_id]["failed"].append(name)

        download_jobs[job_id]["progress"] = i + 1
        
        # Calculate ETA
        elapsed = time.time() - start_time
        avg_time_per_track = elapsed / (i + 1)
        remaining_tracks = total - (i + 1)
        download_jobs[job_id]["eta_seconds"] = int(avg_time_per_track * remaining_tracks)

    safe_folder = _sanitize(playlist_name)
    zip_path = os.path.join(DOWNLOADS_DIR, f"{safe_folder}.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(playlist_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zf.write(file_path, arcname=file)
        
        # We NO LONGER delete the playlist_dir! The user wants the folder to stay on the server.
        download_jobs[job_id]["zip_path"] = zip_path
        download_jobs[job_id]["zip_name"] = f"{safe_folder}.zip"
    except Exception as e:
        print(f"ZIPPING ERROR: {e}")
        import traceback
        traceback.print_exc()
        download_jobs[job_id]["error"] = f"Zipping failed: {e}"

    download_jobs[job_id]["status"] = "done"


def start_playlist_download(job_id: str, tracks: list, playlist_name: str, quality: str = "best"):
    """Launch a background playlist download job."""
    t = threading.Thread(
        target=_playlist_download_worker,
        args=(job_id, tracks, playlist_name, quality),
        daemon=True,
    )
    t.start()


def ffmpeg_available() -> bool:
    return _has_ffmpeg()
