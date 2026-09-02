# MCP-AppleMusic

[![Glama Score](https://glama.ai/mcp/servers/suleyman416/mcp-applemusic/badges/score.svg)](https://glama.ai/mcp/servers/suleyman416/mcp-applemusic)
[![M8ven Live Monitored](https://m8ven.ai/badge/mcp/suleyman416-mcp-applemusic-flnqtd)](https://m8ven.ai/mcp/suleyman416-mcp-applemusic-flnqtd)
[![Quality: Tier A](https://img.shields.io/badge/Quality-Tier%20A%20(4.5%2F5)-00d992.svg)](https://glama.ai/mcp/servers/suleyman416/mcp-applemusic/score)
[![Maintenance: Grade B](https://img.shields.io/badge/Maintenance-Grade%20B-f5a623.svg)](https://glama.ai/mcp/servers/suleyman416/mcp-applemusic/score)
[![License: MIT](https://img.shields.io/badge/License-MIT%20(Grade%20A)-37a169.svg)](https://opensource.org/licenses/MIT)
[![Tools](https://img.shields.io/badge/Tools-68%20Available-blue.svg)](#complete-suite-of-68-tools)

A comprehensive FastMCP server for controlling Apple Music on macOS with AI agents.

Featuring **68 tools** spanning playback, playlist engineering, listening analytics, Spotify conversion, smart DJ transitions, and audio device control.

---

## Key Superpowers

- **Complete Apple Music Control**: Playback, volume, AirPlay per-device levels, EQ presets, repeat/shuffle modes, and MiniPlayer.
- **Listening Journal & Monthly Replay**: Local SQLite database + background daemon scrobbler for continuous tracking and Apple Replay reports.
- **Cross-Platform Spotify Importer**: Import public Spotify playlists and albums directly into Apple Music (zero logins/tokens required).
- **Smart AI DJ Transitions**: Auto-calculates BPMs and trims `start`/`finish` offsets for continuous, seamless crossfading.
- **Hybrid Lyrics & Universal Links**: Instant lyrics via LRCLIB + universal `song.link` generator for sharing songs across Spotify/YouTube/Tidal.
- **Playlist Management & Export**: Nested folders, deduplication, auto-sorting, and export to JSON, CSV, or Markdown.

---

## Requirements

- **macOS** with Apple Music app installed
- **Python 3.13+**
- **uv** package manager (`brew install uv`)

---

## Quick Setup & Configuration

### Option 1: Automatic 1-Click Install via Smithery
To automatically install and configure for Claude Desktop via [Smithery](https://smithery.ai):

```bash
npx -y @smithery/cli install suleyman416/mcp-applemusic --client claude
```

### Option 2: Claude Desktop (Manual)
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "applemusic": {
      "command": "uvx",
      "args": ["git+https://github.com/suleyman416/mcp-applemusic.git"]
    }
  }
}
```

### Option 3: Cursor / Windsurf / VS Code (Cline & Roo Code)
Add to your MCP settings:

```json
{
  "mcpServers": {
    "applemusic": {
      "command": "uvx",
      "args": ["git+https://github.com/suleyman416/mcp-applemusic.git"]
    }
  }
}
```

> **macOS Permission Note**: When running for the first time, macOS will ask permission for your AI client or terminal to control *Music.app*. Click **Allow** (or check *System Settings ➔ Privacy & Security ➔ Automation*).

---

## Example Natural Language Commands

Once connected, you can talk to your AI agent naturally:

- **Playback & Audio**:
  - *"Play Location by Dave"*
  - *"Set volume to 80% and switch EQ to Hip-Hop"*
  - *"Switch audio output to my AirPods Pro"*
  - *"Turn on shuffle for my Gym playlist"*
- **Discovery & Conversion**:
  - *"Import this Spotify playlist: `https://open.spotify.com/playlist/...`"*
  - *"Generate a universal share link for what's currently playing"*
  - *"Show me the UK Top 10 Apple Music chart"*
  - *"Get the lyrics for this song"*
- **Analytics & Replay**:
  - *"Give me my August Replay report"*
  - *"What is my music listening personality profile?"*
  - *"Show my listening history for the last 10 songs"*
- **DJ & Library Engineering**:
  - *"Configure smart DJ crossfades for my 'Party' playlist"*
  - *"Find and remove duplicate songs in my 'Favorites' playlist"*
  - *"Export my 'Chill Vibes' playlist to Markdown"*

---

## Complete Suite of 68 Tools

```python
# 1. Playback & Track Control
itunes_play()                              # Start playback
itunes_pause()                             # Pause playback
itunes_next()                              # Skip to next track
itunes_previous()                          # Go to previous track
itunes_current_track()                     # Get currently playing track info
itunes_set_volume(volume)                  # Set volume (0–100)
itunes_mute(muted)                         # Mute or unmute audio
itunes_set_shuffle_mode(mode)              # Set shuffle mode ('off', 'songs', 'albums', 'groupings')
itunes_repeat(mode)                        # Set repeat mode ('off', 'one', 'all')
itunes_seek(seconds)                       # Seek/jump to timestamp in seconds
itunes_get_position()                      # Get elapsed position & total duration
itunes_favorite_track(favorited)           # Favorite or unfavorite currently playing track
itunes_favorite_song(song, favorited)      # Favorite or unfavorite any song by title
itunes_dislike_track(disliked)             # Mark current track as Disliked for algorithms
itunes_rate_track(stars)                   # Set star rating (1–5 stars)
itunes_favorite_album(favorited)           # Star or unstar currently playing album
itunes_rate_album(stars)                   # Set star rating on currently playing album
itunes_get_lyrics(song)                    # Get lyrics with global database fallback
itunes_set_eq(preset)                      # Set Equalizer preset (e.g. 'Hip-Hop', 'Bass Booster')
itunes_open_location(url)                  # Stream audio URL or music:// link
itunes_get_stream_info()                   # Get live radio / stream station title & URL

# 2. Audio Quality & Technical Inspection
itunes_get_track_audio_info(song)          # Inspect bit rate, sample rate, BPM, cloud status, format
itunes_set_track_bpm(bpm, song)            # Set BPM tempo on a track
itunes_set_track_start_finish(start, finish, song) # Set custom start/finish offsets
itunes_set_track_volume_adjustment(adj, song) # Set track volume adjustment (-100% to +100%)

# 3. Deep Tagging & Metadata Editor
itunes_get_track_metadata(song)            # Inspect genre, composer, track/disc numbers, comments, dates
itunes_edit_track_metadata(...)            # Update metadata tags (genre, composer, comment, year)
itunes_get_artwork_info(song)              # Inspect album artwork format, description & status

# 4. Library, Catalog & Artist Discovery
itunes_search(query)                       # Search local/iCloud library for tracks
itunes_search_catalog(query, limit)        # Search global Apple Music catalog (100M+ tracks)
itunes_get_artist_top_tracks(artist, limit)# Get top songs for any artist worldwide
itunes_get_artist_albums(artist, limit)    # Get official albums for any artist worldwide
itunes_play_song(song)                     # Find and play a specific song

# 5. Cross-Platform Converters & Curation
itunes_import_from_spotify(url, name)      # Import public Spotify playlist/album directly into Apple Music
itunes_generate_share_link(song)           # Generate universal share link (song.link) for all platforms
itunes_get_top_charts(country, limit)      # Fetch official Apple Music Daily Top 100 Charts
itunes_get_new_releases(country, limit)    # Fetch official Apple Music latest album releases
itunes_dj_auto_transition(playlist, crossfade) # Configure smart DJ radio-style crossfades across playlist
itunes_get_listening_personality()         # AI analysis of your listening archetype & signature vibes

# 6. Playlist & Folder Management
itunes_create_playlist(name)               # Create a new playlist
itunes_create_playlist_folder(name)        # Create a playlist folder
itunes_move_playlist_to_folder(playlist, folder) # Move playlist into a folder
itunes_set_playlist_description(playlist, description) # Set playlist description
itunes_add_to_playlist(song, playlist)     # Add a song to a named playlist (cross-playlist search)
itunes_remove_from_playlist(song, playlist)# Remove a track from a playlist by song title
itunes_move_playlist_track(playlist, from, to) # Move track position in playlist
itunes_sort_playlist(playlist, sort_by)    # Sort playlist by 'title', 'artist', or 'album'
itunes_favorite_playlist(playlist, favorited)# Star or unstar a playlist in sidebar
itunes_duplicate_playlist(source, new_name)# Clone an existing playlist into a new one
itunes_merge_playlists(play_a, play_b, new)# Merge two playlists into a new master playlist
itunes_find_duplicates(playlist, remove)   # Detect duplicate tracks in a playlist
itunes_delete_playlist(playlist)           # Delete a user playlist
itunes_list_playlists()                    # List all playlists with track counts
itunes_get_playlist_tracks(playlist)       # Get all tracks in a playlist
itunes_get_playlist_summary(playlist)      # Get statistical summary (tracks, duration, top artists & songs)
itunes_export_playlist(playlist, format)   # Export playlist to JSON, CSV, Markdown, or M3U8

# 7. Listening Journal & Replay Analytics
itunes_sync_library_history()              # Sync all lifetime play counts and recent plays from iCloud/iPhone
itunes_get_monthly_replay(year, month)     # Generate Apple Music Replay report (hours, top songs/artists)
itunes_get_listening_history(limit, artist)# Chronological playback journal with timestamps & skips
itunes_get_listening_stats_by_date(start, end) # Custom date-range listening analytics & top charts
itunes_log_current_play()                  # Manually record current track to journal database

# 8. Audio Devices & UI Controls
itunes_list_devices()                      # List AirPlay audio output devices & active status
itunes_set_device(device_name)             # Switch audio output device (AirPods, HomePod, TV)
itunes_set_device_volume(device, volume)   # Set individual volume for specific AirPlay device
itunes_get_selected_tracks()               # Get tracks highlighted by user in Music window
itunes_set_miniplayer(enabled)             # Toggle MiniPlayer window mode
itunes_reveal_track(song)                  # Reveal & highlight track in Music window
itunes_get_stats()                         # Generate library analytics (tracks, hours, favorites)
```

---

## Development & Contributing

1. Clone the repository:
```bash
git clone https://github.com/suleyman416/mcp-applemusic.git
cd mcp-applemusic
```

2. Run in development mode:
```bash
uv run mcp_applemusic.py
```

3. Open a Pull Request!

---

## License
MIT License. See [LICENSE](LICENSE) for details.

