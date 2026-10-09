import sys
import unittest
from decimal import Decimal
from pathlib import Path


ASSET_API_DIR = (
    Path(__file__).resolve().parents[1]
    / "asset_api"
)
sys.path.insert(0, str(ASSET_API_DIR))

from maintenance import (  # noqa: E402
    MaintenanceValidationError,
    validate_maintenance,
)


class MaintenanceValidationTests(unittest.TestCase):
    def test_valid_preventive_maintenance(self):
        result = validate_maintenance(
            {
                "maintenanceType": "Preventive",
                "notes": "Cleaned ventilation system",
                "performedDate": "2026-10-01",
                "conditionAfterService": "Good",
                "cost": "125.00",
            }
        )

        self.assertEqual(
            result["maintenanceType"],
            "Preventive",
        )
        self.assertEqual(
            result["performedDate"],
            "2026-10-01",
        )
        self.assertEqual(
            result["conditionAfterService"],
            "Good",
        )
        self.assertEqual(
            result["cost"],
            Decimal("125.00"),
        )

    def test_missing_notes_is_rejected(self):
        with self.assertRaises(
            MaintenanceValidationError
        ) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Preventive",
                    "performedDate": "2026-10-01",
                    "conditionAfterService": "Good",
                    "cost": "25.00",
                }
            )

        self.assertEqual(
            context.exception.fields,
            ["notes"],
        )

    def test_invalid_maintenance_type_is_rejected(self):
        with self.assertRaises(
            MaintenanceValidationError
        ) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Unknown",
                    "notes": "Tested asset",
                    "performedDate": "2026-10-01",
                    "conditionAfterService": "Good",
                    "cost": "25.00",
                }
            )

        self.assertEqual(
            context.exception.fields,
            ["maintenanceType"],
        )

    def test_invalid_performed_date_is_rejected(self):
        with self.assertRaises(
            MaintenanceValidationError
        ) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Inspection",
                    "notes": "Inspected asset",
                    "performedDate": "10/01/2026",
                    "conditionAfterService": "Good",
                    "cost": "25.00",
                }
            )

        self.assertEqual(
            context.exception.fields,
            ["performedDate"],
        )

    def test_negative_cost_is_rejected(self):
        with self.assertRaises(
            MaintenanceValidationError
        ) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Repair",
                    "notes": "Replaced battery",
                    "performedDate": "2026-10-01",
                    "conditionAfterService": "Good",
                    "cost": "-25.00",
                }
            )

        self.assertEqual(
            context.exception.fields,
            ["cost"],
        )

    def test_optional_cost_is_normalized(self):
        result = validate_maintenance(
            {
                "maintenanceType": "Cleaning",
                "notes": (
                    "  Cleaned monitor and cables  "
                ),
                "performedDate": "2026-10-01",
                "conditionAfterService": "Good",
            }
        )

        self.assertEqual(
            result["notes"],
            "Cleaned monitor and cables",
        )
        self.assertEqual(
            result["conditionAfterService"],
            "Good",
        )
        self.assertEqual(
            result["cost"],
            Decimal("0.00"),
        )


if __name__ == "__main__":
    unittest.main()
