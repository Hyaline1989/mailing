import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bitrix_missing_hr_tasks as app


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        env = patch.dict(os.environ, {"MAILING_HISTORY_PATH": str(Path(temporary.name) / "history.json"), "MAX_BOT_TOKEN": "test", "MAX_HUSAN_USER_ID": "1", "MAX_ALEKSEY_USER_ID": "2"})
        env.start()
        self.addCleanup(env.stop)
        self.items = [dict(deal_id=i, title="Test", project="Object", settlement_date="2026-01-01", notify_to="husan_aleksey") for i in range(100)]

    def test_baseline_suppresses_current_but_allows_new(self):
        with patch.object(app.MaxClient, "send_message") as send, patch.object(app, "send_admin_report"):
            app.baseline_current(self.items[:2])
            send.assert_not_called()
            app.send_notifications(self.items[:2], 2)
            send.assert_not_called()
            app.send_notifications(self.items[:3], 3)
            self.assertEqual(send.call_count, 2)
            send.reset_mock()
            app.send_notifications(self.items[:3], 3)
            send.assert_not_called()
        with self.assertRaises(RuntimeError):
            app.baseline_current(self.items)

    def test_partial_batches_and_separate_recipients(self):
        app.save_history({})
        batches = app.notification_batches("husan_aleksey", self.items)
        self.assertGreater(len(batches), 1)
        with patch.object(app.MaxClient, "send_message", side_effect=[None, RuntimeError("failure")] + [None] * len(batches)), patch.object(app, "send_admin_report"):
            app.send_notifications(self.items, 100)
        history = app.read_history()
        self.assertEqual(len(history["1"]), len(batches[0]))
        self.assertEqual(len(history["2"]), 100)
        with patch.object(app.MaxClient, "send_message") as send, patch.object(app, "send_admin_report"):
            app.send_notifications(self.items, 100)
            self.assertTrue(all(call.args[0] == "1" for call in send.call_args_list))
        self.assertEqual(len(app.read_history()["1"]), 100)

    def test_missing_history_blocks_sending(self):
        with patch.object(app.MaxClient, "send_message") as send:
            with self.assertRaises(RuntimeError):
                app.send_notifications(self.items, 100)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
