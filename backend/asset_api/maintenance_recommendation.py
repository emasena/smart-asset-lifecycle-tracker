from datetime import date, timedelta


CATEGORY_INTERVALS = {
    "Laptop": {
        "cleaningDays": 90,
        "maintenanceDays": 180,
    },
    "Mobile Phone": {
        "cleaningDays": 60,
        "maintenanceDays": 180,
    },
    "Printer": {
        "cleaningDays": 30,
        "maintenanceDays": 90,
    },
    "Network Equipment": {
        "cleaningDays": 90,
        "maintenanceDays": 180,
    },
    "Monitor": {
        "cleaningDays": 90,
        "maintenanceDays": 365,
    },
    "Projector": {
        "cleaningDays": 60,
        "maintenanceDays": 180,
    },
}

DEFAULT_INTERVALS = {
    "cleaningDays": 90,
    "maintenanceDays": 180,
}

CONDITION_MULTIPLIERS = {
    "Excellent": 1.25,
    "Good": 1.0,
    "Fair": 0.75,
    "Poor": 0.5,
    "Damaged": 0.25,
}


class MaintenanceRecommendationError(ValueError):
    pass


def _parse_date(value, field):
    if not isinstance(value, str) or not value:
        raise MaintenanceRecommendationError(
            f"{field} must use YYYY-MM-DD format."
        )

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MaintenanceRecommendationError(
            f"{field} must use YYYY-MM-DD format."
        ) from exc


def _latest_maintenance(history):
    valid = [
        record
        for record in history
        if isinstance(record.get("performedDate"), str)
    ]

    if not valid:
        return None

    return max(
        valid,
        key=lambda record: record["performedDate"],
    )


def _adjusted_days(days, condition):
    multiplier = CONDITION_MULTIPLIERS.get(condition, 1.0)
    return max(1, round(days * multiplier))


def calculate_maintenance_recommendation(
    asset,
    maintenance_history=None,
    as_of_date=None,
):
    maintenance_history = maintenance_history or []

    today = (
        _parse_date(as_of_date, "asOfDate")
        if as_of_date
        else date.today()
    )

    category = asset.get("category", "")
    latest = _latest_maintenance(maintenance_history)

    condition = (
        latest.get("conditionAfter")
        if latest and latest.get("conditionAfter")
        else asset.get("condition", "Good")
    )

    intervals = CATEGORY_INTERVALS.get(
        category,
        DEFAULT_INTERVALS,
    )

    if latest:
        base_date = _parse_date(
            latest["performedDate"],
            "performedDate",
        )
    else:
        service_date = (
            asset.get("inServiceDate")
            or asset.get("purchaseDate")
        )

        if not service_date:
            raise MaintenanceRecommendationError(
                "Asset requires an inServiceDate or purchaseDate."
            )

        base_date = _parse_date(
            service_date,
            "inServiceDate",
        )

    cleaning_days = _adjusted_days(
        intervals["cleaningDays"],
        condition,
    )
    maintenance_days = _adjusted_days(
        intervals["maintenanceDays"],
        condition,
    )

    recommended_cleaning_date = (
        base_date + timedelta(days=cleaning_days)
    )
    recommended_maintenance_date = (
        base_date + timedelta(days=maintenance_days)
    )

    if latest and latest.get("nextMaintenanceDate"):
        recommended_maintenance_date = _parse_date(
            latest["nextMaintenanceDate"],
            "nextMaintenanceDate",
        )

    days_until = (
        recommended_maintenance_date - today
    ).days

    if days_until < 0:
        status = "Overdue"
    elif days_until <= 30:
        status = "DueSoon"
    else:
        status = "Current"

    if condition == "Damaged":
        priority = "Critical"
        recommendation = (
            "Remove the asset from service and perform an "
            "immediate safety and replacement assessment."
        )
    elif condition == "Poor":
        priority = "High"
        recommendation = (
            "Schedule corrective maintenance and evaluate "
            "whether replacement is more cost-effective."
        )
    elif status == "Overdue":
        priority = "High"
        recommendation = (
            "Complete the overdue maintenance inspection "
            "as soon as possible."
        )
    elif status == "DueSoon":
        priority = "Medium"
        recommendation = (
            "Schedule preventive maintenance within the "
            "next 30 days."
        )
    else:
        priority = "Routine"
        recommendation = (
            "Continue routine cleaning and preventive "
            "maintenance."
        )

    return {
        "conditionUsed": condition,
        "maintenanceStatus": status,
        "priority": priority,
        "recommendedCleaningDate": (
            recommended_cleaning_date.isoformat()
        ),
        "recommendedMaintenanceDate": (
            recommended_maintenance_date.isoformat()
        ),
        "daysUntilMaintenance": days_until,
        "recommendation": recommendation,
        "basedOnMaintenanceHistory": latest is not None,
    }
