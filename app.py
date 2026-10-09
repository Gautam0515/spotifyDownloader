import json
import csv
import io
import os
import threading
import uuid
from flask import Flask, render_template, request, jsonify, Response, send_file
from database import init_db, save_playlist, save_track, get_all_playlists, get_playlist_tracks, get_playlist_by_id, delete_playlist
from spotify_reader import get_playlist_tracks as fetch_spotify_tracks
from ytmusic_searcher import search_youtube_music
from downloader import download_single, start_playlist_download, ffmpeg_available, download_jobs, DOWNLOADS_DIR, COOKIE_FILE

app = Flask(__name__)
init_db()

# In-memory progress tracking per job

jobs: dict = {}


def process_playlist(job_id: str, spotify_url: str):
    """Background thread: fetch Spotify tracks, search YT Music, store results."""
    try:
        jobs[job_id] = {
            "status": "fetching_spotify",
            "progress": 0,
            "total": 0,
            "tracks": [],
            "error": None,
            "playlist_id": None,
            "playlist_name": None,
        }

        playlist_data = fetch_spotify_tracks(spotify_url)
        tracks = playlist_data["tracks"]
        total = len(tracks)

        playlist_id = save_playlist(spotify_url, playlist_data)

        jobs[job_id]["status"] = "searching_ytmusic"
        jobs[job_id]["total"] = total
        jobs[job_id]["playlist_id"] = playlist_id
        jobs[job_id]["playlist_name"] = playlist_data["playlist_name"]

        for i, track in enumerate(tracks):
            yt_result = search_youtube_music(
                track["name"],
                track["artists"],
                track["duration_ms"]
            )
            save_track(playlist_id, track, yt_result)

            jobs[job_id]["progress"] = i + 1
            jobs[job_id]["tracks"].append({
                "name": track["name"],
                "artist_string": track["artist_string"],
                "album_art": track.get("album_art", ""),
                "duration_str": track["duration_str"],
                "spotify_url": track["spotify_url"],
                "youtube_music_url": yt_result["youtube_music_url"] if yt_result else "",
                "youtube_url": yt_result["youtube_url"] if yt_result else "",
                "yt_title": yt_result["title"] if yt_result else "Not found",
                "yt_thumbnail": yt_result.get("thumbnail", "") if yt_result else "",
                "status": "found" if yt_result else "not_found",
            })

        jobs[job_id]["status"] = "done"

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        import traceback
        traceback.print_exc()


# ─── Main page ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    playlists = get_all_playlists()
    return render_template("index.html", playlists=playlists)


# ─── API endpoints ───────────────────────────────────────────────────────────

@app.route("/api/process", methods=["POST"])
def api_process():
    data = request.get_json()
    spotify_url = (data.get("url") or "").strip()
    if not spotify_url:
        return jsonify({"error": "No URL provided"}), 400

    import uuid
    job_id = str(uuid.uuid4())
    t = threading.Thread(target=process_playlist, args=(job_id, spotify_url), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/playlists")
def api_playlists():
    return jsonify(get_all_playlists())


@app.route("/api/playlists/<int:playlist_id>")
def api_playlist_detail(playlist_id):
    playlist = get_playlist_by_id(playlist_id)
    if not playlist:
        return jsonify({"error": "Not found"}), 404
    tracks = get_playlist_tracks(playlist_id)
    return jsonify({"playlist": playlist, "tracks": tracks})


@app.route("/api/playlists/<int:playlist_id>/delete", methods=["DELETE"])
def api_delete_playlist(playlist_id):
    delete_playlist(playlist_id)
    return jsonify({"ok": True})


# ─── Download endpoints ──────────────────────────────────────────────────────

@app.route("/api/ffmpeg-status")
def api_ffmpeg_status():
    return jsonify({"ffmpeg": ffmpeg_available()})


@app.route("/api/cookies/status")
def api_cookies_status():
    """Check if a cookies.txt file has been uploaded."""
    has_cookies = os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 10
    return jsonify({"has_cookies": has_cookies})


@app.route("/api/cookies/upload", methods=["POST"])
def api_cookies_upload():
    """Accept a cookies.txt file upload and save it for yt-dlp to use."""
    if "cookies" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["cookies"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    content = f.read().decode("utf-8", errors="ignore")
    # Basic sanity check — a Netscape cookie file starts with a known header
    if "HTTP Cookie File" not in content and "Netscape HTTP Cookie" not in content and "# Netscape" not in content:
        # Still allow it if it has youtube domains
        if "youtube.com" not in content and "google.com" not in content:
            return jsonify({"error": "File does not look like a YouTube cookies.txt — make sure to export from YouTube Music"}), 400
    with open(COOKIE_FILE, "w", encoding="utf-8") as out:
        out.write(content)
    print(f"[app] Cookies file saved to {COOKIE_FILE} ({len(content)} bytes)")
    return jsonify({"ok": True, "message": "Cookies saved! Downloads should now work."})


@app.route("/api/cookies/delete", methods=["DELETE"])
def api_cookies_delete():
    """Remove the saved cookies file."""
    if os.path.isfile(COOKIE_FILE):
        os.remove(COOKIE_FILE)
    return jsonify({"ok": True})


@app.route("/api/download/track")
def api_download_track():
    """Download a single track and stream it to the browser."""
    yt_url = request.args.get("url", "").strip()
    title  = request.args.get("title", "track").strip()
    artist = request.args.get("artist", "").strip()
    quality = request.args.get("quality", "best").strip()  # best | mp3 | mp3_192

    if not yt_url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        filepath = download_single(yt_url, title, artist, quality)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not os.path.exists(filepath):
        return jsonify({"error": "Download failed — file not found"}), 500

    ext = os.path.splitext(filepath)[1].lstrip(".")
    mimetype_map = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "webm": "audio/webm", "opus": "audio/ogg"}
    mime = mimetype_map.get(ext, "audio/mpeg")
    safe_name = f"{artist} - {title}.{ext}" if artist else f"{title}.{ext}"

    return send_file(
        filepath,
        mimetype=mime,
        as_attachment=True,
        download_name=safe_name,
    )


@app.route("/api/download/playlist/<int:playlist_id>", methods=["POST"])
def api_download_playlist(playlist_id):
    """Start a background job to download all (or selected) tracks in a playlist."""
    payload = request.get_json() or {}
    quality = payload.get("quality", "best")
    selected_urls = payload.get("selected_urls")  # Optional list of youtube URLs
    
    playlist = get_playlist_by_id(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404

    tracks = get_playlist_tracks(playlist_id)
    
    found_tracks = []
    for t in tracks:
        yt_url = t.get("youtube_music_url") or t.get("youtube_url")
        if not yt_url:
            continue
        # Filter if selected_urls is provided
        if selected_urls is not None and yt_url not in selected_urls:
            continue
        found_tracks.append(t)

    if not found_tracks:
        return jsonify({"error": "No tracks with YouTube links found"}), 400

    job_id = str(uuid.uuid4())
    start_playlist_download(job_id, found_tracks, playlist["playlist_name"], quality)
    return jsonify({"job_id": job_id, "total": len(found_tracks)})


@app.route("/api/download/status/<job_id>")
def api_download_status(job_id):
    job = download_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    # Return a copy of the job, but convert zip_path to a boolean
    # so the client knows if zip is ready without exposing server paths
    data = dict(job)
    data["zip_path"] = bool(job.get("zip_path") and os.path.exists(job["zip_path"]))
    return jsonify(data)


@app.route("/api/download/zip/<job_id>")
def api_download_zip(job_id):
    """Stream the completed ZIP file to the browser."""
    job = download_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found. Server may have restarted."}), 404

    zip_path = job.get("zip_path")
    zip_name = job.get("zip_name", "playlist.zip")

    if not zip_path or not os.path.exists(zip_path):
        # Check for a zip_error to give a better message
        if job.get("zip_error"):
            return jsonify({"error": job["zip_error"]}), 500
        return jsonify({"error": "ZIP file not ready yet. Please wait a moment and try again."}), 404

    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_name,
    )



@app.route("/api/playlists/<int:playlist_id>/export/json")
def export_json(playlist_id):
    playlist = get_playlist_by_id(playlist_id)
    tracks = get_playlist_tracks(playlist_id)
    data = {"playlist": playlist, "tracks": tracks}
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=playlist_{playlist_id}.json"}
    )


@app.route("/api/playlists/<int:playlist_id>/export/csv")
def export_csv(playlist_id):
    playlist = get_playlist_by_id(playlist_id)
    tracks = get_playlist_tracks(playlist_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Track Name", "Artists", "Album", "Duration",
                     "Spotify URL", "YouTube Music URL", "YouTube URL", "Status"])
    for t in tracks:
        writer.writerow([
            t["track_name"],
            ", ".join(t["artists"]),
            t["album"],
            t["duration_str"],
            t["spotify_url"],
            t["youtube_music_url"],
            t["youtube_url"],
            t["status"],
        ])
    output.seek(0)
    name = (playlist["playlist_name"] if playlist else "playlist").replace(" ", "_")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={name}.csv"}
    )


if __name__ == "__main__":
    init_db()
    print("\n  Spotify -> YouTube Music Converter")
    print("=" * 40)
    print("  Open: http://127.0.0.1:5000")
    print("=" * 40 + "\n")
    app.run(debug=False, threaded=True, use_reloader=False)
