import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch

import bitrix_missing_hr_tasks as app


class SourceFilterTests(unittest.TestCase):
    def test_source_uses_status_id_and_exact_normalized_name(self):
        client = Mock()
        client.list_all.return_value = [
            {"ID": "10", "STATUS_ID": "RETURN", "NAME": " ПЕРЕВАХТОВКА "},
            {"ID": "11", "STATUS_ID": "OTHER", "NAME": "Не перевахтовка"},
        ]
        self.assertEqual(app.get_reassignment_source_ids(client), {"RETURN"})

    def test_missing_source_stops_before_notifications(self):
        client = Mock()
        client.list_all.return_value = []
        with patch.dict(os.environ, {"SETTLEMENT_DATE_FIELD": "SETTLED", "PROJECT_FIELD": "PROJECT"}), patch.object(app, "send_notifications") as send:
            with self.assertRaises(RuntimeError):
                app.audit_missing_tasks(client, notify=True)
            send.assert_not_called()

    def test_return_deals_skipped_while_other_and_empty_sources_remain(self):
        client = Mock()
        client.list_all.side_effect = [
            [{"STATUS_ID": "RETURN", "NAME": "Перевахтовка"}],
            [
                {"ID": str(i), "TITLE": "Test", "SETTLED": "2020-01-01", "SOURCE_ID": source}
                for i, source in enumerate(["RETURN", "WEB", None], start=1)
            ],
        ]
        env = {"SETTLEMENT_DATE_FIELD": "SETTLED", "PROJECT_FIELD": "PROJECT", "HR_RESPONSIBLE_IDS": "4683,69625", "OLDER_THAN_DAYS": "5"}
        with patch.dict(os.environ, env, clear=True), patch.object(app, "task_exists_for_deal", return_value=False) as tasks, patch.object(app, "send_notifications") as send, contextlib.redirect_stdout(io.StringIO()):
            app.audit_missing_tasks(client, notify=True)
        self.assertEqual([call.args[1] for call in tasks.call_args_list], [2, 3])
        self.assertEqual([item["deal_id"] for item in send.call_args.args[0]], [2, 3])
        self.assertIn("SOURCE_ID", client.list_all.call_args.args[1]["select"])


if __name__ == "__main__":
    unittest.main()
