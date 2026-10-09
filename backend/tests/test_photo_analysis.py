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


class _ClientError(Exception):
    def __init__(self, response):
        self.response = response


def load_handler():
    s3 = MagicMock()
    bedrock = MagicMock()
    table = MagicMock()
    dynamodb_resource = MagicMock()
    dynamodb_resource.Table.return_value = table

    def client(service_name, *args, **kwargs):
        if service_name == "s3":
            return s3
        if service_name == "bedrock-runtime":
            return bedrock
        raise ValueError(f"Unexpected boto3 client: {service_name}")

    boto3 = types.ModuleType("boto3")
    boto3.client = MagicMock(side_effect=client)
    boto3.resource = MagicMock(return_value=dynamodb_resource)

    botocore = types.ModuleType("botocore")
    exceptions = types.ModuleType("botocore.exceptions")
    exceptions.ClientError = _ClientError

    modules = {
        "boto3": boto3,
        "botocore": botocore,
        "botocore.exceptions": exceptions,
    }

    spec = importlib.util.spec_from_file_location("photo_analysis_under_test", API_DIR / "photo_analysis.py")
    module = importlib.util.module_from_spec(spec)
    env = {"ASSET_TABLE_NAME": "asset-table", "ASSET_PHOTO_BUCKET": "private-photos"}
    with patch.dict(sys.modules, modules), patch.dict(os.environ, env):
        spec.loader.exec_module(module)
    return module, {"s3": s3, "bedrock": bedrock, "table": table}


VALID_RESPONSE = {
    "category": "Laptop",
    "manufacturer": "Dell",
    "model": "Latitude",
    "description": "Black laptop with an integrated keyboard.",
    "condition": "Good",
    "usefulLifeMonths": 48,
    "estimatedValueUsd": 650,
    "estimatedProductionDate": None,
    "maintenanceCategory": "End-User Computing",
}


class ValidateSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.module, _ = load_handler()

    def test_valid_response_is_returned_as_is(self):
        suggestion = self.module.validate_suggestion(json.dumps(VALID_RESPONSE))
        self.assertEqual(suggestion["category"], "Laptop")
        self.assertEqual(suggestion["manufacturer"], "Dell")
        self.assertEqual(suggestion["model"], "Latitude")
        self.assertEqual(suggestion["estimatedValueUsd"], 650)

    def test_strips_markdown_code_fences(self):
        raw = "```json\n" + json.dumps(VALID_RESPONSE) + "\n```"
        suggestion = self.module.validate_suggestion(raw)
        self.assertEqual(suggestion["category"], "Laptop")

    def test_missing_manufacturer_and_model_default_to_none(self):
        payload = dict(VALID_RESPONSE)
        del payload["manufacturer"]
        del payload["model"]
        suggestion = self.module.validate_suggestion(json.dumps(payload))
        self.assertIsNone(suggestion["manufacturer"])
        self.assertIsNone(suggestion["model"])

    def test_blank_manufacturer_becomes_none(self):
        payload = {**VALID_RESPONSE, "manufacturer": "   "}
        suggestion = self.module.validate_suggestion(json.dumps(payload))
        self.assertIsNone(suggestion["manufacturer"])

    def test_non_object_response_rejected(self):
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps([1, 2, 3]))

    def test_non_string_manufacturer_rejected(self):
        payload = {**VALID_RESPONSE, "manufacturer": 123}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_oversized_manufacturer_rejected(self):
        payload = {**VALID_RESPONSE, "manufacturer": "x" * 101}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_oversized_field_rejected(self):
        payload = {**VALID_RESPONSE, "description": "x" * 401}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_invalid_condition_rejected(self):
        payload = {**VALID_RESPONSE, "condition": "Excellent"}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_non_integer_useful_life_rejected(self):
        payload = {**VALID_RESPONSE, "usefulLifeMonths": "48"}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_out_of_range_useful_life_rejected(self):
        payload = {**VALID_RESPONSE, "usefulLifeMonths": 0}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_prompt_does_not_show_null_for_required_estimates(self):
        self.assertNotIn('"usefulLifeMonths": null', self.module.PROMPT)
        self.assertNotIn('"estimatedValueUsd": null', self.module.PROMPT)

    def test_null_useful_life_and_value_rejected(self):
        for field in ("usefulLifeMonths", "estimatedValueUsd"):
            payload = {**VALID_RESPONSE, field: None}
            with self.assertRaises(ValueError):
                self.module.validate_suggestion(json.dumps(payload))

    def test_empty_category_rejected(self):
        payload = {**VALID_RESPONSE, "category": ""}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))

    def test_empty_description_rejected(self):
        payload = {**VALID_RESPONSE, "description": ""}
        with self.assertRaises(ValueError):
            self.module.validate_suggestion(json.dumps(payload))


class ApiHandlerAccessControlTests(unittest.TestCase):
    def setUp(self):
        self.module, self.mocks = load_handler()

    def _event(self, sub, groups, key):
        claims = {"cognito:groups": groups}
        if sub is not None:
            claims["sub"] = sub
        return {
            "requestContext": {"authorizer": {"claims": claims}},
            "queryStringParameters": {"key": key},
        }

    def test_missing_subject_returns_401(self):
        event = self._event(None, "[Administrator]", "pending/user-1/" + "a" * 32 + ".jpg")
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 401)

    def test_invalid_key_format_returns_400(self):
        event = self._event("user-1", "[Administrator]", "not-a-valid-key")
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 400)
        self.mocks["table"].get_item.assert_not_called()

    def test_administrator_can_view_any_photo_analysis(self):
        self.mocks["table"].get_item.return_value = {
            "Item": {"status": "Ready", "suggestion": {"category": "Laptop"}}
        }
        key = "pending/someone-else/" + "0" * 32 + ".jpg"
        event = self._event("admin-1", "[Administrator]", key)
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["status"], "Ready")

    def test_owning_technician_can_view_own_photo_analysis(self):
        key = "pending/tech-1/" + "a" * 32 + ".png"
        self.mocks["table"].get_item.return_value = {"Item": {"status": "Processing"}}
        event = self._event("tech-1", "[Technician]", key)
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 200)

    def test_non_owning_technician_is_denied(self):
        key = "pending/tech-1/" + "b" * 32 + ".jpg"
        event = self._event("tech-2", "[Technician]", key)
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 403)
        self.mocks["table"].get_item.assert_not_called()

    def test_employee_is_denied_regardless_of_ownership(self):
        key = "pending/emp-1/" + "c" * 32 + ".jpg"
        event = self._event("emp-1", "[Employee]", key)
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 403)

    def test_no_analysis_item_yet_returns_processing(self):
        self.mocks["table"].get_item.return_value = {}
        key = "pending/admin-1/" + "d" * 32 + ".png"
        event = self._event("admin-1", "[Administrator]", key)
        result = self.module.api_handler(event, None)
        self.assertEqual(result["statusCode"], 202)
        self.assertEqual(json.loads(result["body"])["status"], "Processing")


if __name__ == "__main__":
    unittest.main()
