"""Tests the legacy-page check and the atomic tag reservation in the API."""

import importlib.util
import json
import os
import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


API_DIR = pathlib.Path(__file__).parents[1] / "asset_api"
sys.path.insert(0, str(API_DIR))


class _Attr:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return self


class _Serializer:
    def serialize(self, value):
        return {"S": str(value)}


class _ClientError(Exception):
    def __init__(self, response):
        self.response = response


def _load_api():
    table = MagicMock(name="table")
    table.name = "test-assets"
    transactions = MagicMock(name="transactions")
    boto3 = types.ModuleType("boto3")
    boto3.resource = MagicMock(return_value=types.SimpleNamespace(Table=lambda name: table))
    boto3.client = MagicMock(return_value=transactions)
    dynamodb = types.ModuleType("boto3.dynamodb")
    conditions = types.ModuleType("boto3.dynamodb.conditions")
    conditions.Attr = _Attr
    types_module = types.ModuleType("boto3.dynamodb.types")
    types_module.TypeSerializer = _Serializer
    botocore = types.ModuleType("botocore")
    exceptions = types.ModuleType("botocore.exceptions")
    exceptions.ClientError = _ClientError
    modules = {
        "boto3": boto3,
        "boto3.dynamodb": dynamodb,
        "boto3.dynamodb.conditions": conditions,
        "boto3.dynamodb.types": types_module,
        "botocore": botocore,
        "botocore.exceptions": exceptions,
    }
    spec = importlib.util.spec_from_file_location("asset_api_under_test", API_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules), patch.dict(os.environ, {"ASSET_TABLE_NAME": "test-assets"}):
        spec.loader.exec_module(module)
    return module, table, transactions


ASSET = {
    "assetTag": "TAG-0001", "category": "Laptop", "description": "Business laptop",
    "purchaseDate": "2026-09-01", "inServiceDate": "2026-09-01",
    "purchaseValue": "1500.00", "salvageValue": "100.00",
    "usefulLifeMonths": 48, "condition": "Good", "status": "Available",
}


class UniqueTagTests(unittest.TestCase):
    def setUp(self):
        self.api, self.table, self.transactions = _load_api()
        self.event = {"body": json.dumps(ASSET)}

    def test_duplicate_on_later_scan_page_is_rejected(self):
        self.table.scan.side_effect = [
            {"Items": [], "LastEvaluatedKey": {"PK": "ASSET#OTHER", "SK": "METADATA"}},
            {"Items": [{"assetId": "AST-EXISTING", "assetTag": "tag-0001"}]},
        ]
        result = self.api._create(self.event, {"sub": "admin"}, {"Administrator"})
        self.assertEqual(result["statusCode"], 409)
        self.transactions.transact_write_items.assert_not_called()
        self.assertIn("ExclusiveStartKey", self.table.scan.call_args_list[1].kwargs)

    def test_create_reserves_tag_and_asset_in_one_transaction(self):
        self.table.scan.return_value = {"Items": []}
        result = self.api._create(self.event, {"sub": "admin"}, {"Administrator"})
        self.assertEqual(result["statusCode"], 201)
        writes = self.transactions.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0]["Put"]["Item"]["PK"], {"S": "ASSET_TAG#TAG-0001"})
        self.assertEqual(writes[0]["Put"]["ConditionExpression"], "attribute_not_exists(PK)")
        self.assertEqual(writes[1]["Put"]["ConditionExpression"], "attribute_not_exists(PK)")

    def test_tag_rename_checks_legacy_assets(self):
        existing = {**ASSET, "assetId": "AST-OWN", "PK": "ASSET#AST-OWN", "SK": "METADATA"}
        self.table.get_item.return_value = {"Item": existing}
        self.table.scan.return_value = {"Items": [{"assetId": "AST-OTHER", "assetTag": "TAG-0002"}]}
        event = {"body": json.dumps({"assetTag": "TAG-0002"})}
        result = self.api._update(event, "AST-OWN", {"sub": "admin"}, {"Administrator"})
        self.assertEqual(result["statusCode"], 409)
        self.transactions.transact_write_items.assert_not_called()

    def test_tag_rename_moves_reservation_with_asset(self):
        existing = {**ASSET, "assetId": "AST-OWN", "PK": "ASSET#AST-OWN", "SK": "METADATA"}
        self.table.get_item.side_effect = [
            {"Item": existing},
            {"Item": {"PK": "ASSET_TAG#TAG-0001", "SK": "UNIQUE", "assetId": "AST-OWN"}},
        ]
        self.table.scan.return_value = {"Items": []}
        event = {"body": json.dumps({"assetTag": "TAG-0002"})}
        result = self.api._update(event, "AST-OWN", {"sub": "admin"}, {"Administrator"})
        self.assertEqual(result["statusCode"], 200)
        writes = self.transactions.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(writes), 3)
        self.assertEqual(writes[0]["Put"]["Item"]["PK"], {"S": "ASSET_TAG#TAG-0002"})
        self.assertEqual(writes[2]["Delete"]["Key"]["PK"], {"S": "ASSET_TAG#TAG-0001"})

    def test_concurrent_tag_reservation_conflict_returns_409(self):
        self.table.scan.return_value = {"Items": []}
        self.transactions.transact_write_items.side_effect = _ClientError({
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}],
        })
        result = self.api._create(self.event, {"sub": "admin"}, {"Administrator"})
        self.assertEqual(result["statusCode"], 409)


if __name__ == "__main__":
    unittest.main()
