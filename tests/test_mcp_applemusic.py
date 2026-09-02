import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

import mcp_applemusic as mcp_am


class TestAppleMusicMCP(unittest.TestCase):

    def test_all_68_tools_registered_with_complete_annotations(self):
        """Verify that all 68 tools are registered and have full boolean annotations."""
        tools = asyncio.run(mcp_am.mcp.list_tools())
        self.assertEqual(len(tools), 68, f"Expected 68 tools, found {len(tools)}")

        for tool in tools:
            self.assertIsNotNone(tool.annotations, f"Tool '{tool.name}' is missing annotations")
            a = tool.annotations
            self.assertIsInstance(a.readOnlyHint, bool, f"'{tool.name}' readOnlyHint is not bool")
            self.assertIsInstance(a.destructiveHint, bool, f"'{tool.name}' destructiveHint is not bool")
            self.assertIsInstance(a.idempotentHint, bool, f"'{tool.name}' idempotentHint is not bool")
            self.assertIsInstance(a.openWorldHint, bool, f"'{tool.name}' openWorldHint is not bool")

    def test_split_artists_collaborations(self):
        """Verify official Apple Music multi-artist splitting standard."""
        # Simple ampersand split
        artists = mcp_am._split_artists("Dave & Kano")
        self.assertEqual(artists, ["Dave", "Kano"])

        # Comma split
        artists = mcp_am._split_artists("Victony, Rema & Tempoe")
        self.assertEqual(artists, ["Victony", "Rema", "Tempoe"])

        # Featuring tag in song title
        artists = mcp_am._split_artists("Headie One", "18HUNNA (feat. Dave)")
        self.assertIn("Headie One", artists)
        self.assertIn("Dave", artists)

        # Solo artist
        artists = mcp_am._split_artists("Stormzy", "Lessons")
        self.assertEqual(artists, ["Stormzy"])

    def test_database_initialization(self):
        """Verify that SQLite journal database tables are created cleanly."""
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
                count = cursor.fetchone()[0]
                self.assertEqual(count, 1)
                conn.close()
            finally:
                mcp_am.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()
