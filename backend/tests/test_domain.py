import pathlib
import sys
import unittest


sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "asset_api"))

from domain import (  # noqa: E402
    ValidationError,
    can_create,
    can_read,
    parse_groups,
    validate_asset,
    validate_create_permissions,
    validate_update_permissions,
)


VALID_ASSET = {
    "assetTag": "TAG-0001",
    "category": "Laptop",
    "description": "Business laptop",
    "purchaseDate": "2026-09-01",
    "inServiceDate": "2026-09-01",
    "purchaseValue": "1500.00",
    "salvageValue": "100.00",
    "usefulLifeMonths": 48,
    "condition": "Good",
    "status": "Assigned",
}


class DomainTests(unittest.TestCase):
    def test_valid_asset(self):
        validate_asset(VALID_ASSET)

    def test_missing_required_field(self):
        asset = {**VALID_ASSET}
        del asset["description"]
        with self.assertRaises(ValidationError) as error:
            validate_asset(asset)
        self.assertIn("description", error.exception.fields)

    def test_salvage_cannot_exceed_purchase_value(self):
        asset = {**VALID_ASSET, "salvageValue": "2000.00"}
        with self.assertRaises(ValidationError):
            validate_asset(asset)

    def test_useful_life_must_be_positive_integer(self):
        with self.assertRaises(ValidationError):
            validate_asset({**VALID_ASSET, "usefulLifeMonths": 0})

    def test_groups_are_parsed_from_api_gateway_claim(self):
        self.assertEqual(parse_groups("[Technician, Administrator]"), {"Technician", "Administrator"})

    def test_employee_can_only_read_assigned_asset(self):
        groups = {"Employee"}
        self.assertTrue(can_read(groups, {"sub": "user-1"}, {"assignedUserId": "user-1"}))
        self.assertFalse(can_read(groups, {"sub": "user-1"}, {"assignedUserId": "user-2"}))

    def test_manager_can_only_read_department_asset(self):
        groups = {"Manager"}
        claims = {"sub": "manager-1", "custom:department": "IT"}
        self.assertTrue(can_read(groups, claims, {"department": "IT"}))
        self.assertFalse(can_read(groups, claims, {"department": "Finance"}))

    def test_auditor_is_read_only(self):
        self.assertTrue(can_read({"Auditor"}, {"sub": "a"}, {}))
        self.assertFalse(can_create({"Auditor"}))
        self.assertFalse(validate_update_permissions({"Auditor"}, {"condition"}))

    def test_technician_update_is_field_limited(self):
        self.assertTrue(validate_update_permissions({"Technician"}, {"condition", "status"}))
        self.assertFalse(validate_update_permissions({"Technician"}, {"purchaseValue"}))

    def test_technician_cannot_set_assignment_fields_on_create(self):
        self.assertFalse(validate_create_permissions({"Technician"}, {**VALID_ASSET, "assignedUserId": "user-1"}))
        self.assertFalse(validate_create_permissions({"Technician"}, {**VALID_ASSET, "department": "IT"}))
        self.assertTrue(validate_create_permissions({"Technician"}, VALID_ASSET))

    def test_administrator_can_set_assignment_fields_on_create(self):
        self.assertTrue(validate_create_permissions({"Administrator"}, {**VALID_ASSET, "assignedUserId": "user-1", "department": "IT"}))


if __name__ == "__main__":
    unittest.main()

