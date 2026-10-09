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
    "description": "Test laptop",
    "department": "IT",
    "assignedUserId": "employee-1",
    "condition": "Good",
    "status": "Available",
    "purchaseDate": "2026-09-01",
    "inServiceDate": "2026-09-01",
}

MAINTENANCE = {
    "maintenanceType": "Preventive",
    "description": "Cleaned ventilation system",
    "performedDate": "2026-10-01",
    "conditionAfter": "Good",
    "nextMaintenanceDate": "2027-04-01",
    "cost": "125.00",
}

RECORD = {
    "PK": "ASSET#AST-TEST",
    "SK": "MAINTENANCE#2026-10-01#MNT-12345678",
    "maintenanceId": "MNT-12345678",
    "assetId": "AST-TEST",
    **MAINTENANCE,
    "performedBy": "technician-1",
    "performedByEmail": "technician-1@example.com",
    "createdAt": "2026-10-01T12:00:00+00:00",
}


class MaintenanceApiTests(unittest.TestCase):
    def setUp(self):
        self.api, self.table, _, _ = _load_api()
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
                    "description": "Cleaned ventilation system",
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

    def test_bedrock_client_error_returns_502(self):
        self.table.query.return_value = {"Items": []}

        with patch.object(
            self.api,
            "generate_maintenance_advice",
            side_effect=self.api.ClientError(
                {"Error": {"Code": "ThrottlingException"}}
            ),
        ):
            result = self.api.lambda_handler(
                self.recommendation_event(),
                None,
            )

        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 502)
        self.assertEqual(body["error"], "AiRecommendationError")
        self.assertNotIn("Throttling", body["message"])

    def test_asset_without_dates_returns_422_without_calling_bedrock(self):
        self.table.query.return_value = {"Items": []}
        undated = {
            key: value
            for key, value in ASSET.items()
            if key not in {"purchaseDate", "inServiceDate"}
        }
        self.table.get_item.return_value = {"Item": undated}

        with patch.object(
            self.api,
            "generate_maintenance_advice",
        ) as generate:
            result = self.api.lambda_handler(
                self.recommendation_event(),
                None,
            )

        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 422)
        self.assertEqual(body["error"], "ScheduleUnavailable")
        generate.assert_not_called()

    def test_list_maintenance_reads_every_page(self):
        first = dict(RECORD)
        second = {
            **RECORD,
            "SK": "MAINTENANCE#2026-09-01#MNT-87654321",
            "maintenanceId": "MNT-87654321",
            "performedDate": "2026-09-01",
        }
        self.table.query.side_effect = [
            {"Items": [first], "LastEvaluatedKey": {"SK": first["SK"]}},
            {"Items": [second]},
        ]
        event = self.event()
        event["httpMethod"] = "GET"
        event.pop("body")

        result = self.api.lambda_handler(event, None)
        body = json.loads(result["body"])

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(
            [item["maintenanceId"] for item in body["items"]],
            ["MNT-12345678", "MNT-87654321"],
        )
        self.assertEqual(
            self.table.query.call_args_list[1].kwargs["ExclusiveStartKey"],
            {"SK": first["SK"]},
        )

    def test_non_finite_cost_returns_400(self):
        for cost in ("NaN", "Infinity", "-Infinity", "sNaN"):
            result = self.api.lambda_handler(
                self.event(payload={**MAINTENANCE, "cost": cost}),
                None,
            )

            self.assertEqual(result["statusCode"], 400, cost)

        self.table.put_item.assert_not_called()

    def test_create_uses_performed_date_in_sort_key(self):
        self.api.lambda_handler(self.event(), None)

        stored_item = self.table.put_item.call_args.kwargs["Item"]

        self.assertTrue(
            stored_item["SK"].startswith("MAINTENANCE#2026-10-01#MNT-")
        )


class MaintenanceRecordChangeTests(unittest.TestCase):
    def setUp(self):
        self.api, self.table, self.transactions, _ = _load_api()
        self.table.get_item.return_value = {"Item": ASSET}
        self.table.query.return_value = {"Items": [dict(RECORD)]}

    def event(
        self,
        method="PUT",
        payload=None,
        group="Administrator",
        sub="user-1",
        department="IT",
    ):
        event = {
            "httpMethod": method,
            "resource": "/assets/{assetId}/maintenance/{maintenanceId}",
            "pathParameters": {
                "assetId": "AST-TEST",
                "maintenanceId": "MNT-12345678",
            },
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": sub,
                        "email": f"{sub}@example.com",
                        "cognito:groups": f"[{group}]",
                        "custom:department": department,
                    }
                }
            },
        }

        if method == "PUT":
            event["body"] = json.dumps(payload or MAINTENANCE)

        return event

    def test_administrator_can_update_record_on_same_date(self):
        result = self.api.lambda_handler(self.event(), None)

        self.assertEqual(result["statusCode"], 200)
        stored_item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual(stored_item["SK"], RECORD["SK"])
        self.assertEqual(stored_item["updatedBy"], "user-1")
        self.transactions.transact_write_items.assert_not_called()

    def test_new_performed_date_moves_record_atomically(self):
        payload = {**MAINTENANCE, "performedDate": "2026-10-02"}

        result = self.api.lambda_handler(
            self.event(payload=payload),
            None,
        )

        self.assertEqual(result["statusCode"], 200)
        self.table.put_item.assert_not_called()
        writes = self.transactions.transact_write_items.call_args.kwargs[
            "TransactItems"
        ]
        self.assertEqual(
            writes[0]["Put"]["Item"]["SK"],
            {"S": "MAINTENANCE#2026-10-02#MNT-12345678"},
        )
        self.assertEqual(
            writes[1]["Delete"]["Key"]["SK"],
            {"S": RECORD["SK"]},
        )

    def test_update_keeps_original_identity_fields(self):
        payload = {
            **MAINTENANCE,
            "performedBy": "browser-supplied-user",
            "maintenanceId": "MNT-OTHER",
            "createdAt": "2000-01-01",
        }

        self.api.lambda_handler(self.event(payload=payload), None)

        stored_item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual(stored_item["performedBy"], "technician-1")
        self.assertEqual(stored_item["maintenanceId"], "MNT-12345678")
        self.assertEqual(stored_item["createdAt"], RECORD["createdAt"])

    def test_technician_can_update_own_record(self):
        result = self.api.lambda_handler(
            self.event(group="Technician", sub="technician-1"),
            None,
        )

        self.assertEqual(result["statusCode"], 200)

    def test_technician_who_is_also_auditor_cannot_update_other_department(
        self,
    ):
        result = self.api.lambda_handler(
            self.event(
                group="Technician,Auditor",
                sub="technician-1",
                department="Finance",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 403)
        self.table.query.assert_not_called()
        self.table.put_item.assert_not_called()
        self.transactions.transact_write_items.assert_not_called()

    def test_technician_who_is_also_auditor_can_update_own_department(self):
        result = self.api.lambda_handler(
            self.event(group="Technician,Auditor", sub="technician-1"),
            None,
        )

        self.assertEqual(result["statusCode"], 200)

    def test_administrator_can_update_other_department(self):
        result = self.api.lambda_handler(
            self.event(department="Finance"),
            None,
        )

        self.assertEqual(result["statusCode"], 200)

    def test_update_is_conditioned_on_the_version_read(self):
        self.table.query.return_value = {"Items": [{
            **RECORD,
            "updatedAt": "2026-10-02T09:00:00+00:00",
        }]}

        self.api.lambda_handler(self.event(), None)

        kwargs = self.table.put_item.call_args.kwargs
        self.assertIn("updatedAt = :updated_at", kwargs["ConditionExpression"])
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":updated_at"],
            "2026-10-02T09:00:00+00:00",
        )

    def test_never_edited_record_requires_no_updated_at(self):
        payload = {**MAINTENANCE, "performedDate": "2026-10-02"}

        self.api.lambda_handler(self.event(payload=payload), None)

        delete = self.transactions.transact_write_items.call_args.kwargs[
            "TransactItems"
        ][1]["Delete"]
        self.assertIn(
            "attribute_not_exists(updatedAt)",
            delete["ConditionExpression"],
        )

    def test_stale_expected_updated_at_returns_409(self):
        payload = {
            **MAINTENANCE,
            "expectedUpdatedAt": "2026-10-02T09:00:00+00:00",
        }

        result = self.api.lambda_handler(
            self.event(payload=payload),
            None,
        )

        self.assertEqual(result["statusCode"], 409)
        self.table.put_item.assert_not_called()
        self.transactions.transact_write_items.assert_not_called()

    def test_current_expected_updated_at_is_accepted(self):
        payload = {**MAINTENANCE, "expectedUpdatedAt": None}

        result = self.api.lambda_handler(
            self.event(payload=payload),
            None,
        )

        self.assertEqual(result["statusCode"], 200)

    def test_concurrent_change_returns_409(self):
        class ConditionalCheckFailed(Exception):
            pass

        exceptions = self.table.meta.client.exceptions
        exceptions.ConditionalCheckFailedException = ConditionalCheckFailed
        self.table.put_item.side_effect = ConditionalCheckFailed()

        result = self.api.lambda_handler(self.event(), None)

        self.assertEqual(result["statusCode"], 409)

    def test_technician_cannot_update_another_users_record(self):
        result = self.api.lambda_handler(
            self.event(group="Technician", sub="technician-2"),
            None,
        )

        self.assertEqual(result["statusCode"], 403)
        self.table.put_item.assert_not_called()

    def test_other_department_technician_cannot_update(self):
        result = self.api.lambda_handler(
            self.event(
                group="Technician",
                sub="technician-1",
                department="Finance",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 403)
        self.table.put_item.assert_not_called()

    def test_read_only_roles_cannot_update(self):
        for group in ("Employee", "Manager", "Auditor"):
            result = self.api.lambda_handler(
                self.event(group=group, sub="employee-1"),
                None,
            )

            self.assertEqual(result["statusCode"], 403)

        self.table.put_item.assert_not_called()

    def test_invalid_update_returns_400(self):
        result = self.api.lambda_handler(
            self.event(payload={"maintenanceType": "Unknown"}),
            None,
        )

        self.assertEqual(result["statusCode"], 400)
        self.table.put_item.assert_not_called()

    def test_missing_record_returns_404(self):
        self.table.query.return_value = {"Items": []}

        for method in ("PUT", "DELETE"):
            result = self.api.lambda_handler(
                self.event(method=method),
                None,
            )

            self.assertEqual(result["statusCode"], 404)

        self.table.put_item.assert_not_called()
        self.table.delete_item.assert_not_called()

    def test_administrator_can_delete_record(self):
        result = self.api.lambda_handler(
            self.event(method="DELETE"),
            None,
        )

        self.assertEqual(result["statusCode"], 200)
        self.table.delete_item.assert_called_once()
        self.assertEqual(
            self.table.delete_item.call_args.kwargs["Key"],
            {"PK": RECORD["PK"], "SK": RECORD["SK"]},
        )

    def test_technician_cannot_delete_record(self):
        result = self.api.lambda_handler(
            self.event(
                method="DELETE",
                group="Technician",
                sub="technician-1",
            ),
            None,
        )

        self.assertEqual(result["statusCode"], 403)
        self.table.delete_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()
