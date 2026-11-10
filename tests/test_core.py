#!/usr/bin/env python3
import sys, unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import core_data_to_datetime, format_datetime, jid_to_display, MSG_TYPE, _human_size

class TestCore(unittest.TestCase):
    def test_ts(self):
        self.assertIsNone(core_data_to_datetime(0))
        self.assertIsNone(core_data_to_datetime(None))
        dt = core_data_to_datetime(370812010.56)
        self.assertEqual(dt.year, 2012)
    def test_fmt(self):
        dt = datetime(2015, 6, 15, 14, 30)
        self.assertEqual(format_datetime(dt), "15/06/2015 14:30")
    def test_jid(self):
        self.assertEqual(jid_to_display("5511@s.whatsapp.net"), "5511")
    def test_types(self):
        self.assertEqual(MSG_TYPE[1], "image")
    def test_size(self):
        self.assertIn("KB", _human_size(5000))

if __name__ == "__main__":
    unittest.main()
