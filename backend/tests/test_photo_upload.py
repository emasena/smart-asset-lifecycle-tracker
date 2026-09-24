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


def load_handler():
    s3 = MagicMock()
    s3.generate_presigned_post.return_value = {"url": "https://s3.example/upload", "fields": {"key": "signed"}}
    boto3 = types.ModuleType("boto3")
    boto3.client = MagicMock(return_value=s3)
    spec = importlib.util.spec_from_file_location("photo_upload_under_test", API_DIR / "photo_upload.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"boto3": boto3}), patch.dict(os.environ, {"ASSET_PHOTO_BUCKET": "private-photos"}):
        spec.loader.exec_module(module)
    return module, s3


class PhotoUploadTests(unittest.TestCase):
    def setUp(self):
        self.api, self.s3 = load_handler()
        self.event = {
            "requestContext": {"authorizer": {"claims": {
                "sub": "user-123", "cognito:groups": "[Technician]", "custom:department": "IT",
            }}},
            "body": json.dumps({"contentType": "image/png"}),
        }

    def test_technician_receives_short_lived_size_limited_form(self):
        response = self.api.lambda_handler(self.event, None)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(body["key"].startswith("pending/user-123/"))
        self.assertTrue(body["key"].endswith(".png"))
        self.s3.generate_presigned_post.assert_called_once_with(
            Bucket="private-photos", Key=body["key"],
            Fields={"Content-Type": "image/png"},
            Conditions=[{"Content-Type": "image/png"}, ["content-length-range", 1, 3_750_000]],
            ExpiresIn=300,
        )

    def test_employee_cannot_get_upload_form(self):
        self.event["requestContext"]["authorizer"]["claims"]["cognito:groups"] = "[Employee]"
        self.assertEqual(self.api.lambda_handler(self.event, None)["statusCode"], 403)
        self.s3.generate_presigned_post.assert_not_called()

    def test_technician_without_department_cannot_get_upload_form(self):
        del self.event["requestContext"]["authorizer"]["claims"]["custom:department"]
        self.assertEqual(self.api.lambda_handler(self.event, None)["statusCode"], 403)

    def test_unsupported_content_type_rejected(self):
        self.event["body"] = json.dumps({"contentType": "image/svg+xml"})
        self.assertEqual(self.api.lambda_handler(self.event, None)["statusCode"], 400)
        self.s3.generate_presigned_post.assert_not_called()

    def test_missing_claims_rejected(self):
        self.event["requestContext"]["authorizer"]["claims"] = {}
        self.assertEqual(self.api.lambda_handler(self.event, None)["statusCode"], 401)


if __name__ == "__main__":
    unittest.main()
