import sys
import datetime
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


def run_applescript(script: str) -> str:
    """Execute an AppleScript command via osascript and return its output."""
    if sys.platform != "darwin":
        return "Error: AppleScript is only supported on macOS."
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"
    return result.stdout.strip()


# --- Listening Journal & Analytics Persistence Layer ---
DB_PATH = Path.home() / ".mcp_applemusic_history.db"


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT,
            artist_name TEXT,
            album_name TEXT,
            duration_sec INTEGER,
            played_sec INTEGER,
            skipped INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _split_artists(artist_str: str, track_title: str = "") -> list:
    """
    Split collaborative artist strings (e.g. 'Dave & Kano', 'Dave, Burna Boy', 'Headie One feat. Dave')
    into individual canonical artist names matching Apple Music's exact artist attribution standards.
    """
    if not artist_str:
        return []
    raw = artist_str
    feat_match = re.search(r'\((?:feat\.|ft\.|with)\s+([^)]+)\)', track_title, re.IGNORECASE)
    if feat_match:
        raw += f" & {feat_match.group(1)}"

    tokens = re.split(r'\s*(?:&|,|\bfeat\.|\bft\.|\bwith\b|\bx\b|/)\s*', raw, flags=re.IGNORECASE)
    res = []
    seen = set()
    for t in tokens:
        cleaned = re.sub(r'^[(\[\'"]+|[)\]\'"]+$', '', t.strip()).strip()
        if cleaned and cleaned.lower() not in ["remix", "single", "deluxe", "edit", "version", "instrumental"]:
            if cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                res.append(cleaned)
    return res


def _log_play(track_name: str, artist_name: str, album_name: str, duration_sec: int, played_sec: int, skipped: int):
    if not track_name:
        return
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO plays (track_name, artist_name, album_name, duration_sec, played_sec, skipped, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (track_name, artist_name, album_name, duration_sec, played_sec, skipped, now_str))
        conn.commit()
        conn.close()
    except Exception:
        pass


# Background daemon tracker for automated listening history & scrobbling
_current_track_info = {"key": None, "track": None, "artist": None, "album": None, "duration": 0, "seconds_listened": 0, "last_pos": 0}
_tracker_lock = threading.Lock()


def _tracker_loop():
    if sys.platform != 'darwin':
        return
    global _current_track_info
    _init_db()
    while True:
        try:
            time.sleep(5)
            script = """
            tell application "System Events"
                if not (exists (process "Music")) then return "INACTIVE"
            end tell
            tell application "Music"
                if player state is playing then
                    set t to current track
                    set pos to player position as integer
                    set dur to duration of t as integer
                    return "PLAYING|||" & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "|||" & (pos as string) & "|||" & (dur as string)
                else
                    return "PAUSED"
                end if
            end tell
            """
            raw = run_applescript(script)
            if raw == "INACTIVE" or raw == "PAUSED" or raw.startswith("Error:"):
                continue

            if raw.startswith("PLAYING|||"):
                parts = raw.split("|||")
                if len(parts) >= 6:
                    t_name = parts[1]
                    a_name = parts[2]
                    al_name = parts[3]
                    try:
                        pos = int(parts[4])
                        dur = int(parts[5])
                    except ValueError:
                        pos = 0
                        dur = 0

                    track_key = (t_name, a_name)
                    with _tracker_lock:
                        if _current_track_info["key"] is None:
                            _current_track_info = {
                                "key": track_key,
                                "track": t_name,
                                "artist": a_name,
                                "album": al_name,
                                "duration": dur,
                                "seconds_listened": 5,
                                "last_pos": pos
                            }
                        elif _current_track_info["key"] == track_key:
                            if pos != _current_track_info["last_pos"]:
                                _current_track_info["seconds_listened"] += 5
                                _current_track_info["last_pos"] = pos
                        else:
                            prev = _current_track_info
                            seconds_listened = prev["seconds_listened"]
                            duration = prev["duration"]
                            threshold = min(30, duration // 2) if duration > 0 else 30
                            if seconds_listened >= threshold:
                                _log_play(prev["track"], prev["artist"], prev["album"], duration, seconds_listened, 0)
                            elif seconds_listened >= 3:
                                _log_play(prev["track"], prev["artist"], prev["album"], duration, seconds_listened, 1)

                            _current_track_info = {
                                "key": track_key,
                                "track": t_name,
                                "artist": a_name,
                                "album": al_name,
                                "duration": dur,
                                "seconds_listened": 5,
                                "last_pos": pos
                            }
        except Exception:
            pass


_tracker_thread = threading.Thread(target=_tracker_loop, daemon=True)
_tracker_thread.start()


# Instantiate the MCP server.
mcp = FastMCP("iTunesControlServer")



@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_play() -> str:
    """Start playback in Music (iTunes)."""
    script = 'tell application "Music" to play'
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_pause() -> str:
    """Pause playback in Music (iTunes)."""
    script = 'tell application "Music" to pause'
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_next() -> str:
    """Skip to the next track."""
    script = 'tell application "Music" to next track'
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_previous() -> str:
    """Return to the previous track."""
    script = 'tell application "Music" to previous track'
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_search(query: str) -> str:
    """
    Search the Music library for tracks whose names contain the given query.
    Returns a list of tracks formatted as "Track Name - Artist".
    """
    script = f"""
    tell application "Music"
        set results to search playlist "Library" for "{query}"
        set output to ""
        repeat with t in results
            set output to output & name of t & " - " & artist of t & "\n"
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_search_catalog(query: str, limit: int = 5) -> str:
    """
    Search the global Apple Music / iTunes Store catalog (outside user library).

    Args:
        query: Search term (song title, artist, or album).
        limit: Number of results to return (default 5, max 25).

    Returns:
        Formatted list of matching tracks from the global Apple Music catalog.
    """
    safe_limit = min(max(1, limit), 25)
    encoded_query = urllib.parse.quote(query)
    url = f"https://itunes.apple.com/search?term={encoded_query}&media=music&entity=song&limit={safe_limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("results", [])
            if not results:
                return f"No tracks found in Apple Music catalog for: '{query}'"

            output = []
            for item in results:
                track_name = item.get("trackName", "Unknown")
                artist_name = item.get("artistName", "Unknown")
                collection_name = item.get("collectionName", "Unknown Album")
                release_date = item.get("releaseDate", "")[:4]
                output.append(f"{track_name} - {artist_name} ({collection_name}, {release_date})")

            return "\n".join(output)
    except Exception as e:
        return f"Error querying iTunes catalog: {str(e)}"



@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_play_song(song: str) -> str:
    """
    Search for and play a specific song by name.
    Plays the first matching track found in the library.
    """
    script = f"""
    tell application "Music"
        set results to search playlist "Library" for "{song}"
        if results is not {{}} then
            play item 1 of results
            return "Now playing: " & name of item 1 of results & " - " & artist of item 1 of results
        else
            return "No tracks found matching: {song}"
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_create_playlist(name: str) -> str:
    """Create a new playlist in Music with the given name."""
    script = f"""
    tell application "Music"
        if not (exists playlist "{name}") then
            make new playlist with properties {{name:"{name}"}}
            return "Created playlist: {name}"
        else
            return "Playlist already exists: {name}"
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_add_to_playlist(song: str, playlist: str) -> str:
    """
    Search for a song by title across all playlists and add the first match
    to the named playlist.

    This tool searches across every user playlist (not just the main Library),
    which is necessary when tracks are sourced from Apple Music subscription
    or iCloud Music Library and may not appear in the default Library playlist.

    Args:
        song: The song title to search for.
        playlist: The name of the destination playlist.

    Returns:
        A status message indicating which track was added, or an error if not found.
    """
    script = f"""
    tell application "Music"
        set targetPlaylist to playlist "{playlist}"
        set searchTerm to "{song}"
        set seen to {{}}

        -- Search across all user playlists to handle iCloud/subscription tracks
        repeat with p in (every user playlist)
            try
                set allTracks to tracks of p
                repeat with t in allTracks
                    set tid to database ID of t as string
                    if seen does not contain tid then
                        set end of seen to tid
                        if (name of t) contains searchTerm then
                            duplicate t to targetPlaylist
                            return "Added: " & name of t & " - " & artist of t
                        end if
                    end if
                end repeat
            end try
        end repeat

        return "Not found: " & searchTerm
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_list_playlists() -> str:
    """
    List all playlists in the Music library with their track counts.

    Returns:
        A newline-separated list of playlists in the format "Playlist Name (N tracks)".
    """
    script = """
    tell application "Music"
        set output to ""
        repeat with p in (every user playlist)
            try
                set output to output & name of p & " (" & (count of tracks of p) & " tracks)\\n"
            end try
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_playlist_tracks(playlist: str) -> str:
    """
    Get all tracks in a named playlist.

    Args:
        playlist: The name of the playlist to inspect.

    Returns:
        A newline-separated list of tracks formatted as "Track Name - Artist".
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        set output to ""
        repeat with t in (tracks of playlist "{playlist}")
            set output to output & name of t & " - " & artist of t & "\\n"
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_current_track() -> str:
    """Get information about the currently playing track."""
    script = """
    tell application "Music"
        if player state is playing then
            set t to current track
            return "Now playing: " & name of t & " - " & artist of t & " (" & album of t & ")"
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_volume(volume: int) -> str:
    """Set the Music app volume (0-100)."""
    if not 0 <= volume <= 100:
        return "Error: Volume must be between 0 and 100."
    script = f'tell application "Music" to set sound volume to {volume}'
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_favorite_track(favorited: bool = True) -> str:
    """
    Favorite or unfavorite the currently playing track.

    Args:
        favorited: True to favorite/love the track, False to unfavorite.
    """
    val = "true" if favorited else "false"
    script = f"""
    tell application "Music"
        if player state is playing then
            set t to current track
            set favorited of t to {val}
            if {val} then
                set status to "Favorited"
            else
                set status to "Unfavorited"
            end if
            return status & ": " & name of t & " - " & artist of t
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_rate_track(stars: int) -> str:
    """
    Set a star rating (1 to 5 stars) for the currently playing track.

    Args:
        stars: Rating from 1 (lowest) to 5 (highest), or 0 to clear rating.
    """
    if not 0 <= stars <= 5:
        return "Error: Rating stars must be between 0 and 5."
    rating_val = stars * 20
    script = f"""
    tell application "Music"
        if player state is playing then
            set t to current track
            set rating of t to {rating_val}
            return "Set rating to " & {stars} & " star(s) for: " & name of t & " - " & artist of t
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
def itunes_get_lyrics(song: str = "") -> str:
    """
    Get lyrics for the currently playing track (or search lyrics for any song by title/artist).
    Uses embedded library lyrics first, with instant fallback to global lyrics database.

    Args:
        song: Optional title or 'Title Artist' of a specific song to search lyrics for. If empty, uses currently playing track.
    """
    artist = ""
    title = song.strip()
    embedded_lyrics = ""

    if not title:
        script = """
        tell application "Music"
            if player state is playing then
                set t to current track
                return (name of t) & "|||" & (artist of t) & "|||" & (lyrics of t)
            else
                return "NOT_PLAYING"
            end if
        end tell
        """
        raw = run_applescript(script)
        if raw == "NOT_PLAYING" or raw.startswith("Error:"):
            return "Music is not currently playing. Specify a song title (e.g. itunes_get_lyrics('Location Dave')) to search."
        parts = raw.split("|||")
        if len(parts) >= 2:
            title = parts[0]
            artist = parts[1]
            if len(parts) >= 3 and parts[2].strip():
                embedded_lyrics = parts[2].strip()

    if embedded_lyrics:
        return f"Lyrics for '{title}' - {artist} (from Library):\n\n{embedded_lyrics}"

    q = f"{title} {artist}".strip()
    try:
        url = f"https://lrclib.net/api/search?q={urllib.parse.quote(q)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    lyrics = item.get("plainLyrics") or item.get("syncedLyrics")
                    if lyrics:
                        t_name = item.get("trackName", title)
                        a_name = item.get("artistName", artist)
                        return f"Lyrics for '{t_name}' - {a_name}:\n\n{lyrics}"
    except Exception:
        pass

    return f"No lyrics found for: '{q}'"




@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_seek(seconds: int) -> str:
    """
    Seek/jump to a specific timestamp in seconds in the currently playing track.

    Args:
        seconds: Position in seconds from the start of the song.
    """
    if seconds < 0:
        return "Error: Seconds must be 0 or positive."
    script = f"""
    tell application "Music"
        if player state is playing then
            set player position to {seconds}
            return "Jumped to " & {seconds} & "s in: " & name of current track
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_position() -> str:
    """Get elapsed time and total duration for the currently playing track."""
    script = """
    tell application "Music"
        if player state is playing then
            set pos to player position as integer
            set dur to duration of current track as integer
            set posMin to pos div 60
            set posSec to pos mod 60
            set durMin to dur div 60
            set durSec to dur mod 60
            return "Position: " & posMin & "m" & posSec & "s / " & durMin & "m" & durSec & "s (" & name of current track & ")"
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_list_devices() -> str:
    """List all available AirPlay audio output devices and their selection state."""
    script = """
    tell application "Music"
        set output to ""
        repeat with d in (every AirPlay device)
            if selected of d then
                set sel to "[Active]"
            else
                set sel to "[Available]"
            end if
            set output to output & name of d & " " & sel & "\n"
        end repeat
        return output
    end tell
    """
    return run_applescript(script)



@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_device(device_name: str) -> str:
    """
    Switch audio output to a specific AirPlay device by name (e.g. HomePod, AirPods, TV).

    Args:
        device_name: The exact name of the AirPlay device.
    """
    script = f"""
    tell application "Music"
        try
            set selected of (first AirPlay device whose name is "{device_name}") to true
            return "Selected AirPlay device: {device_name}"
        on error
            return "AirPlay device not found: {device_name}"
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_export_playlist(playlist: str, format: str = "json") -> str:
    """
    Export all tracks in a named playlist to JSON, CSV, or Markdown.

    Args:
        playlist: The name of the playlist to export.
        format: Export format: 'json', 'csv', or 'markdown' (default 'json').
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        set output to ""
        repeat with t in (tracks of playlist "{playlist}")
            set output to output & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "\n"
        end repeat
        return output
    end tell
    """
    raw = run_applescript(script)
    if raw.startswith("Playlist not found") or raw.startswith("Error:"):
        return raw

    items = []
    for line in raw.strip().splitlines():
        parts = line.split("|||")
        if len(parts) == 3:
            items.append({"title": parts[0], "artist": parts[1], "album": parts[2]})

    fmt = format.lower().strip()
    if fmt == "csv":
        lines = ["Title,Artist,Album"]
        for i in items:
            t = i["title"].replace('"', '""')
            a = i["artist"].replace('"', '""')
            al = i["album"].replace('"', '""')
            lines.append(f'"{t}","{a}","{al}"')
        return "\n".join(lines)
    elif fmt == "markdown" or fmt == "md":
        lines = [f"# Playlist: {playlist}", "", "| # | Title | Artist | Album |", "|---|---|---|---|"]
        for idx, i in enumerate(items, 1):
            lines.append(f'| {idx} | {i["title"]} | {i["artist"]} | {i["album"]} |')
        return "\n".join(lines)
    elif fmt in ("m3u8", "m3u"):
        lines = ["#EXTM3U", f"#PLAYLIST:{playlist}"]
        for i in items:
            lines.append(f'#EXTINF:-1,{i["artist"]} - {i["title"]}')
            lines.append(f'{i["artist"]} - {i["title"]}.mp3')
        return "\n".join(lines)
    else:
        return json.dumps({"playlist": playlist, "count": len(items), "tracks": items}, indent=2)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_playlist_summary(playlist: str = "") -> str:
    """
    Get a comprehensive statistical summary of a playlist: total tracks, runtime, top artists, and most played tracks.

    Args:
        playlist: The name of the playlist to inspect. If empty, uses the currently active/selected playlist.
    """
    p_name_esc = playlist.replace('"', '\\"') if playlist else ""
    target_clause = f'playlist "{p_name_esc}"' if playlist else 'current playlist'

    script = f"""
    tell application "Music"
        try
            set p to {target_clause}
            set pName to name of p
            set pTracks to tracks of p
            set tCount to count of pTracks
            set pDur to duration of p as integer
            set pDesc to ""
            try
                set pDesc to description of p
            end try

            set trackData to {{}}
            repeat with t in pTracks
                set tName to name of t
                set tArtist to artist of t
                set tTime to time of t
                set pCount to (played count of t)
                set pDate to ""
                try
                    set pDate to (played date of t) as string
                end try
                set end of trackData to (tName & "|||" & tArtist & "|||" & tTime & "|||" & (pCount as string) & "|||" & pDate)
            end repeat

            set AppleScript's text item delimiters to "###"
            return (pName & ":::" & (tCount as string) & ":::" & (pDur as string) & ":::" & pDesc & ":::" & (trackData as string))
        on error
            return "Error: Playlist not found or no active playlist."
        end try
    end tell
    """
    raw = run_applescript(script)
    if raw.startswith("Error:") or not raw.strip():
        return f"Error: Could not retrieve summary for playlist '{playlist}'."

    parts = raw.strip().split(":::")
    if len(parts) < 5:
        return f"Error: Unexpected output from Apple Music for playlist '{playlist}'."

    name = parts[0]
    count = int(parts[1]) if parts[1].isdigit() else 0
    dur_sec = int(parts[2]) if parts[2].isdigit() else 0
    desc = parts[3]
    raw_tracks = parts[4].split("###") if parts[4] else []

    hours = dur_sec // 3600
    mins = (dur_sec % 3600) // 60
    dur_formatted = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"

    artist_counts = {}
    parsed_tracks = []
    for rt in raw_tracks:
        if "|||" in rt:
            t_name, t_art, t_time, t_pcount, t_pdate = rt.split("|||")
            p_c = int(t_pcount) if t_pcount.isdigit() else 0
            parsed_tracks.append((t_name, t_art, t_time, p_c, t_pdate))
            for individual_art in _split_artists(t_art, t_name):
                artist_counts[individual_art] = artist_counts.get(individual_art, 0) + 1

    sorted_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)
    top_artists_str = ", ".join([f"{art} ({c})" for art, c in sorted_artists[:5]]) if sorted_artists else "None"

    most_played = sorted(parsed_tracks, key=lambda x: x[3], reverse=True)
    top_songs = []
    for t_name, t_art, t_time, p_c, p_date in most_played[:5]:
        if p_c > 0:
            top_songs.append(f"• {t_name} — {t_art} ({t_time}) [{p_c} play(s)]")
        else:
            top_songs.append(f"• {t_name} — {t_art} ({t_time})")

    out = [
        f"📊 Playlist Summary: '{name}'",
        f"• Total Tracks: {count} song(s)",
        f"• Total Duration: {dur_formatted} ({dur_sec // 60} mins)",
    ]
    if desc and desc != "missing value":
        out.append(f"• Description: {desc}")
    out.append(f"• Top Artists: {top_artists_str}")
    out.append("• Top Songs / Most Played:")
    out.extend(top_songs)

    return "\n".join(out)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_stats() -> str:
    """Generate analytics summary of the Music library (total tracks, playlists, favorites, and hours)."""
    script = """
    tell application "Music"
        set totalT to count of tracks of playlist "Library"
        set totalP to count of user playlists
        set totalDur to 0
        set favCount to 0
        
        repeat with t in (tracks of playlist "Library")
            try
                set totalDur to totalDur + (duration of t)
            end try
            try
                if favorited of t is true then set favCount to favCount + 1
            end try
        end repeat
        
        set totalHours to (totalDur / 3600) as integer
        return "Library Statistics:\n" & "- Total Tracks: " & totalT & "\n- Total Playlists: " & totalP & "\n- Favorited Tracks: " & favCount & "\n- Total Playtime: ~" & totalHours & " hours"
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_move_playlist_track(playlist: str, from_index: int, to_index: int) -> str:
    """
    Move a track inside a playlist from one position (1-indexed) to another position.

    Args:
        playlist: The name of the playlist to edit.
        from_index: The current 1-indexed position of the track to move.
        to_index: The target 1-indexed position to move the track to.
    """
    if from_index < 1 or to_index < 1:
        return "Error: Position indices must be 1 or greater."
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        set totalT to count of tracks of playlist "{playlist}"
        if {from_index} > totalT or {to_index} > totalT then
            return "Error: Index out of range (playlist has " & totalT & " tracks)."
        end if
        try
            if {to_index} < {from_index} then
                move track {from_index} of playlist "{playlist}" to before track {to_index} of playlist "{playlist}"
            else
                move track {from_index} of playlist "{playlist}" to after track {to_index} of playlist "{playlist}"
            end if
            set tName to name of track {to_index} of playlist "{playlist}"
            return "Moved track from position " & {from_index} & " to " & {to_index} & " (" & tName & ")"
        on error e
            return "Error moving track: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def itunes_remove_from_playlist(song: str, playlist: str) -> str:
    """
    Remove a track from a playlist by song title.

    Args:
        song: The title of the song to remove.
        playlist: The name of the playlist to remove it from.
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        try
            set tList to (every track of playlist "{playlist}" whose name contains "{song}")
            if tList is not {{}} then
                set tName to name of item 1 of tList
                delete item 1 of tList
                return "Removed '" & tName & "' from playlist '{playlist}'"
            else
                return "Track '{song}' not found in playlist '{playlist}'"
            end if
        on error e
            return "Error removing track: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_sort_playlist(playlist: str, sort_by: str = "title") -> str:
    """
    Sort all tracks in a playlist alphabetically by 'title', 'artist', or 'album'.

    Args:
        playlist: The name of the playlist to sort.
        sort_by: Attribute to sort by: 'title', 'artist', or 'album' (default 'title').
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        set output to ""
        repeat with t in (tracks of playlist "{playlist}")
            set output to output & (database ID of t as string) & "|||" & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "\n"
        end repeat
        return output
    end tell
    """
    raw = run_applescript(script)
    if raw.startswith("Playlist not found") or raw.startswith("Error:"):
        return raw

    items = []
    for line in raw.strip().splitlines():
        parts = line.split("|||")
        if len(parts) == 4:
            items.append({"id": parts[0], "name": parts[1], "artist": parts[2], "album": parts[3]})

    key = sort_by.lower().strip()
    if key == "artist":
        items.sort(key=lambda x: (x["artist"].lower(), x["name"].lower()))
    elif key == "album":
        items.sort(key=lambda x: (x["album"].lower(), x["name"].lower()))
    else:
        items.sort(key=lambda x: x["name"].lower())

    ids_str = "{" + ", ".join([f'"{i["id"]}"' for i in items]) + "}"
    reorder_script = f"""
    tell application "Music"
        set p to playlist "{playlist}"
        set idList to {ids_str}
        set oldCount to count of tracks of p
        
        repeat with dbID in idList
            repeat with userP in (every user playlist)
                if name of userP is not "{playlist}" then
                    try
                        set matching to (first track of userP whose database ID is (dbID as integer))
                        duplicate matching to p
                        exit repeat
                    end try
                end if
            end repeat
        end repeat
        
        repeat with i from 1 to oldCount
            delete track 1 of p
        end repeat
        
        return "Sorted playlist '{playlist}' by {key} (" & (count of tracks of p) & " tracks)."
    end tell
    """
    return run_applescript(reorder_script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_favorite_song(song: str, favorited: bool = True) -> str:
    """
    Favorite or unfavorite any song in your library by title.

    Args:
        song: The title of the song to search for and favorite.
        favorited: True to favorite/love, False to unfavorite.
    """
    val = "true" if favorited else "false"
    script = f"""
    tell application "Music"
        set searchTerm to "{song}"
        repeat with p in (every user playlist)
            try
                set tList to (every track of p whose name contains searchTerm)
                if tList is not {{}} then
                    set targetT to item 1 of tList
                    set favorited of targetT to {val}
                    set status to if {val} then "Favorited" else "Unfavorited"
                    return status & " song: " & name of targetT & " - " & artist of targetT
                end if
            end try
        end repeat
        return "Song not found in library: " & searchTerm
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_dislike_track(disliked: bool = True) -> str:
    """
    Mark or un-mark the currently playing track as Disliked for recommendation algorithms.

    Args:
        disliked: True to dislike/ban the track, False to remove dislike.
    """
    val = "true" if disliked else "false"
    script = f"""
    tell application "Music"
        if player state is playing then
            set t to current track
            set disliked of t to {val}
            set status to if {val} then "Disliked" else "Removed dislike for"
            return status & ": " & name of t & " - " & artist of t
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_repeat(mode: str = "all") -> str:
    """
    Set playback repeat mode.

    Args:
        mode: 'off' (no repeat), 'one' (repeat current song), or 'all' (repeat playlist/album).
    """
    m = mode.lower().strip()
    if m not in ["off", "one", "all"]:
        return "Error: Repeat mode must be 'off', 'one', or 'all'."
    script = f"""
    tell application "Music"
        try
            set song repeat to {m}
            return "Set repeat mode to: {m}"
        on error e
            return "Error setting repeat mode: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_eq(preset: str = "Off") -> str:
    """
    Set Apple Music Equalizer (EQ) preset.

    Args:
        preset: Name of EQ preset (e.g. 'Hip-Hop', 'Bass Booster', 'Electronic', 'Acoustic', 'Flat', 'Off', 'Pop', 'Rock', 'R&B').
    """
    script = f"""
    tell application "Music"
        try
            set EQ enabled to true
            set current EQ preset to EQ preset "{preset}"
            return "Set EQ preset to: " & name of current EQ preset
        on error e
            return "Error setting EQ preset '{preset}': " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_favorite_playlist(playlist: str, favorited: bool = True) -> str:
    """
    Favorite/Star or unfavorite a playlist in the Music app sidebar.

    Args:
        playlist: The name of the playlist to star.
        favorited: True to star/favorite, False to unstar.
    """
    val = "true" if favorited else "false"
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        try
            set favorited of playlist "{playlist}" to {val}
            set status to if {val} then "Favorited (starred)" else "Unfavorited"
            return status & " playlist: {playlist}"
        on error e
            return "Error updating playlist favorite status: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def itunes_delete_playlist(playlist: str) -> str:
    """
    Delete a user playlist from the Music library.

    Args:
        playlist: The name of the playlist to delete.
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        try
            delete playlist "{playlist}"
            return "Deleted playlist: {playlist}"
        on error e
            return "Error deleting playlist: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_duplicate_playlist(source_playlist: str, new_playlist_name: str) -> str:
    """
    Duplicate/clone an existing playlist into a new playlist.

    Args:
        source_playlist: The name of the existing playlist to clone.
        new_playlist_name: The name for the newly cloned playlist.
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{source_playlist}") then
            return "Source playlist not found: {source_playlist}"
        end if
        if not (exists playlist "{new_playlist_name}") then
            make new playlist with properties {{name:"{new_playlist_name}"}}
        end if
        set targetP to playlist "{new_playlist_name}"
        delete tracks of targetP
        repeat with t in (tracks of playlist "{source_playlist}")
            duplicate t to targetP
        end repeat
        return "Duplicated '{source_playlist}' into '{new_playlist_name}' (" & (count of tracks of targetP) & " tracks)."
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_merge_playlists(playlist_a: str, playlist_b: str, new_playlist_name: str) -> str:
    """
    Merge tracks from two playlists into a new master playlist (skipping duplicate songs).

    Args:
        playlist_a: First source playlist.
        playlist_b: Second source playlist.
        new_playlist_name: Target master playlist name.
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist_a}") then return "Playlist not found: {playlist_a}"
        if not (exists playlist "{playlist_b}") then return "Playlist not found: {playlist_b}"
        if not (exists playlist "{new_playlist_name}") then
            make new playlist with properties {{name:"{new_playlist_name}"}}
        end if
        
        set targetP to playlist "{new_playlist_name}"
        delete tracks of targetP
        set addedIDs to {{}}
        
        repeat with pName in {{"{playlist_a}", "{playlist_b}"}}
            repeat with t in (tracks of playlist pName)
                set tID to database ID of t as string
                if addedIDs does not contain tID then
                    set end of addedIDs to tID
                    duplicate t to targetP
                end if
            end repeat
        end repeat
        return "Merged '{playlist_a}' and '{playlist_b}' into '{new_playlist_name}' (" & (count of tracks of targetP) & " tracks)."
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_find_duplicates(playlist: str, remove: bool = False) -> str:
    """
    Scan a playlist for duplicate songs (sharing the exact same title & artist).

    Args:
        playlist: The name of the playlist to check.
        remove: If True, automatically removes the duplicate tracks (keeping one copy).
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then
            return "Playlist not found: {playlist}"
        end if
        set p to playlist "{playlist}"
        set seenNames to {{}}
        set dupesFound to {{}}
        set output to ""
        
        repeat with t in (tracks of p)
            set key to (name of t) & " - " & (artist of t)
            if seenNames contains key then
                set end of dupesFound to key
            else
                set end of seenNames to key
            end if
        end repeat
        
        if dupesFound is {{}} then
            return "No duplicate tracks found in playlist '{playlist}'."
        end if
        
        set output to "Found " & (count of dupesFound) & " duplicate track(s) in '{playlist}':\n"
        repeat with dKey in dupesFound
            set output to output & "- " & dKey & "\n"
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_get_artist_top_tracks(artist: str, limit: int = 10) -> str:
    """
    Search Apple Music's global catalog for top tracks by any artist.

    Args:
        artist: Artist name to search.
        limit: Number of top tracks to return (default 10, max 25).
    """
    safe_limit = min(max(1, limit), 25)
    encoded_artist = urllib.parse.quote(artist)
    url = f"https://itunes.apple.com/search?term={encoded_artist}&media=music&entity=song&limit={safe_limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("results", [])
            if not results:
                return f"No tracks found for artist: '{artist}'"

            output = [f"Top tracks for '{artist}' in Apple Music catalog:"]
            for idx, item in enumerate(results, 1):
                track_name = item.get("trackName", "Unknown")
                artist_name = item.get("artistName", "Unknown")
                collection_name = item.get("collectionName", "Unknown Album")
                output.append(f"{idx}. {track_name} - {artist_name} ({collection_name})")

            return "\n".join(output)
    except Exception as e:
        return f"Error querying catalog top tracks: {str(e)}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_get_artist_albums(artist: str, limit: int = 10) -> str:
    """
    Search Apple Music's global catalog for official albums by any artist.

    Args:
        artist: Artist name to search.
        limit: Number of albums to return (default 10, max 25).
    """
    safe_limit = min(max(1, limit), 25)
    encoded_artist = urllib.parse.quote(artist)
    url = f"https://itunes.apple.com/search?term={encoded_artist}&media=music&entity=album&limit={safe_limit}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("results", [])
            if not results:
                return f"No albums found for artist: '{artist}'"

            output = [f"Official albums for '{artist}' in Apple Music catalog:"]
            for idx, item in enumerate(results, 1):
                collection_name = item.get("collectionName", "Unknown Album")
                artist_name = item.get("artistName", "Unknown")
                release_date = item.get("releaseDate", "")[:4]
                output.append(f"{idx}. {collection_name} - {artist_name} ({release_date})")

            return "\n".join(output)
    except Exception as e:
        return f"Error querying catalog albums: {str(e)}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_monthly_replay(year: int = 0, month: int = 0) -> str:
    """
    Generate an 'Apple Music Replay' listening report for a specific month and year.

    Args:
        year: Year (e.g. 2026). Defaults to current year if 0.
        month: Month (1-12). Defaults to current month if 0.

    Returns:
        Formatted summary with total listening time, play count, skip rate, top artists, top songs, and top albums.
    """
    _init_db()
    now = datetime.datetime.now()
    y = year if year > 0 else now.year
    m = month if month > 0 else now.month

    if not (1 <= m <= 12):
        return "Error: Month must be between 1 and 12."

    start_str = f"{y:04d}-{m:02d}-01 00:00:00"
    if m == 12:
        end_str = f"{y+1:04d}-01-01 00:00:00"
    else:
        end_str = f"{y:04d}-{m+1:02d}-01 00:00:00"

    month_name = datetime.date(y, m, 1).strftime("%B %Y")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Fetch raw play rows for the month
    c.execute("""
        SELECT track_name, artist_name, album_name, duration_sec, played_sec, skipped
        FROM plays
        WHERE timestamp >= ? AND timestamp < ?
    """, (start_str, end_str))
    all_month_rows = c.fetchall()
    conn.close()

    if not all_month_rows:
        return f"No listening journal data recorded yet for {month_name}."

    total_sec = sum(r[4] or 0 for r in all_month_rows)
    total_skips = sum(1 for r in all_month_rows if r[5] == 1)
    
    # Calculate actual plays per song, artist, and album
    song_plays = {}
    song_seconds = {}
    artist_plays = {}
    artist_seconds = {}
    album_plays = {}
    album_artists = {}
    actual_total_plays = 0

    for t_name, a_name, al_name, dur, p_sec, sk in all_month_rows:
        count = max(1, (p_sec or 0) // (dur or 1)) if dur and dur > 0 else 1
        actual_total_plays += count

        if sk == 0:
            s_key = (t_name, a_name)
            song_plays[s_key] = song_plays.get(s_key, 0) + count
            song_seconds[s_key] = song_seconds.get(s_key, 0) + (p_sec or 0)

            if al_name and al_name.strip():
                album_plays[al_name] = album_plays.get(al_name, 0) + count
                album_artists[al_name] = a_name

            for cand in _split_artists(a_name, t_name):
                artist_plays[cand] = artist_plays.get(cand, 0) + count
                artist_seconds[cand] = artist_seconds.get(cand, 0) + (p_sec or 0)

    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    skip_rate = round((total_skips / max(1, actual_total_plays)) * 100, 1)

    # 2. Top Artists (Ranked by listening time)
    top_artists = sorted(artist_seconds.items(), key=lambda x: (x[1], artist_plays.get(x[0], 0)), reverse=True)[:5]

    # 3. Top Songs (Ranked by play count)
    top_songs = sorted(song_plays.items(), key=lambda x: (x[1], song_seconds.get(x[0], 0)), reverse=True)[:10]

    # 4. Top Albums (Ranked by play count)
    top_albums = sorted(album_plays.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = [
        f" Apple Music Replay: {month_name}",
        "=" * 42,
        f"⏱ Total Listening Time: {hours}h {minutes}m",
        f" Total Plays: {actual_total_plays} (Completed: {actual_total_plays - total_skips}, Skipped: {total_skips} | {skip_rate}% skip rate)",
        "",
        " Top Artists:",
    ]
    for idx, (artist, a_sec) in enumerate(top_artists, 1):
        a_m = a_sec // 60
        plays = artist_plays.get(artist, 0)
        lines.append(f"{idx}. {artist} — {plays} play(s) ({a_m} mins)")

    lines.extend(["", " Top Songs:"])
    for idx, ((song, artist), count) in enumerate(top_songs, 1):
        s_m = song_seconds.get((song, artist), 0) // 60
        lines.append(f"{idx}. {song} — {artist} ({count} play(s) | {s_m} mins)")

    if top_albums:
        lines.extend(["", " Top Albums:"])
        for idx, (album, count) in enumerate(top_albums, 1):
            a_art = album_artists.get(album, "")
            lines.append(f"{idx}. {album} — {a_art} ({count} play(s))")

    return "\n".join(lines)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_listening_history(limit: int = 20, artist: str = "") -> str:
    """
    Get a chronological journal log of recent music plays and skips with timestamps.

    Args:
        limit: Number of recent tracks to return (default 20, max 100).
        artist: Optional filter to see history for a specific artist.
    """
    _init_db()
    safe_limit = min(max(1, limit), 100)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if artist.strip():
        c.execute("""
            SELECT track_name, artist_name, album_name, played_sec, skipped, timestamp
            FROM plays
            WHERE artist_name LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (f"%{artist.strip()}%", safe_limit))
    else:
        c.execute("""
            SELECT track_name, artist_name, album_name, played_sec, skipped, timestamp
            FROM plays
            ORDER BY id DESC
            LIMIT ?
        """, (safe_limit,))

    rows = c.fetchall()
    conn.close()

    if not rows:
        return "No listening history entries recorded yet."

    lines = [f" Listening Journal History (Last {len(rows)} entries):", "=" * 55]
    for track, art, album, played_sec, skipped, ts in rows:
        mins = (played_sec or 0) // 60
        secs = (played_sec or 0) % 60
        status = " Skipped" if skipped == 1 else " Completed"
        lines.append(f"• {ts} | {track} — {art} ({mins}m{secs:02d}s) [{status}]")

    return "\n".join(lines)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_listening_stats_by_date(start_date: str = "", end_date: str = "") -> str:
    """
    Get aggregated listening statistics and top artists/songs for a custom date range.

    Args:
        start_date: Start date in 'YYYY-MM-DD' format (e.g. '2026-08-01'). Defaults to 7 days ago if empty.
        end_date: End date in 'YYYY-MM-DD' format (e.g. '2026-08-19'). Defaults to today if empty.
    """
    _init_db()
    now = datetime.datetime.now()
    if not end_date.strip():
        end_date_str = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        end_label = now.strftime("%Y-%m-%d")
    else:
        end_date_str = f"{end_date.strip()} 23:59:59"
        end_label = end_date.strip()

    if not start_date.strip():
        start_date_str = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        start_label = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        start_date_str = f"{start_date.strip()} 00:00:00"
        start_label = start_date.strip()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT COUNT(*), SUM(played_sec), SUM(CASE WHEN skipped = 1 THEN 1 ELSE 0 END)
        FROM plays
        WHERE timestamp >= ? AND timestamp <= ?
    """, (start_date_str, end_date_str))
    total_plays, total_sec, total_skips = c.fetchone()

    if not total_plays or total_plays == 0:
        conn.close()
        return f"No listening data recorded between {start_label} and {end_label}."

    total_sec = total_sec or 0
    total_skips = total_skips or 0
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    skip_rate = round((total_skips / total_plays) * 100, 1)

    # Top Artists (Apple Replay attribution)
    c.execute("""
        SELECT track_name, artist_name, played_sec
        FROM plays
        WHERE timestamp >= ? AND timestamp <= ? AND skipped = 0
    """, (start_date_str, end_date_str))
    artist_rows = c.fetchall()

    artist_plays = {}
    artist_seconds = {}
    for t_name, a_name, p_sec in artist_rows:
        credited = _split_artists(a_name, t_name)
        for cand in credited:
            artist_plays[cand] = artist_plays.get(cand, 0) + 1
            artist_seconds[cand] = artist_seconds.get(cand, 0) + (p_sec or 0)

    ranked_artists = sorted(artist_seconds.items(), key=lambda x: (x[1], artist_plays.get(x[0], 0)), reverse=True)[:5]
    top_artists = [(art, artist_plays.get(art, 0), sec) for art, sec in ranked_artists]

    c.execute("""
        SELECT track_name, artist_name, COUNT(*)
        FROM plays
        WHERE timestamp >= ? AND timestamp <= ? AND skipped = 0
        GROUP BY track_name, artist_name
        ORDER BY COUNT(*) DESC
        LIMIT 5
    """, (start_date_str, end_date_str))
    top_songs = c.fetchall()

    conn.close()

    lines = [
        f" Listening Stats ({start_label} to {end_label})",
        "=" * 45,
        f"⏱ Total Listening Time: {hours}h {minutes}m",
        f" Total Plays: {total_plays} (Completed: {total_plays - total_skips}, Skipped: {total_skips} | {skip_rate}% skip rate)",
        "",
        " Top Artists:",
    ]
    for idx, (artist, count, sec) in enumerate(top_artists, 1):
        art_h = sec // 3600
        art_m = (sec % 3600) // 60
        time_str = f"{art_h}h {art_m}m" if art_h > 0 else f"{art_m}m"
        lines.append(f"{idx}. {artist} — {count} play(s) ({time_str})")

    lines.extend(["", " Top Songs:"])
    for idx, (song, artist, count) in enumerate(top_songs, 1):
        lines.append(f"{idx}. {song} — {artist} ({count} play(s))")

    return "\n".join(lines)

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_sync_library_history() -> str:
    """
    Sync all lifetime play counts and recent plays from your iCloud & iPhone Apple Music library into your local SQLite history.
    """
    if sys.platform != "darwin":
        return "Error: Library sync is only supported on macOS."

    _init_db()
    script = """
    tell application "Music"
        set trackList to {}
        repeat with t in (every track of playlist "Library")
            set pCount to (played count of t)
            if pCount > 0 then
                set pDate to ""
                try
                    set pDate to (played date of t) as string
                end try
                set tName to name of t
                set tArtist to artist of t
                set tAlbum to album of t
                set tDur to duration of t as integer
                set end of trackList to (tName & "|||" & tArtist & "|||" & tAlbum & "|||" & (pCount as string) & "|||" & (tDur as string) & "|||" & pDate)
            end if
        end repeat
        set AppleScript's text item delimiters to "###"
        return trackList as string
    end tell
    """
    res = run_applescript(script)
    if res.startswith("Error:") or not res.strip():
        return "Unable to read library tracks for sync."

    items = [x for x in res.split("###") if x.strip()]
    months = {
        "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
        "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12
    }

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    synced_count = 0
    total_sec_added = 0

    for item in items:
        parts = item.split("|||")
        if len(parts) >= 5:
            name, artist, album, count_str, dur_str = parts[:5]
            try:
                p_count = int(count_str)
                dur = int(dur_str)
            except ValueError:
                continue

            date_str = parts[5] if len(parts) > 5 else ""
            ts = None
            if date_str:
                try:
                    clean_d = date_str.split(", ")[1] if ", " in date_str else date_str
                    clean_d = clean_d.replace(" at ", " ")
                    d_parts = clean_d.split()
                    day = int(d_parts[0])
                    month = months.get(d_parts[1], datetime.datetime.now().month)
                    year = int(d_parts[2])
                    time_p = d_parts[3].split(":")
                    hour = int(time_p[0])
                    minute = int(time_p[1])
                    second = int(time_p[2])
                    ts = datetime.datetime(year, month, day, hour, minute, second).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            c.execute("SELECT SUM(played_sec) FROM plays WHERE track_name = ? AND artist_name = ?", (name, artist))
            existing = c.fetchone()[0] or 0
            total_needed_sec = p_count * dur

            if total_needed_sec > existing:
                diff_sec = total_needed_sec - existing
                c.execute("""
                    INSERT INTO plays (track_name, artist_name, album_name, duration_sec, played_sec, skipped, timestamp)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                """, (name, artist, album, dur, diff_sec, ts))
                synced_count += 1
                total_sec_added += diff_sec

    conn.commit()
    conn.close()
    return f"Synced {synced_count} tracks ({total_sec_added // 60} minutes) from your iCloud/iPhone Apple Music library into your history journal."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_log_current_play() -> str:
    """
    Manually log the currently playing track into the listening journal immediately.
    """
    script = """
    tell application "Music"
        if player state is playing then
            set t to current track
            set pos to player position as integer
            set dur to duration of t as integer
            return (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "|||" & (pos as string) & "|||" & (dur as string)
        else
            return "NOT_PLAYING"
        end if
    end tell
    """
    raw = run_applescript(script)
    if raw == "NOT_PLAYING" or raw.startswith("Error:"):
        return "Music is not currently playing."

    parts = raw.split("|||")
    if len(parts) >= 5:
        t_name = parts[0]
        a_name = parts[1]
        al_name = parts[2]
        try:
            pos = int(parts[3])
            dur = int(parts[4])
        except ValueError:
            pos = 0
            dur = 0
        _log_play(t_name, a_name, al_name, dur, pos, 0)
        return f"Logged play to journal: '{t_name}' — {a_name} ({pos}s played)"
    return "No active track to log."

# --- Audio Technicals & Quality Tools ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_track_audio_info(song: str = "") -> str:
    """
    Get technical audio quality information (bitrate, sample rate, BPM, cloud status, format, volume adjustment).

    Args:
        song: Optional track title. If empty, inspects currently playing track.
    """
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    script = f"""
    tell application "Music"
        try
            set t to {target}
            set bRate to bit rate of t as string
            set sRate to sample rate of t as string
            set bpmVal to bpm of t as string
            set cStatus to cloud status of t as string
            set vAdj to volume adjustment of t as string
            set gLess to gapless of t as string
            set tDur to duration of t as string
            set tKind to kind of t as string
            return "Audio Info for: " & name of t & " - " & artist of t & "\\n" & ¬
                   "• Bit Rate: " & bRate & " kbps\\n" & ¬
                   "• Sample Rate: " & sRate & " Hz\\n" & ¬
                   "• BPM (Tempo): " & bpmVal & "\\n" & ¬
                   "• Cloud Status: " & cStatus & "\\n" & ¬
                   "• Audio Kind: " & tKind & "\\n" & ¬
                   "• Volume Adjustment: " & vAdj & "%\\n" & ¬
                   "• Gapless: " & gLess & "\\n" & ¬
                   "• Duration: " & tDur & "s"
        on error e
            return "Error retrieving audio info: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_track_bpm(bpm: int, song: str = "") -> str:
    """
    Set Beats Per Minute (BPM) tempo on a track.

    Args:
        bpm: Beats per minute (e.g. 120, 140).
        song: Optional track title. If empty, modifies currently playing track.
    """
    if bpm < 0 or bpm > 500:
        return "Error: BPM must be between 0 and 500."
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    script = f"""
    tell application "Music"
        try
            set t to {target}
            set bpm of t to {bpm}
            return "Set BPM to " & {bpm} & " on: " & name of t & " - " & artist of t
        on error e
            return "Error setting BPM: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_track_start_finish(start: int = 0, finish: int = 0, song: str = "") -> str:
    """
    Set custom playback start and/or finish time offsets (in seconds) for a track.

    Args:
        start: Start offset in seconds (0 for beginning).
        finish: Finish offset in seconds (0 for normal track end).
        song: Optional track title. If empty, modifies currently playing track.
    """
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    set_stmts = []
    if start >= 0:
        set_stmts.append(f"set start of t to {start}")
    if finish > 0:
        set_stmts.append(f"set finish of t to {finish}")
    stmts = "\n            ".join(set_stmts)
    script = f"""
    tell application "Music"
        try
            set t to {target}
            {stmts}
            return "Updated start/finish offsets on: " & name of t & " (start: {start}s, finish: {finish}s)"
        on error e
            return "Error setting start/finish: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_track_volume_adjustment(adjustment: int, song: str = "") -> str:
    """
    Set relative volume adjustment (-100% to +100%) for track gain normalization.

    Args:
        adjustment: Volume adjustment from -100 to 100 percent.
        song: Optional track title. If empty, modifies currently playing track.
    """
    if not -100 <= adjustment <= 100:
        return "Error: Volume adjustment must be between -100 and 100."
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    script = f"""
    tell application "Music"
        try
            set t to {target}
            set volume adjustment of t to {adjustment}
            return "Set volume adjustment to " & {adjustment} & "% on: " & name of t & " - " & artist of t
        on error e
            return "Error setting volume adjustment: " & e
        end try
    end tell
    """
    return run_applescript(script)


# --- Deep Tagging & Metadata Editor Tools ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_track_metadata(song: str = "") -> str:
    """
    Inspect comprehensive metadata for a track (genre, composer, comment, track/disc numbers, compilation, date added, unplayed).

    Args:
        song: Optional track title. If empty, inspects currently playing track.
    """
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    script = f"""
    tell application "Music"
        try
            set t to {target}
            set gName to genre of t as string
            set cName to composer of t as string
            set cText to comment of t as string
            set tNum to track number of t as string
            set tCount to track count of t as string
            set dNum to disc number of t as string
            set dCount to disc count of t as string
            set compVal to compilation of t as string
            set dAdded to date added of t as string
            set unp to unplayed of t as string
            set pCount to played count of t as string
            set sCount to skipped count of t as string
            return "Detailed Metadata for: " & name of t & " - " & artist of t & "\\n" & ¬
                   "• Album: " & album of t & "\\n" & ¬
                   "• Genre: " & gName & "\\n" & ¬
                   "• Composer: " & cName & "\\n" & ¬
                   "• Track Number: " & tNum & " of " & tCount & "\\n" & ¬
                   "• Disc Number: " & dNum & " of " & dCount & "\\n" & ¬
                   "• Compilation: " & compVal & "\\n" & ¬
                   "• Date Added: " & dAdded & "\\n" & ¬
                   "• Unplayed: " & unp & "\\n" & ¬
                   "• Lifetime Plays: " & pCount & " | Lifetime Skips: " & sCount & "\\n" & ¬
                   "• Comment: " & cText
        on error e
            return "Error retrieving metadata: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_edit_track_metadata(song: str = "", genre: str = "", composer: str = "", comment: str = "", year: int = 0, track_number: int = 0) -> str:
    """
    Edit and update metadata tags on a track in your library.

    Args:
        song: Optional track title to edit. If empty, edits currently playing track.
        genre: New genre tag (optional).
        composer: New composer/producer credit (optional).
        comment: Custom comment or note (optional).
        year: Release year (optional).
        track_number: Track index number (optional).
    """
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    updates = []
    if genre.strip():
        updates.append(f'set genre of t to "{genre.strip()}"')
    if composer.strip():
        updates.append(f'set composer of t to "{composer.strip()}"')
    if comment.strip():
        updates.append(f'set comment of t to "{comment.strip()}"')
    if year > 0:
        updates.append(f'set year of t to {year}')
    if track_number > 0:
        updates.append(f'set track number of t to {track_number}')

    if not updates:
        return "No metadata updates specified."

    stmts = "\n            ".join(updates)
    script = f"""
    tell application "Music"
        try
            set t to {target}
            {stmts}
            return "Successfully updated metadata for: " & name of t & " - " & artist of t
        on error e
            return "Error editing metadata: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_favorite_album(favorited: bool = True) -> str:
    """
    Favorite/star or unfavorite the album of the currently playing track.

    Args:
        favorited: True to star/favorite the album, False to unstar.
    """
    val = "true" if favorited else "false"
    script = f"""
    tell application "Music"
        if player state is playing then
            set t to current track
            try
                set album favorited of t to {val}
                set status to if {val} then "Favorited (starred)" else "Unfavorited"
                return status & " album: " & album of t & " — " & artist of t
            on error e
                return "Error favoriting album: " & e
            end try
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_rate_album(stars: int) -> str:
    """
    Set a star rating (1–5 stars) for the album of the currently playing track.

    Args:
        stars: Rating from 1 to 5 stars, or 0 to clear album rating.
    """
    if not 0 <= stars <= 5:
        return "Error: Rating stars must be between 0 and 5."
    rating_val = stars * 20
    script = f"""
    tell application "Music"
        if player state is playing then
            set t to current track
            try
                set album rating of t to {rating_val}
                return "Set album rating to " & {stars} & " star(s) for: " & album of t & " — " & artist of t
            on error e
                return "Error setting album rating: " & e
            end try
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


# --- Artwork Management Tool ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_artwork_info(song: str = "") -> str:
    """
    Get information about attached album artwork for a track.

    Args:
        song: Optional track title. If empty, inspects currently playing track.
    """
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    script = f"""
    tell application "Music"
        try
            set t to {target}
            set artCount to count of artworks of t
            if artCount > 0 then
                set art to artwork 1 of t
                set artFmt to format of art as string
                set artDesc to description of art as string
                set artDown to downloaded of art as string
                return "Artwork Info for: " & name of t & " - " & artist of t & "\\n" & ¬
                       "• Total Artworks: " & (artCount as string) & "\\n" & ¬
                       "• Format: " & artFmt & "\\n" & ¬
                       "• Downloaded: " & artDown & "\\n" & ¬
                       "• Description: " & artDesc
            else
                return "No artwork attached to: " & name of t
            end if
        on error e
            return "Error retrieving artwork info: " & e
        end try
    end tell
    """
    return run_applescript(script)


# --- Advanced Playback & Stream Controls ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_mute(muted: bool = True) -> str:
    """
    Mute or unmute Apple Music audio playback.

    Args:
        muted: True to mute, False to unmute.
    """
    val = "true" if muted else "false"
    script = f"""
    tell application "Music"
        set mute to {val}
        set status to if {val} then "Muted" else "Unmuted"
        return "Audio " & status
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_shuffle_mode(mode: str = "songs") -> str:
    """
    Set shuffle granularity mode.

    Args:
        mode: 'songs' (shuffle individual tracks), 'albums' (shuffle albums), or 'groupings' (shuffle groupings).
    """
    m = mode.lower().strip()
    if m not in ["songs", "albums", "groupings"]:
        return "Error: Shuffle mode must be 'songs', 'albums', or 'groupings'."
    script = f"""
    tell application "Music"
        try
            set shuffle mode to {m}
            return "Set shuffle mode to: {m}"
        on error e
            return "Error setting shuffle mode: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_device_volume(device_name: str, volume: int) -> str:
    """
    Set individual volume (0-100) for a specific AirPlay output device (e.g. HomePod, AirPods, Mac speakers).

    Args:
        device_name: The exact name of the AirPlay device.
        volume: Volume level from 0 to 100.
    """
    if not 0 <= volume <= 100:
        return "Error: Volume must be between 0 and 100."
    script = f"""
    tell application "Music"
        try
            set d to (first AirPlay device whose name is "{device_name}")
            set sound volume of d to {volume}
            return "Set volume of '" & "{device_name}" & "' to " & {volume} & "%"
        on error e
            return "AirPlay device not found or error setting volume: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_open_location(url: str) -> str:
    """
    Open and stream an audio stream URL or Apple Music link directly.

    Args:
        url: Stream URL (e.g. 'http://...', 'https://...', or 'music://...').
    """
    script = f"""
    tell application "Music"
        try
            open location "{url.strip()}"
            return "Opened stream location: {url.strip()}"
        on error e
            return "Error opening location: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_stream_info() -> str:
    """
    Get live stream station title and URL when listening to live/internet radio or Apple Music 1.
    """
    script = """
    tell application "Music"
        if player state is playing then
            set sTitle to current stream title as string
            set sURL to current stream URL as string
            if sTitle is not "missing value" and sTitle is not "" then
                return "Live Stream: " & sTitle & "\nStream URL: " & sURL
            else
                return "Not currently listening to an internet stream/radio station."
            end if
        else
            return "Music is not currently playing."
        end if
    end tell
    """
    return run_applescript(script)


# --- Playlist Folders & Descriptions ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def itunes_create_playlist_folder(name: str) -> str:
    """
    Create a new playlist folder to organize multiple playlists.

    Args:
        name: The name of the folder to create.
    """
    script = f"""
    tell application "Music"
        if not (exists folder playlist "{name}") then
            make new folder playlist with properties {{name:"{name}"}}
            return "Created playlist folder: {name}"
        else
            return "Playlist folder already exists: {name}"
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_move_playlist_to_folder(playlist: str, folder: str) -> str:
    """
    Move an existing playlist into a playlist folder.

    Args:
        playlist: The name of the playlist to move.
        folder: The name of the destination folder playlist.
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then return "Playlist not found: {playlist}"
        if not (exists folder playlist "{folder}") then return "Folder not found: {folder}"
        try
            set p to playlist "{playlist}"
            set parent of p to folder playlist "{folder}"
            return "Moved playlist '{playlist}' into folder '{folder}'"
        on error e
            return "Error moving playlist to folder: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_playlist_description(playlist: str, description: str) -> str:
    """
    Set or update the description text on a playlist.

    Args:
        playlist: The name of the playlist.
        description: Description text for the playlist.
    """
    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then return "Playlist not found: {playlist}"
        try
            set description of playlist "{playlist}" to "{description.replace('"', '\\"')}"
            return "Updated description for playlist '{playlist}'"
        on error e
            return "Error setting playlist description: " & e
        end try
    end tell
    """
    return run_applescript(script)


# --- UI & Window Management Tools ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_selected_tracks() -> str:
    """
    Get a list of tracks currently selected/highlighted by the user in the Music app window.
    """
    script = """
    tell application "Music"
        try
            set sel to selection
            if sel is not {} then
                set output to "Selected Tracks (" & (count of sel) & "):\n"
                repeat with t in sel
                    set output to output & "• " & name of t & " — " & artist of t & " (" & album of t & ")\n"
                end repeat
                return output
            else
                return "No tracks currently selected in the Music app window."
            end if
        on error e
            return "Error getting selection: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_set_miniplayer(enabled: bool = True) -> str:
    """
    Toggle the compact MiniPlayer window mode in the Music app.

    Args:
        enabled: True to switch to MiniPlayer, False for standard full window.
    """
    val = "true" if enabled else "false"
    script = f"""
    tell application "Music"
        try
            set visible of miniplayer window 1 to {val}
            set status to if {val} then "MiniPlayer activated" else "MiniPlayer closed"
            return status
        on error e
            return "Error toggling MiniPlayer: " & e
        end try
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_reveal_track(song: str = "") -> str:
    """
    Reveal and highlight a track in the main Music app window.

    Args:
        song: Optional track title to reveal. If empty, reveals currently playing track.
    """
    target = f'(first track of playlist "Library" whose name contains "{song}")' if song.strip() else 'current track'
    script = f"""
    tell application "Music"
        try
            set t to {target}
            reveal t
            activate
            return "Revealed '" & name of t & " — " & artist of t & "' in Music app"
        on error e
            return "Error revealing track: " & e
        end try
    end tell
    """
    return run_applescript(script)


# --- Next-Gen Curation & Ecosystem Tools ---

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_import_from_spotify(playlist_url: str, playlist_name: str = "") -> str:
    """
    Import and reconstruct a public Spotify playlist or album into Apple Music without any Spotify login.

    Args:
        playlist_url: Public Spotify playlist or album URL (e.g. 'https://open.spotify.com/playlist/...').
        playlist_name: Optional custom name for the created Apple Music playlist. Defaults to Spotify playlist title.
    """
    import re
    clean_url = playlist_url.split("?")[0].strip()
    match = re.search(r'spotify\.com/(playlist|album)/([a-zA-Z0-9]+)', clean_url)
    if not match:
        return "Error: Invalid Spotify URL. Expected format: 'https://open.spotify.com/playlist/{id}' or 'https://open.spotify.com/album/{id}'"

    embed_url = f"https://open.spotify.com/embed/{match.group(1)}/{match.group(2)}"
    try:
        req = urllib.request.Request(embed_url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        json_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>', html)
        if not json_match:
            return "Error: Unable to extract playlist tracks from Spotify embed."

        data = json.loads(json_match.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        default_title = entity.get("title") or "Imported Spotify Playlist"
        target_name = playlist_name.strip() if playlist_name.strip() else default_title
        track_list = entity.get("trackList", [])

        if not track_list:
            return f"No tracks found in Spotify playlist: {target_name}"

        create_script = f"""
        tell application "Music"
            if not (exists playlist "{target_name}") then
                make new playlist with properties {{name:"{target_name}"}}
            end if
        end tell
        """
        run_applescript(create_script)

        added_count = 0
        failed_tracks = []
        for t in track_list:
            t_name = t.get("title", "")
            a_name = t.get("subtitle", "")
            if not t_name:
                continue

            add_script = f"""
            tell application "Music"
                set p to playlist "{target_name}"
                set sName to "{t_name.replace('"', '\\"')}"
                repeat with userP in (every user playlist)
                    if name of userP is not "{target_name}" then
                        try
                            set tList to (every track of userP whose name contains sName)
                            if tList is not {{}} then
                                duplicate item 1 of tList to p
                                return "ADDED"
                            end if
                        end try
                    end if
                end repeat
                return "NOT_FOUND"
            end tell
            """
            res = run_applescript(add_script)
            if res == "ADDED":
                added_count += 1
            else:
                failed_tracks.append(f"{t_name} — {a_name}")

        summary = f"Imported Spotify Playlist: '{target_name}'\n• Added {added_count} of {len(track_list)} tracks to Apple Music."
        if failed_tracks:
            summary += f"\n• {len(failed_tracks)} track(s) not currently in your local library (use 'itunes_search_catalog' to discover them):\n" + "\n".join([f"  - {f}" for f in failed_tracks[:5]])
        return summary

    except Exception as e:
        return f"Error importing Spotify playlist: {str(e)}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
def itunes_generate_share_link(song: str = "") -> str:
    """
    Generate a universal share link (song.link) for friends on Spotify, YouTube, Tidal, etc.

    Args:
        song: Optional track title or 'Title Artist'. If empty, uses currently playing track.
    """
    query = song.strip()
    if not query:
        script = """
        tell application "Music"
            if player state is playing then
                set t to current track
                return (name of t) & " " & (artist of t)
            else
                return "NOT_PLAYING"
            end if
        end tell
        """
        raw = run_applescript(script)
        if raw != "NOT_PLAYING" and not raw.startswith("Error:"):
            query = raw.strip()

    if not query:
        return "Music is not playing. Specify a song title (e.g. itunes_generate_share_link('Location Dave'))."

    try:
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if results:
                track_url = results[0].get("trackViewUrl", "")
                t_name = results[0].get("trackName", "")
                a_name = results[0].get("artistName", "")
                return f"Universal Share Link for '{t_name}' — {a_name}:\nhttps://song.link/{track_url}"
    except Exception:
        pass

    return f"Unable to generate universal share link for: '{query}'"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_get_top_charts(country: str = "gb", limit: int = 25) -> str:
    """
    Fetch Apple Music's official Daily Top Charts by country (e.g. 'gb', 'us', 'global', 'ng', 'ca').

    Args:
        country: Two-letter country code (e.g. 'gb' for UK, 'us' for USA, 'ca' for Canada).
        limit: Number of top songs to return (default 25, max 100).
    """
    safe_limit = min(max(1, limit), 100)
    c_code = country.lower().strip()

    # 1. Try Apple Marketing RSS feed
    try:
        url = f"https://rss.applemarketingtools.com/api/v2/{c_code}/music/most-played/{safe_limit}/songs.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            feed = data.get("feed", {})
            title = feed.get("title", f"Apple Music Top {safe_limit} ({country.upper()})")
            results = feed.get("results", [])
            if results:
                lines = [f" {title}:", "=" * 45]
                for idx, r in enumerate(results, 1):
                    name = r.get("name", "Unknown")
                    artist = r.get("artistName", "Unknown")
                    lines.append(f"{idx}. {name} — {artist}")
                return "\n".join(lines)
    except Exception:
        pass

    # 2. Resilient fallback to iTunes search API
    try:
        url = f"https://itunes.apple.com/search?term=top+hits&country={c_code}&entity=song&limit={safe_limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if results:
                lines = [f" Apple Music Top Hits ({country.upper()}):", "=" * 45]
                for idx, r in enumerate(results, 1):
                    lines.append(f"{idx}. {r.get('trackName')} — {r.get('artistName')}")
                return "\n".join(lines)
    except Exception as e:
        return f"Error fetching charts: {e}"

    return f"No chart results found for: '{country}'"



@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_get_new_releases(country: str = "gb", limit: int = 25) -> str:
    """
    Fetch Apple Music's latest official album and single releases by country.

    Args:
        country: Two-letter country code (e.g. 'gb', 'us', 'ng', 'ca').
        limit: Number of new releases to return (default 25, max 100).
    """
    safe_limit = min(max(1, limit), 100)
    c_code = country.lower().strip()
    url = f"https://rss.applemarketingtools.com/api/v2/{c_code}/music/most-played/{safe_limit}/albums.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            feed = data.get("feed", {})
            title = feed.get("title", f"Apple Music Top Albums ({country.upper()})")
            results = feed.get("results", [])
            if not results:
                return f"No release results returned for country code: '{country}'"

            lines = [f" {title}:", "=" * 45]
            for idx, r in enumerate(results, 1):
                name = r.get("name", "Unknown Album")
                artist = r.get("artistName", "Unknown Artist")
                lines.append(f"{idx}. {name} — {artist}")

            return "\n".join(lines)
    except Exception as e:
        return f"Error fetching Apple releases: {str(e)}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
def itunes_dj_auto_transition(playlist: str, crossfade_seconds: int = 5, trim_intro: int = 0) -> str:
    """
    Apply intelligent DJ start/finish trim offsets across a playlist for radio-style seamless crossfades.

    Args:
        playlist: The name of the playlist to configure.
        crossfade_seconds: Seconds to trim off the end of each track (default 5 seconds).
        trim_intro: Seconds to trim off the start of each track (default 0).
    """
    if crossfade_seconds < 0 or trim_intro < 0:
        return "Error: Offsets must be 0 or positive integers."

    script = f"""
    tell application "Music"
        if not (exists playlist "{playlist}") then return "Playlist not found: {playlist}"
        set p to playlist "{playlist}"
        set modifiedCount to 0
        repeat with t in (tracks of p)
            set d to duration of t as integer
            if d > ({crossfade_seconds} + {trim_intro} + 10) then
                if {trim_intro} > 0 then set start of t to {trim_intro}
                set finish of t to (d - {crossfade_seconds})
                set modifiedCount to modifiedCount + 1
            end if
        end repeat
        return "Configured DJ Transitions for " & modifiedCount & " track(s) in '{playlist}' (Trim Intro: {trim_intro}s, Crossfade: -{crossfade_seconds}s)."
    end tell
    """
    return run_applescript(script)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def itunes_get_listening_personality() -> str:
    """
    Generate an AI analytical breakdown of your listening habits, signature artists, peak listening hours, and skip patterns.
    """
    _init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(played_sec), SUM(CASE WHEN skipped = 1 THEN 1 ELSE 0 END) FROM plays")
    total_plays, total_sec, skips = c.fetchone()
    if not total_plays or total_plays == 0:
        conn.close()
        return "Not enough listening journal data recorded yet to analyze personality."

    total_sec = total_sec or 0
    skips = skips or 0
    skip_rate = (skips / total_plays) * 100

    c.execute("SELECT track_name, artist_name, played_sec FROM plays WHERE skipped = 0")
    all_rows = c.fetchall()
    art_plays = {}
    art_secs = {}
    for t_n, a_n, p_s in all_rows:
        for single_art in _split_artists(a_n, t_n):
            art_plays[single_art] = art_plays.get(single_art, 0) + 1
            art_secs[single_art] = art_secs.get(single_art, 0) + (p_s or 0)
    top_artists = sorted(art_secs.items(), key=lambda x: (x[1], art_plays.get(x[0], 0)), reverse=True)[:3]
    top_artists = [(a, art_plays.get(a, 0)) for a, s in top_artists]

    c.execute("""
        SELECT 
            CASE 
                WHEN CAST(strftime('%H', timestamp) AS INT) BETWEEN 5 AND 11 THEN 'Morning  (5am-12pm)'
                WHEN CAST(strftime('%H', timestamp) AS INT) BETWEEN 12 AND 16 THEN 'Afternoon  (12pm-5pm)'
                WHEN CAST(strftime('%H', timestamp) AS INT) BETWEEN 17 AND 21 THEN 'Evening  (5pm-10pm)'
                ELSE 'Night  (10pm-5am)'
            END as time_period,
            COUNT(*) as count
        FROM plays
        GROUP BY time_period
        ORDER BY count DESC
        LIMIT 1
    """)
    peak_time_row = c.fetchone()
    peak_time = peak_time_row[0] if peak_time_row else "Varied"

    conn.close()

    if skip_rate < 15:
        archetype = "The Immersive Listener (Deeply committed, low skip rate)"
    elif skip_rate > 35:
        archetype = "The High-Velocity DJ (Fast skipper, curating the exact vibe)"
    else:
        archetype = "The Balanced Explorer (Steady listener with eclectic taste)"

    top_a_str = ", ".join([f"{a[0]} ({a[1]} play(s))" for a in top_artists])

    return f""" Your Music Listening Personality Profile
================================================
 Archetype: {archetype}
⏰ Peak Listening Vibe: {peak_time}
⏭ Skip Tolerance: {skip_rate:.1f}% skip rate ({skips} skips across {total_plays} logged plays)
 Signature Core Artists: {top_a_str}
⏱ Total Journaled Playtime: {total_sec // 60} minutes"""


def main():
    mcp.run()


if __name__ == "__main__":
    main()







