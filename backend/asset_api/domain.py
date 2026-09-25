from datetime import date
from decimal import Decimal, InvalidOperation


READ_GROUPS = {"Employee", "Technician", "Manager", "Administrator", "Auditor"}
CREATE_GROUPS = {"Technician", "Administrator"}
FULL_UPDATE_GROUPS = {"Administrator"}
TECHNICIAN_UPDATE_FIELDS = {
    "condition",
    "status",
    "description",
    "location",
    "lastCleaningDate",
    "lastMaintenanceDate",
    "imageKey",
}
CREATE_RESTRICTED_FIELDS = {"assignedUserId", "department"}

REQUIRED_FIELDS = {
    "assetTag",
    "category",
    "description",
    "purchaseDate",
    "inServiceDate",
    "purchaseValue",
    "salvageValue",
    "usefulLifeMonths",
    "condition",
    "status",
}

VALID_STATUSES = {
    "Available",
    "Assigned",
    "Checked Out",
    "In Maintenance",
    "Damaged",
    "Lost",
    "Stolen",
    "Retired",
}


class ValidationError(ValueError):
    def __init__(self, message, fields=None):
        super().__init__(message)
        self.fields = fields or []


def parse_groups(raw_groups):
    if not raw_groups:
        return set()
    if isinstance(raw_groups, list):
        return set(raw_groups)
    return {group.strip().strip("[]'") for group in str(raw_groups).split(",") if group.strip()}


def validate_asset(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    if "assetTag" in payload and (not isinstance(payload["assetTag"], str) or not payload["assetTag"].strip()):
        raise ValidationError("Asset tag must contain a value.", ["assetTag"])

    if not partial:
        missing = sorted(field for field in REQUIRED_FIELDS if payload.get(field) in (None, ""))
        if missing:
            raise ValidationError("Required asset information is missing.", missing)

    if "status" in payload and payload["status"] not in VALID_STATUSES:
        raise ValidationError("Invalid asset status.", ["status"])

    for field in ("purchaseDate", "inServiceDate"):
        if field in payload:
            try:
                date.fromisoformat(payload[field])
            except (TypeError, ValueError):
                raise ValidationError(f"{field} must use YYYY-MM-DD.", [field])

    money_fields = ("purchaseValue", "salvageValue")
    values = {}
    for field in money_fields:
        if field in payload:
            try:
                value = Decimal(str(payload[field]))
            except (InvalidOperation, TypeError, ValueError):
                raise ValidationError(f"{field} must be a valid financial value.", [field])
            if not value.is_finite() or value < 0:
                raise ValidationError(f"{field} must be finite and non-negative.", [field])
            values[field] = value

    if "purchaseValue" in values and "salvageValue" in values:
        if values["salvageValue"] > values["purchaseValue"]:
            raise ValidationError("Salvage value cannot exceed purchase value.", money_fields)

    if "usefulLifeMonths" in payload:
        value = payload["usefulLifeMonths"]
        if type(value) is not int or value <= 0:
            raise ValidationError("Useful life must be a positive integer.", ["usefulLifeMonths"])


def can_read(groups, claims, asset):
    if not groups.intersection(READ_GROUPS):
        return False
    if groups.intersection({"Administrator", "Auditor"}):
        return True

    if groups.intersection({"Manager", "Technician"}):
        department = claims.get("custom:department")
        return bool(department and department == asset.get("department"))

    if "Employee" in groups:
        return claims.get("sub") == asset.get("assignedUserId")

    return False


def can_create(groups):
    return bool(groups.intersection(CREATE_GROUPS))


def validate_update_permissions(groups, changed_fields):
    if groups.intersection(FULL_UPDATE_GROUPS):
        return True
    if "Technician" in groups:
        return set(changed_fields).issubset(TECHNICIAN_UPDATE_FIELDS)
    return False


def validate_create_permissions(groups, payload):
    if groups.intersection(FULL_UPDATE_GROUPS):
        return True
    restricted_present = {field for field in CREATE_RESTRICTED_FIELDS if payload.get(field)}
    return not restricted_present
