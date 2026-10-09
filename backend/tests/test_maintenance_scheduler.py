import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


API_DIR = pathlib.Path(__file__).parents[1] / "asset_api"
sys.path.insert(0, str(API_DIR))


def _load_scheduler():
    boto3 = types.ModuleType("boto3")
    boto3.resource = MagicMock()
    boto3.client = MagicMock()

    spec = importlib.util.spec_from_file_location(
        "maintenance_scheduler_under_test",
        API_DIR / "maintenance_scheduler.py",
    )
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"boto3": boto3}):
        spec.loader.exec_module(module)

    return module, boto3


OVERDUE_PRINTER = {
    "PK": "ASSET#AST-PRINTER",
    "SK": "METADATA",
    "assetId": "AST-PRINTER",
    "assetTag": "IT-PRN-001",
    "category": "Printer",
    "description": "Office printer",
    "condition": "Good",
    "inServiceDate": "2026-01-01",
}

CURRENT_LAPTOP = {
    "PK": "ASSET#AST-LAPTOP",
    "SK": "METADATA",
    "assetId": "AST-LAPTOP",
    "assetTag": "IT-LAP-001",
    "category": "Laptop",
    "description": "Business laptop",
    "condition": "Good",
    "inServiceDate": "2026-09-01",
}


class MaintenanceSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler, self.boto3 = _load_scheduler()

    def test_overdue_asset_is_included_and_current_is_excluded(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                OVERDUE_PRINTER,
                CURRENT_LAPTOP,
            ]
        }

        report = self.scheduler.evaluate_assets(
            table,
            "2026-10-01",
        )

        self.assertEqual(report["evaluatedCount"], 2)
        self.assertEqual(report["alertCount"], 1)
        self.assertEqual(
            report["alerts"][0]["assetId"],
            "AST-PRINTER",
        )
        self.assertEqual(
            report["alerts"][0]["maintenanceStatus"],
            "Overdue",
        )

    def test_due_soon_asset_uses_maintenance_history(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                CURRENT_LAPTOP,
                {
                    "PK": "ASSET#AST-LAPTOP",
                    "SK": (
                        "MAINTENANCE#2026-09-15T12:00:00Z"
                        "#MNT-12345678"
                    ),
                    "performedDate": "2026-09-15",
                    "conditionAfter": "Good",
                    "nextMaintenanceDate": "2026-10-15",
                },
            ]
        }

        report = self.scheduler.evaluate_assets(
            table,
            "2026-10-01",
        )

        self.assertEqual(report["alertCount"], 1)
        self.assertEqual(
            report["alerts"][0]["maintenanceStatus"],
            "DueSoon",
        )
        self.assertEqual(
            report["alerts"][0]["daysUntilMaintenance"],
            14,
        )

    def test_asset_scan_processes_all_pages(self):
        table = MagicMock()
        table.scan.side_effect = [
            {
                "Items": [OVERDUE_PRINTER],
                "LastEvaluatedKey": {
                    "PK": "ASSET#AST-PRINTER",
                    "SK": "METADATA",
                },
            },
            {
                "Items": [CURRENT_LAPTOP],
            },
        ]

        report = self.scheduler.evaluate_assets(
            table,
            "2026-10-01",
        )

        self.assertEqual(report["evaluatedCount"], 2)
        self.assertEqual(table.scan.call_count, 2)
        self.assertIn(
            "ExclusiveStartKey",
            table.scan.call_args_list[1].kwargs,
        )

    def test_asset_without_required_dates_is_skipped(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                {
                    "PK": "ASSET#AST-INCOMPLETE",
                    "SK": "METADATA",
                    "assetId": "AST-INCOMPLETE",
                    "assetTag": "TEST-INCOMPLETE",
                    "category": "Laptop",
                    "condition": "Good",
                }
            ]
        }

        report = self.scheduler.evaluate_assets(
            table,
            "2026-10-01",
        )

        self.assertEqual(report["evaluatedCount"], 1)
        self.assertEqual(report["skippedCount"], 1)
        self.assertEqual(report["alertCount"], 0)

    def test_history_is_read_from_the_scan_without_per_asset_queries(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                OVERDUE_PRINTER,
                CURRENT_LAPTOP,
                {
                    "PK": "ASSET#AST-PRINTER",
                    "SK": "MAINTENANCE#2026-09-20#MNT-00000001",
                    "performedDate": "2026-09-20",
                    "conditionAfter": "Good",
                },
            ]
        }

        report = self.scheduler.evaluate_assets(table, "2026-10-01")

        table.query.assert_not_called()
        self.assertEqual(table.scan.call_count, 1)
        self.assertEqual(report["evaluatedCount"], 2)
        self.assertEqual(report["alertCount"], 0)

    def test_unexpected_asset_error_skips_only_that_asset(self):
        table = MagicMock()
        bad_asset = {
            **CURRENT_LAPTOP,
            "assetId": "AST-BAD",
            "condition": {"unexpected": "shape"},
        }
        table.scan.return_value = {"Items": [bad_asset, OVERDUE_PRINTER]}

        report = self.scheduler.evaluate_assets(table, "2026-10-01")

        self.assertEqual(report["evaluatedCount"], 2)
        self.assertEqual(report["skippedCount"], 1)
        self.assertEqual(report["alertCount"], 1)
        self.assertEqual(report["alerts"][0]["assetId"], "AST-PRINTER")

    def test_no_alerts_does_not_publish_sns_message(self):
        table = MagicMock()
        sns = MagicMock()

        self.boto3.resource.return_value.Table.return_value = (
            table
        )
        self.boto3.client.return_value = sns

        report = {
            "asOfDate": "2026-10-01",
            "evaluatedCount": 1,
            "skippedCount": 0,
            "alertCount": 0,
            "alerts": [],
        }

        with patch.dict(
            self.scheduler.os.environ,
            {
                "ASSET_TABLE_NAME": "test-assets",
                "MAINTENANCE_TOPIC_ARN": (
                    "arn:aws:sns:us-east-1:123456789012:test"
                ),
            },
        ), patch.object(
            self.scheduler,
            "evaluate_assets",
            return_value=report,
        ):
            result = self.scheduler.lambda_handler(
                {"time": "2026-10-01T12:00:00Z"},
                None,
            )

        self.assertFalse(result["notificationSent"])
        sns.publish.assert_not_called()

    def test_alerts_publish_one_summary_message(self):
        table = MagicMock()
        sns = MagicMock()

        self.boto3.resource.return_value.Table.return_value = (
            table
        )
        self.boto3.client.return_value = sns

        report = {
            "asOfDate": "2026-10-01",
            "evaluatedCount": 2,
            "skippedCount": 0,
            "alertCount": 1,
            "alerts": [
                {
                    "assetId": "AST-PRINTER",
                    "assetTag": "IT-PRN-001",
                    "category": "Printer",
                    "description": "Office printer",
                    "condition": "Good",
                    "maintenanceStatus": "Overdue",
                    "priority": "High",
                    "recommendedMaintenanceDate": "2026-04-01",
                    "recommendedCleaningDate": "2026-01-31",
                    "daysUntilMaintenance": -183,
                }
            ],
        }

        with patch.dict(
            self.scheduler.os.environ,
            {
                "ASSET_TABLE_NAME": "test-assets",
                "MAINTENANCE_TOPIC_ARN": (
                    "arn:aws:sns:us-east-1:123456789012:test"
                ),
            },
        ), patch.object(
            self.scheduler,
            "evaluate_assets",
            return_value=report,
        ):
            result = self.scheduler.lambda_handler(
                {"time": "2026-10-01T12:00:00Z"},
                None,
            )

        self.assertTrue(result["notificationSent"])
        sns.publish.assert_called_once()

        request = sns.publish.call_args.kwargs

        self.assertIn("1 asset(s)", request["Subject"])
        self.assertIn("IT-PRN-001", request["Message"])
        self.assertIn("Overdue", request["Message"])
        self.assertNotIn("Office printer", request["Message"])


if __name__ == "__main__":
    unittest.main()
