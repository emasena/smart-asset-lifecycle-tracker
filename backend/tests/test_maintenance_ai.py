import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


API_DIR = pathlib.Path(__file__).parents[1] / "asset_api"


def _load_module():
    boto3 = types.ModuleType("boto3")
    boto3.client = MagicMock()

    spec = importlib.util.spec_from_file_location(
        "maintenance_ai_under_test",
        API_DIR / "maintenance_ai.py",
    )
    module = importlib.util.module_from_spec(spec)

    with patch.dict(sys.modules, {"boto3": boto3}):
        spec.loader.exec_module(module)

    return module


VALID_RESPONSE = {
    "recommendedActions": [
        "Clean the ventilation openings.",
        "Run a battery health inspection.",
    ],
    "riskLevel": "Medium",
    "rationale": (
        "The asset is approaching its scheduled "
        "preventive-maintenance date."
    ),
    "reviewStatus": "NeedsReview",
}


class MaintenanceAiTests(unittest.TestCase):
    def setUp(self):
        self.ai = _load_module()

    def test_valid_recommendation_is_normalized(self):
        result = self.ai.validate_ai_recommendation(
            json.dumps(VALID_RESPONSE)
        )

        self.assertEqual(result["riskLevel"], "Medium")
        self.assertEqual(result["reviewStatus"], "NeedsReview")
        self.assertEqual(len(result["recommendedActions"]), 2)

    def test_markdown_json_fence_is_removed(self):
        raw = (
            "```json\n"
            + json.dumps(VALID_RESPONSE)
            + "\n```"
        )

        result = self.ai.validate_ai_recommendation(raw)

        self.assertEqual(result["riskLevel"], "Medium")

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(self.ai.MaintenanceAiError):
            self.ai.validate_ai_recommendation(
                "This is not JSON."
            )

    def test_invalid_risk_level_is_rejected(self):
        invalid = {
            **VALID_RESPONSE,
            "riskLevel": "Extreme",
        }

        with self.assertRaises(self.ai.MaintenanceAiError):
            self.ai.validate_ai_recommendation(
                json.dumps(invalid)
            )

    def test_more_than_five_actions_is_rejected(self):
        invalid = {
            **VALID_RESPONSE,
            "recommendedActions": [
                f"Action {number}"
                for number in range(6)
            ],
        }

        with self.assertRaises(self.ai.MaintenanceAiError):
            self.ai.validate_ai_recommendation(
                json.dumps(invalid)
            )

    def test_browser_and_identity_fields_are_not_sent(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": json.dumps(
                                VALID_RESPONSE
                            )
                        }
                    ]
                }
            }
        }

        asset = {
            "category": "Laptop",
            "description": "Business laptop",
            "condition": "Good",
            "inServiceDate": "2026-01-01",
            "usefulLifeMonths": 48,
            "status": "Available",
            "createdBy": "private-creator-id",
            "assignedUserId": "private-employee-id",
            "department": "Private Department",
        }

        history = [
            {
                "maintenanceType": "Preventive",
                "description": "Cleaned ventilation system",
                "performedDate": "2026-09-01",
                "conditionAfter": "Good",
                "nextMaintenanceDate": "2027-03-01",
                "performedBy": "private-technician-id",
                "performedByEmail": "private@example.com",
                "cost": "125.00",
            }
        ]

        schedule = {
            "maintenanceStatus": "Current",
            "recommendedCleaningDate": "2026-11-30",
            "recommendedMaintenanceDate": "2027-02-28",
            "daysUntilMaintenance": 150,
        }

        result = self.ai.generate_maintenance_advice(
            asset,
            history,
            schedule,
            bedrock_client=bedrock,
        )

        self.assertEqual(result["riskLevel"], "Medium")

        request = bedrock.converse.call_args.kwargs
        prompt = request["messages"][0]["content"][0]["text"]

        self.assertNotIn("private-creator-id", prompt)
        self.assertNotIn("private-employee-id", prompt)
        self.assertNotIn("Private Department", prompt)
        self.assertNotIn("private-technician-id", prompt)
        self.assertNotIn("private@example.com", prompt)
        self.assertNotIn('"cost"', prompt)

        self.assertIn("Business laptop", prompt)
        self.assertIn("2027-02-28", prompt)

    def test_bedrock_request_is_deterministic(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": json.dumps(
                                VALID_RESPONSE
                            )
                        }
                    ]
                }
            }
        }

        self.ai.generate_maintenance_advice(
            {
                "category": "Laptop",
                "condition": "Good",
                "inServiceDate": "2026-01-01",
            },
            [],
            {
                "maintenanceStatus": "Current",
                "recommendedMaintenanceDate": "2027-01-01",
            },
            bedrock_client=bedrock,
        )

        request = bedrock.converse.call_args.kwargs

        self.assertEqual(
            request["modelId"],
            "us.amazon.nova-lite-v1:0",
        )
        self.assertEqual(
            request["inferenceConfig"]["temperature"],
            0,
        )
        self.assertEqual(
            request["inferenceConfig"]["maxTokens"],
            450,
        )


if __name__ == "__main__":
    unittest.main()
