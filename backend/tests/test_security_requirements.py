"""Security acceptance tests for the Week 4 milestone."""

import json
import pathlib
import sys
import unittest

from unittest import mock

TEST_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))

from test_unique_asset_tags import _load_api  # noqa: E402


ASSET = {
    "PK": "ASSET#AST-SECURITY",
    "SK": "METADATA",
    "assetId": "AST-SECURITY",
    "assetTag": "SEC-001",
    "category": "Laptop",
    "description": "Security test laptop",
    "purchaseDate": "2026-01-01",
    "inServiceDate": "2026-01-01",
    "purchaseValue": "1500.00",
    "salvageValue": "100.00",
    "usefulLifeMonths": 48,
    "department": "IT",
    "condition": "Good",
    "status": "Available",
}


def authenticated_event(
    method,
    resource,
    *,
    asset_id=None,
    group="Administrator",
    sub="security-user",
    body=None,
):
    event = {
        "httpMethod": method,
        "resource": resource,
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
    }

    if asset_id:
        event["pathParameters"] = {
            "assetId": asset_id,
        }

    if body is not None:
        event["body"] = body

    return event


def machine_event(
    method,
    resource,
    *,
    scope="",
    asset_id=None,
    body=None,
):
    client_id = "machine-client-123"

    event = {
        "httpMethod": method,
        "resource": resource,
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": client_id,
                    "client_id": client_id,
                    "token_use": "access",
                    "scope": scope,
                }
            }
        },
    }

    if asset_id:
        event["pathParameters"] = {
            "assetId": asset_id,
        }

    if body is not None:
        event["body"] = body

    return event


class SecurityRequirementTests(unittest.TestCase):
    def setUp(self):
                (
            self.api,
            self.table,
            self.transactions,
            self.s3,
        ) = _load_api()

    def response_body(self, result):
        return json.loads(result["body"])

    def test_request_without_authenticated_identity_returns_401(self):
        event = {
            "httpMethod": "GET",
            "resource": "/assets",
            "requestContext": {},
        }

        result = self.api.lambda_handler(event, None)
        body = self.response_body(result)

        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(body["error"], "Unauthorized")
        self.table.scan.assert_not_called()
        self.table.query.assert_not_called()

    def test_auditor_cannot_modify_asset(self):
        self.table.get_item.return_value = {
            "Item": ASSET,
        }

        event = authenticated_event(
            "PUT",
            "/assets/{assetId}",
            asset_id="AST-SECURITY",
            group="Auditor",
            sub="auditor-1",
            body=json.dumps({
                "condition": "Poor",
            }),
        )

    def test_machine_read_scope_allows_asset_list(self):
        self.table.scan.return_value = {"Items": []}

        event = machine_event(
            "GET",
            "/assets",
            scope="asset-tracker/assets.read",
        )

        result = self.api.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        self.table.scan.assert_called_once()

    def test_machine_without_read_scope_is_rejected(self):
        event = machine_event(
            "GET",
            "/assets",
            scope="asset-tracker/assets.write",
        )

        result = self.api.lambda_handler(event, None)
        body = self.response_body(result)

        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(body["error"], "InsufficientScope")
        self.table.scan.assert_not_called()

    def test_machine_write_scope_allows_asset_create(self):
        event = machine_event(
            "POST",
            "/assets",
            scope="asset-tracker/assets.write",
            body="{}",
        )
        expected = self.api.response(
            201,
            {"message": "created"},
        )

        with mock.patch.object(
            self.api,
            "_create",
            return_value=expected,
        ) as create:
            result = self.api.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 201)
        create.assert_called_once()
        self.assertEqual(
            create.call_args.args[2],
            {"Administrator"},
        )

    def test_machine_cannot_access_maintenance_routes(self):
        event = machine_event(
            "GET",
            "/assets/{assetId}/maintenance",
            asset_id="AST-SECURITY",
            scope=(
                "asset-tracker/assets.read "
                "asset-tracker/assets.write"
            ),
        )

        result = self.api.lambda_handler(event, None)
        body = self.response_body(result)

        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(body["error"], "Forbidden")
        self.table.query.assert_not_called()
        self.transactions.transact_write_items.assert_not_called()

    def test_malformed_json_is_rejected(self):
        event = authenticated_event(
            "POST",
            "/assets",
            body='{"assetTag": "SEC-001", invalid}',
        )

        result = self.api.lambda_handler(event, None)
        body = self.response_body(result)

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(body["error"], "ValidationError")
        self.table.put_item.assert_not_called()
        self.transactions.transact_write_items.assert_not_called()

    def test_unsupported_method_is_rejected(self):
        event = authenticated_event(
            "DELETE",
            "/assets/{assetId}",
            asset_id="AST-SECURITY",
        )

        result = self.api.lambda_handler(event, None)
        body = self.response_body(result)

        self.assertEqual(result["statusCode"], 405)
        self.assertEqual(body["error"], "MethodNotAllowed")

    def test_employee_cannot_read_another_users_asset(self):
        protected_asset = {
            **ASSET,
            "assignedUserId": "employee-owner",
        }
        self.table.get_item.return_value = {
            "Item": protected_asset,
        }

        event = authenticated_event(
            "GET",
            "/assets/{assetId}",
            asset_id="AST-SECURITY",
            group="Employee",
            sub="different-employee",
        )

        result = self.api.lambda_handler(event, None)
        body = self.response_body(result)

        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(body["error"], "Forbidden")


if __name__ == "__main__":
    unittest.main()
