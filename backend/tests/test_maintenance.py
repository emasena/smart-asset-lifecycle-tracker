import sys
import unittest
from decimal import Decimal
from pathlib import Path


ASSET_API_DIR = Path(__file__).resolve().parents[1] / "asset_api"
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
                "description": "Cleaned ventilation system",
                "performedDate": "2026-10-01",
                "conditionAfter": "Good",
                "nextMaintenanceDate": "2027-04-01",
                "cost": "125.00",
            }
        )

        self.assertEqual(result["maintenanceType"], "Preventive")
        self.assertEqual(result["performedDate"], "2026-10-01")
        self.assertEqual(result["conditionAfter"], "Good")
        self.assertEqual(result["cost"], Decimal("125.00"))

    def test_missing_description_is_rejected(self):
        with self.assertRaises(MaintenanceValidationError) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Preventive",
                    "performedDate": "2026-10-01",
                }
            )

        self.assertEqual(context.exception.fields, ["description"])

    def test_invalid_maintenance_type_is_rejected(self):
        with self.assertRaises(MaintenanceValidationError) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Unknown",
                    "description": "Tested asset",
                    "performedDate": "2026-10-01",
                }
            )

        self.assertEqual(context.exception.fields, ["maintenanceType"])

    def test_invalid_performed_date_is_rejected(self):
        with self.assertRaises(MaintenanceValidationError) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Inspection",
                    "description": "Inspected asset",
                    "performedDate": "10/01/2026",
                }
            )

        self.assertEqual(context.exception.fields, ["performedDate"])

    def test_negative_cost_is_rejected(self):
        with self.assertRaises(MaintenanceValidationError) as context:
            validate_maintenance(
                {
                    "maintenanceType": "Repair",
                    "description": "Replaced battery",
                    "performedDate": "2026-10-01",
                    "cost": "-25.00",
                }
            )

        self.assertEqual(context.exception.fields, ["cost"])

    def test_optional_values_are_normalized(self):
        result = validate_maintenance(
            {
                "maintenanceType": "Cleaning",
                "description": "  Cleaned monitor and cables  ",
                "performedDate": "2026-10-01",
            }
        )

        self.assertEqual(
            result["description"],
            "Cleaned monitor and cables",
        )
        self.assertIsNone(result["conditionAfter"])
        self.assertIsNone(result["nextMaintenanceDate"])
        self.assertEqual(result["cost"], Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
