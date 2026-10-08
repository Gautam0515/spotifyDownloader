"""
spotify_reader.py

Scrapes track data from Spotify's public embed page.
- NO API keys needed
- NO OAuth / login
- NO tokens
- Works for any public playlist by parsing the Next.js JSON Spotify embeds in the page
"""

import requests
import json
import re
import os


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://open.spotify.com/",
}


# ── Stubs so app.py doesn't need changes ───────────────────────────────────
def is_logged_in() -> bool:
    return True

def get_auth_url() -> str:
    return "/"

def handle_callback(code: str) -> bool:
    return True

def logout():
    pass


# ── Core ────────────────────────────────────────────────────────────────────

def extract_playlist_id(url: str) -> str:
    url = url.strip()
    if "playlist/" in url:
        return url.split("playlist/")[-1].split("?")[0].strip()
    if url.startswith("spotify:playlist:"):
        return url.split("spotify:playlist:")[-1].strip()
    return url.strip()


def _fetch_embed_data(playlist_id: str) -> dict:
    """
    Fetch the Spotify embed page and extract the __NEXT_DATA__ JSON blob
    that Spotify inlines in all their embed pages.
    """
    embed_url = (
        f"https://open.spotify.com/embed/playlist/{playlist_id}"
        f"?utm_source=generator&theme=0"
    )
    resp = requests.get(embed_url, headers=_HEADERS, timeout=20)

    if resp.status_code == 404:
        raise ValueError("Playlist not found (404). Check the link is correct.")
    if resp.status_code == 403:
        raise ValueError(
            "Cannot access this playlist (403). "
            "Make sure it is set to PUBLIC in Spotify."
        )
    if resp.status_code != 200:
        raise ValueError(f"Spotify embed returned HTTP {resp.status_code}.")

    # Extract inline Next.js JSON
    match = re.search(
        r'<script\s+id=["\']__NEXT_DATA__["\'][^>]*>([^<]+)</script>',
        resp.text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(
            "Could not find track data in the Spotify embed page. "
            "Spotify may have changed their page format."
        )

    return json.loads(match.group(1))


def _parse_tracks_from_next_data(data: dict) -> tuple:
    """
    Parse playlist metadata and tracks from the __NEXT_DATA__ structure.
    Returns (meta_dict, list_of_tracks).
    Handles Spotify's varying data shapes.
    """
    props = data.get("props", {})
    page_props = props.get("pageProps", {})

    # Shape 1: props.pageProps.state.data.entity  (older embed format)
    entity = (
        page_props
        .get("state", {})
        .get("data", {})
        .get("entity", {})
    )

    # Shape 2: props.pageProps.entity  (newer embed format)
    if not entity:
        entity = page_props.get("entity", {})

    # Shape 3: some versions wrap differently
    if not entity:
        entity = page_props.get("data", {}).get("playlistV2", {})

    if not entity:
        raise ValueError(
            "Unexpected Spotify embed structure — could not locate track list. "
            "The playlist may be private or Spotify changed their embed format."
        )

    playlist_name = entity.get("name", "") or entity.get("__typename", "Unknown Playlist")

    # Owner
    owner_data = entity.get("ownerV2", {}).get("data", {})
    owner = owner_data.get("name") or entity.get("owner", {}).get("display_name", "Unknown")

    # Cover image
    visuals = entity.get("visuals", {}) or {}
    cover_sources = (
        visuals.get("headerImage", {}).get("sources", []) or
        visuals.get("thumbnail", {}).get("sources", []) or
        []
    )
    playlist_image = cover_sources[0].get("url") if cover_sources else None

    # Description
    description = entity.get("description", "")

    # Track list — try multiple keys
    track_list = (
        entity.get("trackList") or
        entity.get("tracks", {}).get("items") or
        []
    )

    tracks = []
    for item in track_list:
        if not item:
            continue

        # Unwrap if wrapped in {track: ...}
        if "track" in item and isinstance(item["track"], dict):
            item = item["track"]

        raw_id = item.get("id") or item.get("uri", "")
        track_id = raw_id.replace("spotify:track:", "").split("?")[0]
        if not track_id:
            continue

        name = item.get("title") or item.get("name") or "Unknown"

        # Artists
        artists_raw = item.get("artists") or []
        if artists_raw and isinstance(artists_raw[0], dict):
            artist_names = [a.get("name", "") for a in artists_raw]
        else:
            subtitle = item.get("subtitle", "")
            artist_names = [subtitle] if subtitle else ["Unknown"]

        # Duration
        duration_ms = item.get("duration") or item.get("duration_ms") or 0

        # Album art
        cover_art = item.get("coverArt", {}) or {}
        art_sources = cover_art.get("sources", []) or []
        album_art = art_sources[0].get("url", "") if art_sources else ""

        # Album name
        album_info = item.get("album", {}) or {}
        album_name = album_info.get("name", "") if isinstance(album_info, dict) else ""

        tracks.append({
            "id": track_id,
            "name": name,
            "artists": artist_names,
            "artist_string": ", ".join(artist_names),
            "album": album_name,
            "album_art": album_art,
            "duration_ms": duration_ms,
            "duration_str": ms_to_min(duration_ms),
            "spotify_url": f"https://open.spotify.com/track/{track_id}",
            "popularity": item.get("popularity", 0),
        })

    return {
        "playlist_name": playlist_name or "Unknown Playlist",
        "description": description,
        "image": playlist_image,
        "owner": owner or "Unknown",
    }, tracks


def get_playlist_tracks(playlist_url: str) -> dict:
    """
    Fetch all tracks from a public Spotify playlist by scraping the embed page.
    No API key or login required.
    """
    playlist_id = extract_playlist_id(playlist_url)
    raw = _fetch_embed_data(playlist_id)
    meta, tracks = _parse_tracks_from_next_data(raw)

    if not tracks:
        raise ValueError(
            "No tracks found in this playlist, or the playlist is empty/private."
        )

    return {
        **meta,
        "total_tracks": len(tracks),
        "tracks": tracks,
    }


def ms_to_min(ms: int) -> str:
    seconds = (ms or 0) // 1000
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"
