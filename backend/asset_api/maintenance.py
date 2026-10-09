from datetime import date
from decimal import Decimal, InvalidOperation


class MaintenanceValidationError(ValueError):
    def __init__(self, message, fields=None):
        super().__init__(message)
        self.fields = fields or []


MAINTENANCE_TYPES = {
    "Preventive",
    "Corrective",
    "Inspection",
    "Cleaning",
    "Repair",
}

CONDITIONS = {
    "Excellent",
    "Good",
    "Fair",
    "Poor",
    "Damaged",
}


def _required_string(payload, field):
    value = payload.get(field)

    if not isinstance(value, str) or not value.strip():
        raise MaintenanceValidationError(
            f"{field} is required.",
            [field],
        )

    return value.strip()


def _optional_date(payload, field):
    value = payload.get(field)

    if value in (None, ""):
        return None

    if not isinstance(value, str):
        raise MaintenanceValidationError(
            f"{field} must use YYYY-MM-DD format.",
            [field],
        )

    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise MaintenanceValidationError(
            f"{field} must use YYYY-MM-DD format.",
            [field],
        ) from exc


def _cost(payload):
    value = payload.get("cost", 0)

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MaintenanceValidationError(
            "cost must be a valid number.",
            ["cost"],
        ) from exc

    if not amount.is_finite():
        raise MaintenanceValidationError(
            "cost must be a valid number.",
            ["cost"],
        )

    if amount < 0:
        raise MaintenanceValidationError(
            "cost cannot be negative.",
            ["cost"],
        )

    return amount.quantize(Decimal("0.01"))


def validate_maintenance(payload):
    if not isinstance(payload, dict):
        raise MaintenanceValidationError(
            "Maintenance information must be a JSON object."
        )

    maintenance_type = _required_string(payload, "maintenanceType")

    if maintenance_type not in MAINTENANCE_TYPES:
        raise MaintenanceValidationError(
            "maintenanceType is not supported.",
            ["maintenanceType"],
        )

    description = _required_string(payload, "description")
    performed_date = _optional_date(payload, "performedDate")

    if not performed_date:
        raise MaintenanceValidationError(
            "performedDate is required.",
            ["performedDate"],
        )

    condition_after = payload.get("conditionAfter")

    if condition_after not in (None, ""):
        if condition_after not in CONDITIONS:
            raise MaintenanceValidationError(
                "conditionAfter is not supported.",
                ["conditionAfter"],
            )
    else:
        condition_after = None

    return {
        "maintenanceType": maintenance_type,
        "description": description,
        "performedDate": performed_date,
        "conditionAfter": condition_after,
        "nextMaintenanceDate": _optional_date(
            payload,
            "nextMaintenanceDate",
        ),
        "cost": _cost(payload),
    }
