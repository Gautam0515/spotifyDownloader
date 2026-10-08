from __future__ import annotations
from typing import Optional
from ytmusicapi import YTMusic
import re


# Initialize YTMusic in unauthenticated mode (search only — no login required)
ytmusic = YTMusic()


def search_youtube_music(track_name: str, artists: list, duration_ms: int = 0) -> Optional[dict]:
    """
    Search YouTube Music for a given track and return the best match.
    Returns a dict with videoId, title, artists, duration, and full URL.
    """
    query = f"{track_name} {', '.join(artists[:2])}"  # Use up to 2 artists for query

    try:
        results = ytmusic.search(query, filter="songs", limit=5)
    except Exception as e:
        print(f"[YTMusic] Search error for '{query}': {e}")
        return None

    if not results:
        # Fallback: search without filter
        try:
            results = ytmusic.search(query, limit=5)
        except Exception:
            return None

    best = pick_best_match(results, track_name, artists, duration_ms)
    return best


def pick_best_match(results: list, track_name: str, artists: list, duration_ms: int) -> Optional[dict]:
    """
    Pick the best matching result based on title similarity and duration proximity.
    """
    if not results:
        return None

    target_name_lower = track_name.lower()
    target_artists_lower = [a.lower() for a in artists]
    target_duration_sec = duration_ms / 1000 if duration_ms else 0

    scored = []
    for result in results:
        video_id = result.get("videoId")
        if not video_id:
            continue

        result_title = result.get("title", "")
        result_artists = [a.get("name", "") for a in result.get("artists", [])]
        result_duration = result.get("duration_seconds", 0) or 0

        score = 0

        # Title match
        if target_name_lower in result_title.lower() or result_title.lower() in target_name_lower:
            score += 50
        elif fuzzy_contains(target_name_lower, result_title.lower()):
            score += 25

        # Artist match
        for artist_lower in target_artists_lower:
            for result_artist in result_artists:
                if artist_lower in result_artist.lower() or result_artist.lower() in artist_lower:
                    score += 30
                    break

        # Duration proximity (±10 seconds is good)
        if target_duration_sec and result_duration:
            diff = abs(target_duration_sec - result_duration)
            if diff <= 5:
                score += 20
            elif diff <= 10:
                score += 10
            elif diff <= 30:
                score += 5

        result_thumbnail = ""
        thumbnails = result.get("thumbnails", [])
        if thumbnails:
            result_thumbnail = thumbnails[-1].get("url", "")

        scored.append({
            "score": score,
            "videoId": video_id,
            "title": result_title,
            "artists": result_artists,
            "artist_string": ", ".join(result_artists),
            "duration_str": result.get("duration", ""),
            "thumbnail": result_thumbnail,
            "youtube_music_url": f"https://music.youtube.com/watch?v={video_id}",
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        })

    if not scored:
        return None

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[0]


def fuzzy_contains(a: str, b: str) -> bool:
    """Check if most words of 'a' are present in 'b'."""
    words = re.findall(r'\w+', a)
    if not words:
        return False
    matches = sum(1 for w in words if w in b)
    return matches / len(words) >= 0.6
