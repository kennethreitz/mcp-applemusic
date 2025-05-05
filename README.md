[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/kennethreitz-mcp-applemusic-badge.png)](https://mseep.ai/app/kennethreitz-mcp-applemusic)

# MCP-AppleMusic

A FastMCP server implementation for controlling Apple Music (formerly iTunes) on macOS through AppleScript commands.

## Requirements

- Python 3.13+
- macOS with Apple Music app installed
- MCP library ≥1.2.1

## Installation

First, ensure you have uv installed:
```bash
$ brew install uv
```

Then, with **Claude Desktop**, add the following to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "iTunesControlServer": {
      "command": "uvx",
      "args": ["-n", "mcp-applemusic"]
    }
  }
}
```

## Available Commands

The following commands are available through the MCP server:

```python
itunes_play()         # Start playback
itunes_pause()        # Pause playback
itunes_next()         # Skip to next track
itunes_previous()     # Go to previous track
itunes_search(query)  # Search library for tracks
itunes_play_song(song)  # Play specific song
itunes_create_playlist(name, songs)  # Create new playlist
itunes_library()      # Get library statistics
```

## Usage

Start the server:

```bash
python server.py
```

Example interactions:

```python
# Search for a song
results = itunes_search("Hey Jude")

# Create a new playlist
itunes_create_playlist("Beatles Favorites", ["Yesterday", "Hey Jude", "Let It Be"])

# Play a specific song
itunes_play_song("Hey Jude")
```

## Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/mcp-applemusic.git
cd mcp-applemusic
```

2. Install development dependencies:
```bash
pip install -e ".[dev]"
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Notes

- This tool only works on macOS systems due to its AppleScript dependency
- Requires Apple Music (formerly iTunes) to be installed
