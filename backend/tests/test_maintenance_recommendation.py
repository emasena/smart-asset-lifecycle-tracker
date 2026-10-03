import pathlib
import sys
import unittest


API_DIR = pathlib.Path(__file__).parents[1] / "asset_api"
sys.path.insert(0, str(API_DIR))

from maintenance_recommendation import (  # noqa: E402
    MaintenanceRecommendationError,
    calculate_maintenance_recommendation,
)


class MaintenanceRecommendationTests(unittest.TestCase):
    def test_new_laptop_receives_routine_schedule(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Laptop",
                "condition": "Good",
                "inServiceDate": "2026-09-01",
            },
            as_of_date="2026-10-01",
        )

        self.assertEqual(
            result["recommendedCleaningDate"],
            "2026-11-30",
        )
        self.assertEqual(
            result["recommendedMaintenanceDate"],
            "2027-02-28",
        )
        self.assertEqual(result["daysUntilMaintenance"], 150)
        self.assertEqual(result["maintenanceStatus"], "Current")
        self.assertEqual(result["priority"], "Routine")
        self.assertFalse(result["basedOnMaintenanceHistory"])

    def test_old_printer_is_overdue(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Printer",
                "condition": "Good",
                "inServiceDate": "2026-01-01",
            },
            as_of_date="2026-10-01",
        )

        self.assertEqual(
            result["recommendedMaintenanceDate"],
            "2026-04-01",
        )
        self.assertEqual(result["daysUntilMaintenance"], -183)
        self.assertEqual(result["maintenanceStatus"], "Overdue")
        self.assertEqual(result["priority"], "High")

    def test_explicit_next_maintenance_date_is_used(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Laptop",
                "condition": "Good",
                "inServiceDate": "2025-01-01",
            },
            maintenance_history=[
                {
                    "performedDate": "2026-09-15",
                    "conditionAfter": "Good",
                    "nextMaintenanceDate": "2026-10-15",
                }
            ],
            as_of_date="2026-10-01",
        )

        self.assertEqual(
            result["recommendedMaintenanceDate"],
            "2026-10-15",
        )
        self.assertEqual(result["daysUntilMaintenance"], 14)
        self.assertEqual(result["maintenanceStatus"], "DueSoon")
        self.assertEqual(result["priority"], "Medium")
        self.assertTrue(result["basedOnMaintenanceHistory"])

    def test_poor_condition_shortens_intervals(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Laptop",
                "condition": "Poor",
                "inServiceDate": "2026-09-01",
            },
            as_of_date="2026-10-01",
        )

        self.assertEqual(
            result["recommendedCleaningDate"],
            "2026-10-16",
        )
        self.assertEqual(
            result["recommendedMaintenanceDate"],
            "2026-11-30",
        )
        self.assertEqual(result["priority"], "High")
        self.assertIn(
            "replacement",
            result["recommendation"].lower(),
        )

    def test_damaged_asset_receives_critical_priority(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Network Equipment",
                "condition": "Damaged",
                "inServiceDate": "2026-09-01",
            },
            as_of_date="2026-10-01",
        )

        self.assertEqual(result["priority"], "Critical")
        self.assertIn(
            "remove the asset from service",
            result["recommendation"].lower(),
        )

    def test_latest_maintenance_record_controls_condition(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Laptop",
                "condition": "Poor",
                "inServiceDate": "2025-01-01",
            },
            maintenance_history=[
                {
                    "performedDate": "2026-05-01",
                    "conditionAfter": "Poor",
                },
                {
                    "performedDate": "2026-09-01",
                    "conditionAfter": "Excellent",
                },
            ],
            as_of_date="2026-10-01",
        )

        self.assertEqual(result["conditionUsed"], "Excellent")
        self.assertEqual(
            result["recommendedMaintenanceDate"],
            "2027-04-14",
        )
        self.assertTrue(result["basedOnMaintenanceHistory"])

    def test_unknown_category_uses_default_intervals(self):
        result = calculate_maintenance_recommendation(
            {
                "category": "Office Equipment",
                "condition": "Good",
                "purchaseDate": "2026-09-01",
            },
            as_of_date="2026-10-01",
        )

        self.assertEqual(
            result["recommendedCleaningDate"],
            "2026-11-30",
        )
        self.assertEqual(
            result["recommendedMaintenanceDate"],
            "2027-02-28",
        )

    def test_missing_service_and_purchase_dates_is_rejected(self):
        with self.assertRaises(MaintenanceRecommendationError):
            calculate_maintenance_recommendation(
                {
                    "category": "Laptop",
                    "condition": "Good",
                },
                as_of_date="2026-10-01",
            )


if __name__ == "__main__":
    unittest.main()
