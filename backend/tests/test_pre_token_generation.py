import copy
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from pre_token_generation.app import lambda_handler


def event_for(username, okta_groups=None, cognito_groups=None):
    attributes = {"sub": "test-sub"}

    if okta_groups is not None:
        attributes["custom:oktaGroups"] = okta_groups

    return {
        "version": "1",
        "triggerSource": "TokenGeneration_HostedAuth",
        "userName": username,
        "request": {
            "userAttributes": attributes,
            "groupConfiguration": {
                "groupsToOverride": cognito_groups or [],
                "iamRolesToOverride": [],
                "preferredRole": None,
            },
        },
        "response": {},
    }


class PreTokenGenerationTests(unittest.TestCase):
    def test_maps_approved_okta_groups(self):
        event = event_for(
            "Okta_00u123",
            '["AWS-Asset-Administrator","AWS-Asset-Employee"]',
            [
                "us-east-1_IflJ7FznK_Okta",
                "Auditor",
            ],
        )

        result = lambda_handler(copy.deepcopy(event), None)

        groups = result["response"]["claimsOverrideDetails"][
            "groupOverrideDetails"
        ]["groupsToOverride"]

        self.assertEqual(
            groups,
            [
                "Administrator",
                "Employee",
                "us-east-1_IflJ7FznK_Okta",
            ],
        )

    def test_ignores_unknown_okta_groups(self):
        event = event_for(
            "Okta_00u123",
            '["AWS-Asset-Employee","AWS-Asset-Superuser"]',
            ["us-east-1_IflJ7FznK_Okta"],
        )

        result = lambda_handler(event, None)

        groups = result["response"]["claimsOverrideDetails"][
            "groupOverrideDetails"
        ]["groupsToOverride"]

        self.assertEqual(
            groups,
            [
                "Employee",
                "us-east-1_IflJ7FznK_Okta",
            ],
        )

    def test_blocks_administrator_auditor_conflict(self):
        event = event_for(
            "Okta_00u123",
            '["AWS-Asset-Administrator","AWS-Asset-Auditor"]',
            ["us-east-1_IflJ7FznK_Okta"],
        )

        with self.assertRaises(ValueError):
            lambda_handler(event, None)

    def test_preserves_native_cognito_groups(self):
        event = event_for(
            "native-user-id",
            cognito_groups=["Manager"],
        )

        result = lambda_handler(event, None)

        groups = result["response"]["claimsOverrideDetails"][
            "groupOverrideDetails"
        ]["groupsToOverride"]

        self.assertEqual(groups, ["Manager"])

    def test_handles_url_encoded_group_value(self):
        event = event_for(
            "Okta_00u123",
            "%5B%22AWS-Asset-Technician%22%5D",
            ["us-east-1_IflJ7FznK_Okta"],
        )

        result = lambda_handler(event, None)

        groups = result["response"]["claimsOverrideDetails"][
            "groupOverrideDetails"
        ]["groupsToOverride"]

        self.assertIn("Technician", groups)


if __name__ == "__main__":
    unittest.main()
