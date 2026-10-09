"""
downloader.py

Downloads audio from YouTube Music URLs using yt-dlp.
Supports MP3 (requires ffmpeg) and best-quality M4A/WebM (no ffmpeg needed).
"""

import os
import shutil
import threading
import zipfile
import time
import traceback
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_PATH = shutil.which("ffmpeg")

# ── Directory setup ───────────────────────────────────────────────────────────
# Use os.path.abspath to guarantee a real absolute path in all environments
_BASE_DIR = os.path.abspath(os.path.dirname(__file__))

if os.environ.get("VERCEL"):
    DOWNLOADS_DIR = "/tmp/downloads"
elif os.environ.get("RENDER"):
    # On Render, store inside the project folder (ephemeral disk, always writable)
    DOWNLOADS_DIR = os.path.join(_BASE_DIR, "downloads")
else:
    # Locally: save into the user's own Downloads folder
    DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
print(f"[downloader] DOWNLOADS_DIR = {DOWNLOADS_DIR} (exists={os.path.isdir(DOWNLOADS_DIR)})")

# Path where the uploaded YouTube cookies.txt file is stored
COOKIE_FILE = os.path.join(_BASE_DIR, "youtube_cookies.txt")


def _get_cookie_file() -> str | None:
    """Return the cookie file path if it exists, otherwise None."""
    if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 10:
        print(f"[downloader] Using cookie file: {COOKIE_FILE}")
        return COOKIE_FILE
    return None


# In-memory download job tracker (dict is shared because we force 1 gunicorn worker)
download_jobs: dict = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_ffmpeg() -> bool:
    return FFMPEG_PATH is not None


def ffmpeg_available() -> bool:
    return _has_ffmpeg()


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
        "quiet": False,
        "no_warnings": False,
        "nooverwrites": False,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if FFMPEG_PATH:
        base["ffmpeg_location"] = FFMPEG_PATH

    # Attach cookies if available — bypasses YouTube bot detection on server IPs
    cookie_file = _get_cookie_file()
    if cookie_file:
        base["cookiefile"] = cookie_file

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
                "key": "FFmpegMetadata",
                "add_metadata": True,
                "add_chapters": False,
            },
        ]
        return base, "mp3"
    else:
        base["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
        if use_ffmpeg:
            base["postprocessors"] = [{
                "key": "FFmpegMetadata",
                "add_metadata": True,
                "add_chapters": False,
            }]
        return base, None  # ext determined after download


# ── Single-track download ─────────────────────────────────────────────────────

def download_single(youtube_url: str, title: str, artist: str, quality: str = "best") -> str:
    """
    Download a single track from a YouTube Music URL.
    Filename format: "Song Name - Artist.ext"
    Returns the absolute path to the downloaded file.
    """
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    # Song name first, then artist
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


# ── Playlist download (background thread) ─────────────────────────────────────

def _playlist_download_worker(job_id: str, tracks: list, playlist_name: str, quality: str):
    """Background thread: download all tracks into a sub-folder, then ZIP them up."""
    total = len(tracks)
    download_jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": total,
        "done": [],
        "failed": [],
        "folder": "",
        "zip_path": None,
        "zip_name": None,
        "eta_seconds": None,
        "zip_error": None,
    }

    # ── Create a playlist-specific sub-folder ─────────────────────────────────
    safe_folder = _sanitize(playlist_name)
    # Always use an absolute path so yt-dlp has no ambiguity
    playlist_dir = os.path.abspath(os.path.join(DOWNLOADS_DIR, safe_folder))
    os.makedirs(playlist_dir, exist_ok=True)
    download_jobs[job_id]["folder"] = playlist_dir
    print(f"[downloader] playlist_dir = {playlist_dir}")

    use_ffmpeg = _has_ffmpeg()
    print(f"[downloader] ffmpeg available = {use_ffmpeg}, path = {FFMPEG_PATH}")

    _shared_opts, _ext = _build_ydl_opts("PLACEHOLDER", quality, use_ffmpeg)
    ydl_opts = {k: v for k, v in _shared_opts.items() if k != "outtmpl"}
    ext = _ext

    start_time = time.time()

    for i, track in enumerate(tracks):
        yt_url = track.get("youtube_music_url") or track.get("youtube_url", "")
        name = track.get("track_name") or track.get("name", "Unknown")
        artists = track.get("artists", [])
        artist_str = ", ".join(artists) if isinstance(artists, list) else str(artists)

        if not yt_url:
            print(f"[downloader] Skipping '{name}' — no YouTube URL")
            download_jobs[job_id]["failed"].append(name)
            download_jobs[job_id]["progress"] = i + 1
            continue

        # Song name first, then artist — e.g. "Song Name - Artist.mp3"
        safe_name = _sanitize(f"{name} - {artist_str}" if artist_str else name)
        out_template = os.path.join(playlist_dir, f"{safe_name}.%(ext)s")
        print(f"[downloader] [{i+1}/{total}] Downloading: '{safe_name}' from {yt_url}")
        print(f"[downloader]   outtmpl = {out_template}")

        try:
            opts = {**ydl_opts, "outtmpl": out_template}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(yt_url, download=True)
                # Log the actual file yt-dlp wrote
                actual_filename = ydl.prepare_filename(info)
                print(f"[downloader]   yt-dlp wrote: {actual_filename}")
                # Verify the file actually exists
                if os.path.exists(actual_filename):
                    print(f"[downloader]   ✅ File confirmed on disk: {actual_filename}")
                else:
                    # Try with known extensions (post-processor may have changed it)
                    for try_ext in ["m4a", "webm", "opus", "mp3"]:
                        candidate = os.path.join(playlist_dir, f"{safe_name}.{try_ext}")
                        if os.path.exists(candidate):
                            print(f"[downloader]   ✅ File found with ext '{try_ext}': {candidate}")
                            break
                    else:
                        print(f"[downloader]   ⚠️ File NOT found at expected path! Listing dir:")
                        for f in os.listdir(playlist_dir):
                            print(f"[downloader]     - {f}")

            download_jobs[job_id]["done"].append(name)
        except Exception as e:
            print(f"[downloader]   ❌ Exception downloading '{name}': {e}")
            traceback.print_exc()
            download_jobs[job_id]["failed"].append(name)

        download_jobs[job_id]["progress"] = i + 1

        # Calculate ETA
        elapsed = time.time() - start_time
        avg_time = elapsed / (i + 1)
        download_jobs[job_id]["eta_seconds"] = int(avg_time * (total - (i + 1)))

    # ── List what's in the folder before zipping ─────────────────────────────
    print(f"[downloader] Files in playlist_dir before ZIP:")
    all_files_in_dir = []
    for root, dirs, files in os.walk(playlist_dir):
        for f in files:
            full = os.path.join(root, f)
            all_files_in_dir.append(full)
            print(f"  {full}  ({os.path.getsize(full)} bytes)")
    print(f"[downloader] Total files found: {len(all_files_in_dir)}")

    # ── Create ZIP from the playlist folder ──────────────────────────────────
    zip_path = os.path.abspath(os.path.join(DOWNLOADS_DIR, f"{safe_folder}.zip"))
    print(f"[downloader] Creating ZIP at: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in all_files_in_dir:
                arcname = os.path.basename(file_path)  # flat structure, no sub-dirs
                zf.write(file_path, arcname=arcname)
                print(f"[downloader]   Added to ZIP: {arcname}")

        zip_size = os.path.getsize(zip_path)
        print(f"[downloader] ✅ ZIP ready: {zip_path} ({zip_size} bytes)")
        download_jobs[job_id]["zip_path"] = zip_path
        download_jobs[job_id]["zip_name"] = f"{safe_folder}.zip"

    except Exception as e:
        print(f"[downloader] ❌ ZIP creation failed: {e}")
        traceback.print_exc()
        download_jobs[job_id]["zip_error"] = f"ZIP creation failed: {e}"

    # Mark the job done regardless of whether zip succeeded
    download_jobs[job_id]["status"] = "done"
    print(f"[downloader] Job {job_id} complete. done={len(download_jobs[job_id]['done'])}, failed={len(download_jobs[job_id]['failed'])}")


def start_playlist_download(job_id: str, tracks: list, playlist_name: str, quality: str = "best"):
    """Launch a background playlist download job."""
    t = threading.Thread(
        target=_playlist_download_worker,
        args=(job_id, tracks, playlist_name, quality),
        daemon=True,
    )
    t.start()
