import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ASSET_API_DIR = Path(__file__).resolve().parents[1] / "asset_api"
sys.path.insert(0, str(ASSET_API_DIR))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("ASSET_TABLE_NAME", "test-assets")
os.environ.setdefault("ASSET_PHOTO_BUCKET", "private-photos")

try:
    import boto3  # noqa: F401
except ModuleNotFoundError:
    boto3_module = types.ModuleType("boto3")
    boto3_module.resource = MagicMock()
    boto3_module.client = MagicMock()
    sys.modules["boto3"] = boto3_module

    conditions_module = types.ModuleType("boto3.dynamodb.conditions")
    conditions_module.Attr = MagicMock
    sys.modules["boto3.dynamodb"] = types.ModuleType("boto3.dynamodb")
    sys.modules["boto3.dynamodb.conditions"] = conditions_module

    types_module = types.ModuleType("boto3.dynamodb.types")
    types_module.TypeSerializer = MagicMock
    sys.modules["boto3.dynamodb.types"] = types_module

    exceptions_module = types.ModuleType("botocore.exceptions")
    exceptions_module.ClientError = Exception
    sys.modules["botocore"] = types.ModuleType("botocore")
    sys.modules["botocore.exceptions"] = exceptions_module

import app  # noqa: E402


class AssetPhotoGalleryTests(unittest.TestCase):
    def setUp(self):
        self.table = MagicMock()
        self.s3 = MagicMock()
        self.s3.generate_presigned_url.return_value = "https://signed.example/photo"
        self.asset = {
            "PK": "ASSET#AST-1",
            "SK": "METADATA",
            "assetId": "AST-1",
            "assetTag": "TAG-1",
            "department": "IT",
            "assignedUserId": "employee-1",
            "imageKey": "pending/technician-1/photo.jpg",
        }
        self.analysis = {
            "PK": "PHOTO#pending/technician-1/photo.jpg",
            "SK": "ANALYSIS",
            "status": "Ready",
            "suggestion": {"category": "Laptop", "reviewStatus": "NeedsReview"},
        }

    def response_body(self, result):
        return json.loads(result["body"])

    def call_photo(self, claims, groups):
        with patch.object(app, "TABLE", self.table), patch.object(app, "S3", self.s3), patch.object(
            app, "PHOTO_BUCKET", "private-photos"
        ):
            return app._get_photo("AST-1", claims, groups)

    def test_administrator_receives_short_lived_private_photo_url(self):
        self.table.get_item.side_effect = [{"Item": self.asset}, {"Item": self.analysis}]

        result = self.call_photo({"sub": "admin-1"}, {"Administrator"})

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(self.response_body(result)["analysisStatus"], "Ready")
        self.s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "private-photos", "Key": self.asset["imageKey"]},
            ExpiresIn=300,
        )

    def test_manager_cannot_view_other_department_photo(self):
        self.table.get_item.return_value = {"Item": self.asset}

        result = self.call_photo(
            {"sub": "manager-1", "custom:department": "Finance"},
            {"Manager"},
        )

        self.assertEqual(result["statusCode"], 403)
        self.s3.generate_presigned_url.assert_not_called()

    def test_employee_can_view_only_assigned_asset_photo(self):
        self.table.get_item.side_effect = [{"Item": self.asset}, {"Item": self.analysis}]

        allowed = self.call_photo({"sub": "employee-1"}, {"Employee"})

        self.assertEqual(allowed["statusCode"], 200)

        self.table.reset_mock()
        self.s3.reset_mock()
        self.table.get_item.side_effect = None
        self.table.get_item.return_value = {"Item": self.asset}
        denied = self.call_photo({"sub": "employee-2"}, {"Employee"})

        self.assertEqual(denied["statusCode"], 403)
        self.s3.generate_presigned_url.assert_not_called()

    def test_asset_without_photo_returns_not_found(self):
        self.table.get_item.return_value = {"Item": {**self.asset, "imageKey": None}}

        result = self.call_photo({"sub": "admin-1"}, {"Administrator"})

        self.assertEqual(result["statusCode"], 404)
        self.s3.generate_presigned_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
