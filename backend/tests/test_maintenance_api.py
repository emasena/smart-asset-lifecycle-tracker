import json
import pathlib
import sys
import unittest

from unittest.mock import patch

TEST_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))

from test_unique_asset_tags import _load_api  # noqa: E402

ASSET = {
    "PK": "ASSET#AST-TEST",
    "SK": "METADATA",
    "assetId": "AST-TEST",
    "assetTag": "TEST-001",
    "category": "Laptop",
    "notes": "Test laptop",
    "department": "IT",
    "assignedUserId": "employee-1",
    "condition": "Good",
    "status": "Available",
    "purchaseDate": "2026-09-01",
    "inServiceDate": "2026-09-01",
}

MAINTENANCE = {
    "maintenanceType": "Preventive",
    "notes": "Cleaned ventilation system",
    "performedDate": "2026-10-01",
    "conditionAfterService": "Good",
    "nextMaintenanceDate": "2027-04-01",
    "cost": "125.00",
}


class MaintenanceApiTests(unittest.TestCase):
    def setUp(self):
        self.api, self.table, _ = _load_api()
        self.table.get_item.return_value = {"Item": ASSET}

    def event(self, payload=None, group="Administrator", sub="user-1"):
        return {
            "httpMethod": "POST",
            "resource": "/assets/{assetId}/maintenance",
            "pathParameters": {
                "assetId": "AST-TEST",
            },
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": sub,
                        "email": f"{sub}@example.com",
                        "cognito:groups": f"[{group}]",
                        "custom:department": "IT",
                    }
                }
            },
            "body": json.dumps(payload or MAINTENANCE),
        }
    def recommendation_event(
        self,
        group="Administrator",
        sub="user-1",
        department="IT",
    ):
        event = self.event(
            group=group,
            sub=sub,
        )
        event["resource"] = (
            "/assets/{assetId}/maintenance-recommendation"
        )
        event["path"] = (
            "/assets/AST-TEST/maintenance-recommendation"
        )
        event["requestContext"]["authorizer"]["claims"][
            "custom:department"
        ] = department
        event.pop("body")

        return event

    def test_administrator_can_create_maintenance(self):
        result = self.api.lambda_handler(
            self.event(),
            None,
        )

        self.assertEqual(result["statusCode"], 201)
        self.table.put_item.assert_called_once()

    def test_authorized_technician_can_create_maintenance(self):
        result = self.api.lambda_handler(
            self.event(
                group="Technician",
                sub="technician-1",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 201)
        self.table.put_item.assert_called_once()

    def test_employee_cannot_create_maintenance(self):
        result = self.api.lambda_handler(
            self.event(
                group="Employee",
                sub="employee-1",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 403)
        self.table.put_item.assert_not_called()

    def test_auditor_cannot_create_maintenance(self):
        result = self.api.lambda_handler(
            self.event(
                group="Auditor",
                sub="auditor-1",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 403)
        self.table.put_item.assert_not_called()

    def test_performed_by_comes_from_cognito_claims(self):
        payload = {
            **MAINTENANCE,
            "performedBy": "browser-supplied-user",
            "performedByEmail": "attacker@example.com",
        }

        result = self.api.lambda_handler(
            self.event(
                payload=payload,
                sub="authenticated-user",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 201)

        stored_item = self.table.put_item.call_args.kwargs["Item"]

        self.assertEqual(
            stored_item["performedBy"],
            "authenticated-user",
        )
        self.assertEqual(
            stored_item["performedByEmail"],
            "authenticated-user@example.com",
        )
        self.assertNotEqual(
            stored_item["performedBy"],
            "browser-supplied-user",
        )

    def test_invalid_payload_returns_400(self):
        invalid_payload = {
            "maintenanceType": "Preventive",
            "performedDate": "2026-10-01",
        }

        result = self.api.lambda_handler(
            self.event(payload=invalid_payload),
            None,
        )

        self.assertEqual(result["statusCode"], 400)
        self.table.put_item.assert_not_called()

    def test_missing_asset_returns_404(self):
        self.table.get_item.return_value = {}

        result = self.api.lambda_handler(
            self.event(),
            None,
        )

        self.assertEqual(result["statusCode"], 404)
        self.table.put_item.assert_not_called()

    def test_authorized_manager_can_list_maintenance(self):
        self.table.query.return_value = {
            "Items": [
                {
                    "PK": "ASSET#AST-TEST",
                    "SK": (
                        "MAINTENANCE#2026-10-01T12:00:00+00:00"
                        "#MNT-12345678"
                    ),
                    "maintenanceId": "MNT-12345678",
                    "assetId": "AST-TEST",
                    "maintenanceType": "Preventive",
                    "notes": "Cleaned ventilation system",
                }
            ]
        }

        event = self.event(
            group="Manager",
            sub="manager-1",
        )
        event["httpMethod"] = "GET"
        event.pop("body")

        result = self.api.lambda_handler(event, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["count"], 1)
        self.assertIn("recommendation", body)
        self.assertIn(
            body["recommendation"]["maintenanceStatus"],
            {"Current", "DueSoon", "Overdue"},
        )
        self.assertIn(
            "recommendedCleaningDate",
            body["recommendation"],
        )
        self.assertIn(
            "recommendedMaintenanceDate",
            body["recommendation"],
        )
        self.assertEqual(
            body["items"][0]["maintenanceId"],
            "MNT-12345678",
        )

    def test_other_department_manager_cannot_list_maintenance(self):
        event = self.event(
            group="Manager",
            sub="manager-1",
        )
        event["httpMethod"] = "GET"
        event.pop("body")
        event["requestContext"]["authorizer"]["claims"][
            "custom:department"
        ] = "Finance"

        result = self.api.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 403)
        self.table.query.assert_not_called()

    def test_administrator_can_generate_ai_recommendation(self):
        self.table.query.return_value = {
            "Items": [],
        }

        ai_result = {
            "recommendedActions": [
                "Clean the ventilation openings."
            ],
            "riskLevel": "Low",
            "rationale": "Routine preventive maintenance.",
            "reviewStatus": "NeedsReview",
        }

        with patch.object(
            self.api,
            "generate_maintenance_advice",
            return_value=ai_result,
        ) as generate:
            result = self.api.lambda_handler(
                self.recommendation_event(),
                None,
            )

        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(
            body["aiRecommendation"]["riskLevel"],
            "Low",
        )
        self.assertTrue(body["generatedForReview"])
        generate.assert_called_once()

    def test_technician_can_generate_ai_recommendation(self):
        self.table.query.return_value = {
            "Items": [],
        }

        ai_result = {
            "recommendedActions": [
                "Inspect the battery."
            ],
            "riskLevel": "Medium",
            "rationale": "Preventive inspection is due.",
            "reviewStatus": "NeedsReview",
        }

        with patch.object(
            self.api,
            "generate_maintenance_advice",
            return_value=ai_result,
        ):
            result = self.api.lambda_handler(
                self.recommendation_event(
                    group="Technician",
                    sub="technician-1",
                ),
                None,
            )

        self.assertEqual(result["statusCode"], 200)

    def test_employee_cannot_generate_ai_recommendation(self):
        with patch.object(
            self.api,
            "generate_maintenance_advice",
        ) as generate:
            result = self.api.lambda_handler(
                self.recommendation_event(
                    group="Employee",
                    sub="employee-1",
                ),
                None,
            )

        self.assertEqual(result["statusCode"], 403)
        generate.assert_not_called()
        self.table.query.assert_not_called()

    def test_other_department_technician_cannot_generate(self):
        with patch.object(
            self.api,
            "generate_maintenance_advice",
        ) as generate:
            result = self.api.lambda_handler(
                self.recommendation_event(
                    group="Technician",
                    sub="technician-1",
                    department="Finance",
                ),
                None,
            )

        self.assertEqual(result["statusCode"], 403)
        generate.assert_not_called()
        self.table.query.assert_not_called()

    def test_invalid_bedrock_response_returns_502(self):
        self.table.query.return_value = {
            "Items": [],
        }

        with patch.object(
            self.api,
            "generate_maintenance_advice",
            side_effect=self.api.MaintenanceAiError(
                "Invalid model response."
            ),
        ):
            result = self.api.lambda_handler(
                self.recommendation_event(),
                None,
            )

        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 502)
        self.assertEqual(
            body["error"],
            "AiRecommendationError",
        )
        self.assertNotIn(
            "Invalid model response",
            body["message"],
        )


if __name__ == "__main__":
    unittest.main()
