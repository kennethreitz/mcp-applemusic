import asyncio
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import mcp_applemusic as mcp_am


class TestAppleMusicMCP(unittest.TestCase):

    def setUp(self):
        self.mock_as = patch('mcp_applemusic.run_applescript', return_value="OK").start()
        self.mock_url = patch('urllib.request.urlopen').start()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [], "props": {"pageProps": {"state": {"data": {"entity": {"title": "Test", "trackList": []}}}}}}).encode('utf-8')
        self.mock_url.return_value.__enter__.return_value = mock_resp

    def tearDown(self):
        patch.stopall()

    def test_all_68_tool_annotations_and_hints(self):
        tools = asyncio.run(mcp_am.mcp.list_tools())
        self.assertEqual(len(tools), 68)
        for t in tools:
            self.assertIsNotNone(t.annotations)
            self.assertIsInstance(t.annotations.readOnlyHint, bool)
            self.assertIsInstance(t.annotations.destructiveHint, bool)
            self.assertIsInstance(t.annotations.idempotentHint, bool)
            self.assertIsInstance(t.annotations.openWorldHint, bool)

    def test_playback_and_track_controls(self):
        self.assertIsNotNone(mcp_am.itunes_play())
        self.assertIsNotNone(mcp_am.itunes_pause())
        self.assertIsNotNone(mcp_am.itunes_next())
        self.assertIsNotNone(mcp_am.itunes_previous())
        self.assertIsNotNone(mcp_am.itunes_current_track())
        self.assertIsNotNone(mcp_am.itunes_set_volume(50))
        self.assertIsNotNone(mcp_am.itunes_mute(True))
        self.assertIsNotNone(mcp_am.itunes_set_shuffle_mode("songs"))
        self.assertIsNotNone(mcp_am.itunes_repeat("all"))
        self.assertIsNotNone(mcp_am.itunes_seek(15))
        self.assertIsNotNone(mcp_am.itunes_get_position())
        self.assertIsNotNone(mcp_am.itunes_favorite_track(True))
        self.assertIsNotNone(mcp_am.itunes_favorite_song("Song", True))
        self.assertIsNotNone(mcp_am.itunes_dislike_track(True))
        self.assertIsNotNone(mcp_am.itunes_rate_track(5))
        self.assertIsNotNone(mcp_am.itunes_favorite_album(True))
        self.assertIsNotNone(mcp_am.itunes_rate_album(5))
        self.assertIsNotNone(mcp_am.itunes_get_lyrics("Song"))
        self.assertIsNotNone(mcp_am.itunes_set_eq("Acoustic"))
        self.assertIsNotNone(mcp_am.itunes_open_location("https://music.apple.com"))
        self.assertIsNotNone(mcp_am.itunes_get_stream_info())

    def test_audio_inspection_and_tagging(self):
        self.assertIsNotNone(mcp_am.itunes_get_track_audio_info("Song"))
        self.assertIsNotNone(mcp_am.itunes_set_track_bpm(120, "Song"))
        self.assertIsNotNone(mcp_am.itunes_set_track_start_finish(0, 180, "Song"))
        self.assertIsNotNone(mcp_am.itunes_set_track_volume_adjustment(10, "Song"))
        self.assertIsNotNone(mcp_am.itunes_get_track_metadata("Song"))
        self.assertIsNotNone(mcp_am.itunes_edit_track_metadata(song="Song", genre="Rap"))
        self.assertIsNotNone(mcp_am.itunes_get_artwork_info("Song"))

    def test_library_and_catalog_discovery(self):
        self.assertIsNotNone(mcp_am.itunes_search("Dave"))
        self.assertIsNotNone(mcp_am.itunes_search_catalog("Dave"))
        self.assertIsNotNone(mcp_am.itunes_get_artist_top_tracks("Dave"))
        self.assertIsNotNone(mcp_am.itunes_get_artist_albums("Dave"))
        self.assertIsNotNone(mcp_am.itunes_play_song("Location"))

    def test_converters_and_ecosystem_curation(self):
        self.assertIsNotNone(mcp_am.itunes_import_from_spotify("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"))
        self.assertIsNotNone(mcp_am.itunes_generate_share_link("Song"))
        self.assertIsNotNone(mcp_am.itunes_get_top_charts("gb", 10))
        self.assertIsNotNone(mcp_am.itunes_get_new_releases("gb", 10))
        self.assertIsNotNone(mcp_am.itunes_dj_auto_transition("Party", 5))
        self.assertIsNotNone(mcp_am.itunes_get_listening_personality())

    def test_playlist_and_folder_management(self):
        self.assertIsNotNone(mcp_am.itunes_create_playlist("Test"))
        self.assertIsNotNone(mcp_am.itunes_create_playlist_folder("Folder"))
        self.assertIsNotNone(mcp_am.itunes_move_playlist_to_folder("Test", "Folder"))
        self.assertIsNotNone(mcp_am.itunes_set_playlist_description("Test", "Description"))
        self.assertIsNotNone(mcp_am.itunes_add_to_playlist("Song", "Test"))
        self.assertIsNotNone(mcp_am.itunes_remove_from_playlist("Song", "Test"))
        self.assertIsNotNone(mcp_am.itunes_move_playlist_track("Test", 1, 2))
        self.assertIsNotNone(mcp_am.itunes_sort_playlist("Test", "title"))
        self.assertIsNotNone(mcp_am.itunes_favorite_playlist("Test", True))
        self.assertIsNotNone(mcp_am.itunes_duplicate_playlist("Test", "Copy"))
        self.assertIsNotNone(mcp_am.itunes_merge_playlists("Test", "Copy", "Merged"))
        self.assertIsNotNone(mcp_am.itunes_find_duplicates("Test", False))
        self.assertIsNotNone(mcp_am.itunes_delete_playlist("Test"))
        self.assertIsNotNone(mcp_am.itunes_list_playlists())
        self.assertIsNotNone(mcp_am.itunes_get_playlist_tracks("Test"))
        self.assertIsNotNone(mcp_am.itunes_get_playlist_summary("Test"))
        self.assertIsNotNone(mcp_am.itunes_export_playlist("Test", "json"))
        self.assertIsNotNone(mcp_am.itunes_export_playlist("Test", "csv"))
        self.assertIsNotNone(mcp_am.itunes_export_playlist("Test", "markdown"))
        self.assertIsNotNone(mcp_am.itunes_export_playlist("Test", "m3u8"))

    def test_journal_and_replay_analytics(self):
        self.assertIsNotNone(mcp_am.itunes_sync_library_history())
        self.assertIsNotNone(mcp_am.itunes_get_monthly_replay(2026, 8))
        self.assertIsNotNone(mcp_am.itunes_get_listening_history(10))
        self.assertIsNotNone(mcp_am.itunes_get_listening_stats_by_date("2026-08-01", "2026-08-31"))
        self.assertIsNotNone(mcp_am.itunes_log_current_play())

    def test_devices_and_ui_controls(self):
        self.assertIsNotNone(mcp_am.itunes_list_devices())
        self.assertIsNotNone(mcp_am.itunes_set_device("AirPods"))
        self.assertIsNotNone(mcp_am.itunes_set_device_volume("AirPods", 80))
        self.assertIsNotNone(mcp_am.itunes_get_selected_tracks())
        self.assertIsNotNone(mcp_am.itunes_set_miniplayer(True))
        self.assertIsNotNone(mcp_am.itunes_reveal_track("Song"))
        self.assertIsNotNone(mcp_am.itunes_get_stats())

    def test_artist_splitting_helper(self):
        self.assertEqual(mcp_am._split_artists("Dave & Kano"), ["Dave", "Kano"])
        self.assertEqual(mcp_am._split_artists("Victony, Rema & Tempoe"), ["Victony", "Rema", "Tempoe"])
        self.assertIn("Dave", mcp_am._split_artists("Headie One", "18HUNNA (feat. Dave)"))
        self.assertEqual(mcp_am._split_artists("Stormzy", "Lessons"), ["Stormzy"])

    def test_database_persistence_layer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db = Path(tmpdir) / "test_history.db"
            orig_db = mcp_am.DB_PATH
            try:
                mcp_am.DB_PATH = temp_db
                mcp_am._init_db()
                self.assertTrue(temp_db.exists())
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='plays'")
                self.assertEqual(cursor.fetchone()[0], 1)
                conn.close()
            finally:
                mcp_am.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()
