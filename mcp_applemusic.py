import contextlib
import csv
import os
import subprocess
from mcp.server.fastmcp import FastMCP

# ASCII unit separator; embedded literally into the AppleScript source passed to osascript
# as a field delimiter. Tracks whose metadata contains this character produce lines with
# the wrong field count and are counted as skipped in the export confirmation.
_SEP = "\x1f"


def run_applescript(script: str) -> str:
    """Execute an AppleScript command via osascript and return its output.

    Leading and trailing whitespace (including newlines) is stripped from stdout.
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"
    return result.stdout.strip()


def _unlink_if_exists(path: str) -> None:
    """Delete path, suppressing any OSError so cleanup is best-effort if the file was already replaced or deleted."""
    with contextlib.suppress(OSError):
        os.unlink(path)


def _check_applescript_str(value: str, label: str) -> str | None:
    """Return an error string if value is unsafe to interpolate into an AppleScript string literal.

    Rejects double-quote (terminates the string), backslash (undefined but
    dangerous), and newline/carriage-return (breaks the string across lines,
    enabling arbitrary AppleScript injection).
    """
    if '"' in value:
        return f"Error: {label} contains a double-quote character, which is not allowed"
    if "\\" in value:
        return f"Error: {label} contains a backslash character, which is not allowed"
    if "\n" in value or "\r" in value:
        return f"Error: {label} contains a newline character, which is not allowed"
    return None


mcp = FastMCP("iTunesControlServer")


@mcp.tool()
def itunes_play() -> str:
    """Start playback in Music (iTunes)."""
    return run_applescript('tell application "Music" to play')


@mcp.tool()
def itunes_pause() -> str:
    """Pause playback in Music (iTunes)."""
    return run_applescript('tell application "Music" to pause')


@mcp.tool()
def itunes_next() -> str:
    """Skip to the next track."""
    return run_applescript('tell application "Music" to next track')


@mcp.tool()
def itunes_previous() -> str:
    """Return to the previous track."""
    return run_applescript('tell application "Music" to previous track')


@mcp.tool()
def itunes_search(query: str) -> str:
    """
    Search the Music library for tracks whose names contain the given query.
    Returns a list of tracks formatted as "Track Name - Artist".
    """
    if err := _check_applescript_str(query, "query"):
        return err
    script = f"""
    tell application "Music"
        set trackList to every track of playlist "Library" whose name contains "{query}"
        set output to ""
        repeat with t in trackList
            set output to output & (name of t) & " - " & (artist of t) & linefeed
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_play_song(song: str) -> str:
    """
    Play the first track whose name exactly matches the given song name.
    Returns a confirmation message.
    """
    if err := _check_applescript_str(song, "song"):
        return err
    script = f"""
    tell application "Music"
        set theTrack to first track of playlist "Library" whose name is "{song}"
        play theTrack
        return "Now playing: " & (name of theTrack) & " by " & (artist of theTrack)
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_create_playlist(name: str, songs: str) -> str:
    """
    Create a new playlist with the given name and add tracks to it.
    'songs' should be a comma-separated list of exact track names.
    Returns a confirmation message including the number of tracks added.
    """
    if err := _check_applescript_str(name, "name"):
        return err
    if err := _check_applescript_str(songs, "songs"):
        return err
    song_list = [s.strip() for s in songs.split(",") if s.strip()]
    if not song_list:
        return "No songs provided."
    conditions = " or ".join(f'name is "{s}"' for s in song_list)
    script = f"""
    tell application "Music"
        set newPlaylist to make new user playlist with properties {{name:"{name}"}}
        set matchingTracks to every track of playlist "Library" whose ({conditions})
        repeat with t in matchingTracks
            duplicate t to newPlaylist
        end repeat
        return "Playlist \\"{name}\\" created with " & (count of tracks of newPlaylist) & " tracks."
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_library() -> str:
    """
    Return a summary of the Music library, including total tracks and user playlists.
    """
    script = """
    tell application "Music"
        set totalTracks to count of every track of playlist "Library"
        set totalPlaylists to count of user playlists
        return "Total tracks: " & totalTracks & linefeed & "Total playlists: " & totalPlaylists
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_current_song() -> str:
    """
    Get information about the currently playing track.
    Returns the track name, artist, and album.
    """
    script = """
    tell application "Music"
        if player state is playing then
            set currentTrack to current track
            return "Now playing: " & (name of currentTrack) & " by " & (artist of currentTrack) & " from " & (album of currentTrack)
        else
            return "No track is currently playing"
        end if
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_all_songs() -> str:
    """
    Get a list of all songs in the Music library.
    Returns a formatted list of all tracks with their names and artists.
    """
    script = """
    tell application "Music"
        set trackList to every track of playlist "Library"
        set output to ""
        repeat with t in trackList
            set output to output & (name of t) & " - " & (artist of t) & linefeed
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_list_playlists() -> str:
    """
    List all user playlists in the Music library.
    Returns each playlist name and its track count.
    """
    script = """
    tell application "Music"
        set output to ""
        repeat with p in user playlists
            set output to output & (name of p) & " (" & (count of tracks of p) & " tracks)" & linefeed
        end repeat
        return output
    end tell
    """
    return run_applescript(script)


@mcp.tool()
def itunes_export_playlist(name: str, file_path: str) -> str:
    """
    Export all tracks in a playlist to a CSV file.
    'name' is the exact playlist name.
    'file_path' is the destination file path (e.g. /Users/me/Music/playlist.csv).
    Tilde (~) is not expanded; use an absolute or relative path.
    Returns a confirmation message with the number of tracks written.
    """
    if err := _check_applescript_str(name, "name"):
        return err

    abs_path = os.path.abspath(file_path)
    tmp_path = os.path.join(os.path.dirname(abs_path), "." + os.path.basename(abs_path) + ".tmp")

    try:
        tmp_file = open(tmp_path, "w", newline="")
    except OSError as e:
        return f"Error: {e}"

    def fetch_prop(prop):
        """Bulk-fetch a single track property as a SEP-delimited string, return as list."""
        script = f'''
tell application "Music"
    set thePlaylist to user playlist "{name}"
    set vals to {prop} of every track of thePlaylist
    set output to {{}}
    repeat with v in vals
        if v is missing value then
            set end of output to ""
        else
            set end of output to (v as text)
        end if
    end repeat
    set AppleScript's text item delimiters to "{_SEP}"
    set result to output as text
    set AppleScript's text item delimiters to ""
    return result
end tell'''
        raw = run_applescript(script)
        if raw.startswith("Error:"):
            raise RuntimeError(raw)
        # Split on SEP; trailing SEP produces a spurious empty last element
        items = raw.split(_SEP)
        return items[:-1] if items and items[-1] == "" else items

    with contextlib.ExitStack() as cleanup:
        cleanup.enter_context(tmp_file)
        cleanup.callback(_unlink_if_exists, tmp_path)

        try:
            names     = fetch_prop("name")
            artists   = fetch_prop("artist")
            albums    = fetch_prop("album")
            durations = fetch_prop("duration")
        except RuntimeError as e:
            return str(e)

        writer = csv.writer(tmp_file)
        writer.writerow(["Name", "Artist", "Album", "Duration"])
        track_count = 0
        skipped = 0
        for n, ar, al, d in zip(names, artists, albums, durations):
            try:
                secs = round(float(d)) if d else None
                duration = f"{secs // 60}:{secs % 60:02d}" if secs is not None else ""
            except (ValueError, TypeError):
                skipped += 1
                continue
            writer.writerow([n, ar, al, duration])
            track_count += 1

        tmp_file.close()
        os.replace(tmp_path, abs_path)
        cleanup.pop_all()

    msg = f'Exported {track_count} {"track" if track_count == 1 else "tracks"} from "{name}" to {abs_path}'
    if skipped:
        msg += f" ({skipped} malformed {"line" if skipped == 1 else "lines"} skipped)"
    return msg


def main():
    mcp.run()


if __name__ == "__main__":
    main()
