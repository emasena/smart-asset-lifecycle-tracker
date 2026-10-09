"""Scheduled maintenance evaluation and notification."""

import json
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal

import boto3

from maintenance_recommendation import calculate_maintenance_recommendation


LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def _as_of_date(event):
    event_time = event.get("time")

    if isinstance(event_time, str) and len(event_time) >= 10:
        try:
            return date.fromisoformat(event_time[:10]).isoformat()
        except ValueError:
            pass

    return date.today().isoformat()


MAX_HISTORY_RECORDS = 10


def _scan_items(table):
    params = {
        "FilterExpression": (
            "SK = :metadata OR begins_with(SK, :maintenance)"
        ),
        "ExpressionAttributeValues": {
            ":metadata": "METADATA",
            ":maintenance": "MAINTENANCE#",
        },
    }

    while True:
        page = table.scan(**params)

        for item in page.get("Items", []):
            yield item

        last_key = page.get("LastEvaluatedKey")

        if not last_key:
            return

        params["ExclusiveStartKey"] = last_key


def _collect_assets_and_history(table):
    """Read assets and their maintenance records in one table scan."""
    assets = []
    records_by_asset = {}

    for item in _scan_items(table):
        sort_key = item.get("SK", "")

        if sort_key == "METADATA":
            assets.append(item)
        else:
            records_by_asset.setdefault(item.get("PK"), []).append(item)

    history_by_asset = {}

    for partition_key, records in records_by_asset.items():
        records.sort(key=lambda record: record["SK"], reverse=True)
        history_by_asset[partition_key] = [
            {
                key: value
                for key, value in record.items()
                if key not in {"PK", "SK"}
            }
            for record in records[:MAX_HISTORY_RECORDS]
        ]

    return assets, history_by_asset


def evaluate_assets(table, as_of_date):
    alerts = []
    evaluated_count = 0
    skipped_count = 0

    assets, history_by_asset = _collect_assets_and_history(table)

    for asset in assets:
        asset_id = asset.get("assetId")

        if not asset_id:
            skipped_count += 1
            continue

        evaluated_count += 1

        try:
            recommendation = calculate_maintenance_recommendation(
                asset,
                maintenance_history=history_by_asset.get(
                    f"ASSET#{asset_id}",
                    [],
                ),
                as_of_date=as_of_date,
            )
        except Exception as exc:
            skipped_count += 1
            LOGGER.warning(
                "Skipping maintenance calculation assetId=%s: %s",
                asset_id,
                exc,
            )
            continue

        if recommendation["maintenanceStatus"] not in {
            "DueSoon",
            "Overdue",
        }:
            continue

        alerts.append(
            {
                "assetId": asset_id,
                "assetTag": asset.get("assetTag"),
                "category": asset.get("category"),
                "description": asset.get("description"),
                "condition": (
                    recommendation["conditionUsed"]
                ),
                "maintenanceStatus": (
                    recommendation["maintenanceStatus"]
                ),
                "priority": recommendation["priority"],
                "recommendedMaintenanceDate": (
                    recommendation[
                        "recommendedMaintenanceDate"
                    ]
                ),
                "recommendedCleaningDate": (
                    recommendation[
                        "recommendedCleaningDate"
                    ]
                ),
                "daysUntilMaintenance": (
                    recommendation["daysUntilMaintenance"]
                ),
            }
        )

    alerts.sort(
        key=lambda item: (
            item["daysUntilMaintenance"],
            item["assetTag"] or "",
        )
    )

    return {
        "asOfDate": as_of_date,
        "evaluatedCount": evaluated_count,
        "skippedCount": skipped_count,
        "alertCount": len(alerts),
        "alerts": alerts,
    }


def _notification_message(report):
    lines = [
        "AWS Smart Asset Lifecycle Tracker",
        "Scheduled maintenance report",
        "",
        f"As of: {report['asOfDate']}",
        f"Assets evaluated: {report['evaluatedCount']}",
        f"Assets requiring attention: {report['alertCount']}",
        "",
    ]

    for alert in report["alerts"]:
        lines.extend(
            [
                (
                    f"{alert['assetTag'] or alert['assetId']} — "
                    f"{alert['maintenanceStatus']}"
                ),
                (
                    "Recommended maintenance date: "
                    f"{alert['recommendedMaintenanceDate']}"
                ),
                (
                    "Days until maintenance: "
                    f"{alert['daysUntilMaintenance']}"
                ),
                f"Priority: {alert['priority']}",
                "",
            ]
        )

    return "\n".join(lines)


def lambda_handler(event, _context):
    table_name = os.environ["ASSET_TABLE_NAME"]
    topic_arn = os.environ["MAINTENANCE_TOPIC_ARN"]

    table = boto3.resource("dynamodb").Table(table_name)
    sns = boto3.client("sns")

    report = evaluate_assets(
        table,
        _as_of_date(event),
    )

    if not report["alerts"]:
        LOGGER.info(
            "Maintenance check completed without alerts "
            "evaluated=%s skipped=%s",
            report["evaluatedCount"],
            report["skippedCount"],
        )

        return {
            "status": "Complete",
            **report,
            "notificationSent": False,
        }

    sns.publish(
        TopicArn=topic_arn,
        Subject=(
            "Smart Asset Maintenance Alert: "
            f"{report['alertCount']} asset(s)"
        ),
        Message=_notification_message(report),
        MessageAttributes={
            "alertType": {
                "DataType": "String",
                "StringValue": "Maintenance",
            }
        },
    )

    LOGGER.info(
        "Maintenance notification sent alertCount=%s",
        report["alertCount"],
    )

    return {
        "status": "Complete",
        **report,
        "notificationSent": True,
        "completedAt": datetime.now(
            timezone.utc
        ).isoformat(),
    }
