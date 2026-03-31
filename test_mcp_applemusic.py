import csv
import os
from unittest.mock import MagicMock, patch

import pytest

import mcp_applemusic
from mcp_applemusic import (
    itunes_create_playlist,
    itunes_export_playlist,
    itunes_list_playlists,
    itunes_play_song,
    itunes_search,
)


# ---------------------------------------------------------------------------
# run_applescript
# ---------------------------------------------------------------------------

def test_run_applescript_returns_stdout():
    mock_result = MagicMock(returncode=0, stdout="hello", stderr="")
    with patch.object(mcp_applemusic.subprocess, "run", return_value=mock_result):
        assert mcp_applemusic.run_applescript("script") == "hello"


def test_run_applescript_strips_whitespace():
    mock_result = MagicMock(returncode=0, stdout="  hello\n", stderr="")
    with patch.object(mcp_applemusic.subprocess, "run", return_value=mock_result):
        assert mcp_applemusic.run_applescript("script") == "hello"


def test_run_applescript_returns_error_on_nonzero():
    mock_result = MagicMock(returncode=1, stdout="", stderr="oops")
    with patch.object(mcp_applemusic.subprocess, "run", return_value=mock_result):
        assert mcp_applemusic.run_applescript("script") == "Error: oops"


# ---------------------------------------------------------------------------
# _unlink_if_exists
# ---------------------------------------------------------------------------

def test_unlink_if_exists_deletes_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    mcp_applemusic._unlink_if_exists(str(f))
    assert not f.exists()


def test_unlink_if_exists_tolerates_missing_file(tmp_path):
    mcp_applemusic._unlink_if_exists(str(tmp_path / "nonexistent.txt"))
    # passes if no exception is raised


# ---------------------------------------------------------------------------
# _check_applescript_str
# ---------------------------------------------------------------------------

def test_check_applescript_str_passes_clean_input():
    assert mcp_applemusic._check_applescript_str("Hey Jude", "query") is None


def test_check_applescript_str_rejects_double_quote():
    result = mcp_applemusic._check_applescript_str('bad"input', "query")
    assert result.startswith("Error:")
    assert "query" in result


def test_check_applescript_str_rejects_backslash():
    result = mcp_applemusic._check_applescript_str("back\\slash", "query")
    assert result.startswith("Error:")
    assert "query" in result


def test_check_applescript_str_rejects_newline():
    result = mcp_applemusic._check_applescript_str("line\nbreak", "query")
    assert result.startswith("Error:")
    assert "query" in result


def test_check_applescript_str_rejects_carriage_return():
    result = mcp_applemusic._check_applescript_str("line\rbreak", "query")
    assert result.startswith("Error:")
    assert "query" in result


# ---------------------------------------------------------------------------
# injection validation on tools
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_str", ['"', "\\", "\n", "\r"], ids=["double-quote", "backslash", "newline", "carriage-return"])
@pytest.mark.parametrize("call", [
    pytest.param(lambda s, _: itunes_search(s),                              id="search"),
    pytest.param(lambda s, _: itunes_play_song(s),                           id="play_song"),
    pytest.param(lambda s, _: itunes_create_playlist(s, "Hey Jude"),         id="create_playlist_name"),
    pytest.param(lambda s, _: itunes_create_playlist("Good Name", s),        id="create_playlist_song"),
    pytest.param(lambda s, p: itunes_export_playlist(s, str(p / "out.csv")), id="export_name"),
])
def test_injection_rejected(bad_str, call, tmp_path):
    with patch.object(mcp_applemusic, "run_applescript") as mock_as:
        result = call(bad_str, tmp_path)
    assert result.startswith("Error:")
    mock_as.assert_not_called()


# ---------------------------------------------------------------------------
# itunes_list_playlists
# ---------------------------------------------------------------------------

def test_list_playlists_passes_through_output():
    output = "Favourites (10 tracks)\nRoad Trip (42 tracks)\n"
    with patch.object(mcp_applemusic, "run_applescript", return_value=output):
        assert itunes_list_playlists() == output


def test_list_playlists_passes_through_error():
    with patch.object(mcp_applemusic, "run_applescript", return_value="Error: Music not running"):
        assert itunes_list_playlists() == "Error: Music not running"


# ---------------------------------------------------------------------------
# itunes_export_playlist helpers
# ---------------------------------------------------------------------------

def _make_raw(*tracks):
    """Build _SEP-delimited AppleScript output for the given tracks.

    Each argument is a track represented as the tuple (name, artist, album,
    mins, secs). No trailing newline, matching what run_applescript returns
    after strip(). Tuples of other lengths produce malformed lines useful for
    testing the skip logic.
    """
    return "\n".join(mcp_applemusic._SEP.join(str(f) for f in t) for t in tracks)


def _read_csv(file_path):
    with open(file_path, newline="") as f:
        return list(csv.reader(f))


def _tmp_path_for(dest):
    """Return the expected temp file path for a given destination.

    Mirrors the tmp path construction in itunes_export_playlist. If the
    production naming scheme changes, this helper must be updated to match
    or cleanup assertions will silently test the wrong path.
    """
    abs_dest = os.path.abspath(dest)
    return os.path.join(os.path.dirname(abs_dest), "." + os.path.basename(abs_dest) + ".tmp")


# ---------------------------------------------------------------------------
# itunes_export_playlist
# ---------------------------------------------------------------------------

def test_export_writes_csv_and_cleans_up_tmp(tmp_path):
    raw = _make_raw(("Hey Jude", "The Beatles", "Past Masters", 7, 4))
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        result = itunes_export_playlist("Beatles", dest)

    rows = _read_csv(dest)
    assert rows[0] == ["Name", "Artist", "Album", "Duration"]
    assert rows[1] == ["Hey Jude", "The Beatles", "Past Masters", "7:04"]
    assert result.startswith('Exported 1 track from "Beatles" to ')
    assert not os.path.exists(_tmp_path_for(dest))


def test_export_uses_absolute_path_for_relative_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = _make_raw(("Song", "Artist", "Album", 3, 0))
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        result = itunes_export_playlist("PL", "out.csv")
    assert result.startswith(f'Exported 1 track from "PL" to {tmp_path / "out.csv"}')


@pytest.mark.parametrize("mins,secs,expected", [
    (3, 5,  "3:05"),
    (4, 10, "4:10"),
], ids=["pads-below-ten", "no-pad-at-ten"])
def test_export_formats_duration(tmp_path, mins, secs, expected):
    raw = _make_raw(("Song", "Artist", "Album", mins, secs))
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        itunes_export_playlist("PL", dest)
    assert _read_csv(dest)[1] == ["Song", "Artist", "Album", expected]


def test_export_quotes_fields_with_commas(tmp_path):
    raw = _make_raw(("You, Me & Us", "Smith, John", "Vol. 1, Remastered", 2, 30))
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        itunes_export_playlist("PL", dest)
    assert _read_csv(dest)[1] == ["You, Me & Us", "Smith, John", "Vol. 1, Remastered", "2:30"]


def test_export_multiple_tracks(tmp_path):
    raw = _make_raw(
        ("Yesterday", "The Beatles", "Help!", 2, 5),
        ("Let It Be", "The Beatles", "Let It Be", 3, 52),
    )
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        result = itunes_export_playlist("Beatles", dest)

    rows = _read_csv(dest)
    assert rows[0] == ["Name", "Artist", "Album", "Duration"]
    assert rows[1] == ["Yesterday", "The Beatles", "Help!", "2:05"]
    assert rows[2] == ["Let It Be", "The Beatles", "Let It Be", "3:52"]
    assert result.startswith('Exported 2 tracks from "Beatles" to ')


def test_export_empty_playlist(tmp_path):
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=_make_raw()):
        result = itunes_export_playlist("Empty", dest)
    assert _read_csv(dest) == [["Name", "Artist", "Album", "Duration"]]
    assert result.startswith('Exported 0 tracks from "Empty" to ')


def test_export_skips_non_integer_duration(tmp_path):
    raw = _make_raw(
        ("Bad Mins", "Artist", "Album", "NaN", "0"),   # non-integer mins — triggers skip
        ("Bad Secs", "Artist", "Album", "3", "NaN"),   # non-integer secs — triggers skip
        ("Good Song", "Artist", "Album", 3, 30),
    )
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        result = itunes_export_playlist("PL", dest)
    rows = _read_csv(dest)
    assert len(rows) == 2  # header + 1 good track
    assert rows[1] == ["Good Song", "Artist", "Album", "3:30"]
    assert "2 malformed lines skipped" in result


def test_export_skips_and_reports_malformed_lines(tmp_path):
    raw = _make_raw(
        ("x", "x", "x", "x", "x", "x"),  # 6 fields — triggers skip
        ("Good Song", "Artist", "Album", 3, 30),
    )
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        result = itunes_export_playlist("PL", dest)

    rows = _read_csv(dest)
    assert len(rows) == 2  # header + 1 good track
    assert rows[1] == ["Good Song", "Artist", "Album", "3:30"]
    assert result.startswith('Exported 1 track from "PL" to ')
    assert "1 malformed line skipped" in result


def test_export_reports_multiple_skipped_lines(tmp_path):
    raw = _make_raw(
        ("x", "x", "x", "x", "x", "x"),  # 6 fields — triggers skip
        ("x", "x", "x", "x", "x", "x"),  # 6 fields — triggers skip
    )
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value=raw):
        result = itunes_export_playlist("PL", dest)
    assert _read_csv(dest) == [["Name", "Artist", "Album", "Duration"]]
    assert "2 malformed lines skipped" in result


def test_export_returns_applescript_error_without_writing(tmp_path):
    dest = str(tmp_path / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript", return_value="Error: playlist not found"):
        result = itunes_export_playlist("Missing", dest)
    assert result.startswith("Error:")
    assert not os.path.exists(dest)
    assert not os.path.exists(_tmp_path_for(dest))


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores file permissions")
def test_export_fails_early_on_unwritable_directory(tmp_path):
    read_only = tmp_path / "ro"
    read_only.mkdir(mode=0o555)
    dest = str(read_only / "out.csv")
    with patch.object(mcp_applemusic, "run_applescript") as mock_as:
        result = itunes_export_playlist("PL", dest)
    assert result.startswith("Error:")
    mock_as.assert_not_called()
    assert not os.path.exists(dest)
