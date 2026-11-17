import io
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import bitrix_missing_hr_tasks as app


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"MAILING_HISTORY_PATH": str(Path(directory.name) / "history.json")})
        env.start()
        self.addCleanup(env.stop)
        app.save_history({})

    def test_split_preserves_every_character(self):
        for text in ["short", "x" * 9000, ("Employee | Object\nhttps://example.org/deal/123\n\n" * 200)]:
            parts = app.split_message(text)
            self.assertEqual("".join(parts), text)
            self.assertTrue(all(0 < len(part) <= 3500 for part in parts))

    def test_partial_failure_reports_completed_parts(self):
        client = app.MaxClient("secret")
        with patch.object(client, "_send_part", side_effect=[None, RuntimeError("failed")]) as send:
            with self.assertRaisesRegex(RuntimeError, "1/3"):
                client.send_message("1", "x" * 8000)
            self.assertEqual(send.call_count, 2)

    def test_http_error_includes_response_without_token(self):
        error = HTTPError("https://example.org", 400, "Bad Request", {}, io.BytesIO(b'bad text secret'))
        with patch.object(app.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as result:
                app.MaxClient("secret").send_message("1", "text")
        self.assertIn("HTTP 400", str(result.exception))
        self.assertIn("bad text", str(result.exception))
        self.assertNotIn("secret", str(result.exception))

    def test_recipient_failure_does_not_block_others_or_admin(self):
        env = {"MAX_BOT_TOKEN": "secret", "MAX_HUSAN_USER_ID": "1", "MAX_ALEKSEY_USER_ID": "2", "MAX_IVAN_USER_ID": "3"}
        items = [dict(notify_to=owner, deal_id=i, title="Test", project="Object", settlement_date="2026-01-01") for i, owner in enumerate(["husan_aleksey", "ivan"])]
        with patch.dict(os.environ, env), patch.object(app.MaxClient, "send_message", side_effect=[RuntimeError("failed"), None, None]) as send, patch.object(app, "send_admin_report") as report:
            app.send_notifications(items, 100)
        self.assertEqual([call.args[0] for call in send.call_args_list], ["1", "2", "3"])
        report.assert_called_once()
        statuses = report.call_args.args[3]
        self.assertIn("ошибка", statuses[0])
        self.assertIn("отправлено", statuses[1])


if __name__ == "__main__":
    unittest.main()
