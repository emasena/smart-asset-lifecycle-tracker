import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from domain import (
    ValidationError,
    can_create,
    can_read,
    parse_groups,
    validate_asset,
    validate_create_permissions,
    validate_update_permissions,
)
from depreciation import (
    DepreciationError,
    calculate_depreciation,
)
from maintenance import (
    MaintenanceValidationError,
    validate_maintenance,
)

from maintenance_ai import (
    MaintenanceAiError,
    generate_maintenance_advice,
)

from maintenance_recommendation import (
    MaintenanceRecommendationError,
    calculate_maintenance_recommendation,
)

LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
TABLE = boto3.resource("dynamodb").Table(os.environ["ASSET_TABLE_NAME"])
TRANSACTIONS = boto3.client("dynamodb")
S3 = boto3.client("s3")
PHOTO_BUCKET = os.environ.get("ASSET_PHOTO_BUCKET")
PHOTO_URL_EXPIRES_IN = 300
SERIALIZER = TypeSerializer()

PENDING_PREFIX = "pending/"
CLAIMED_PREFIX = "claimed/"


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def _body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Request body contains invalid JSON.") from exc


def _identity(event):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("claims") or {}
    return claims, parse_groups(claims.get("cognito:groups"))


def _asset_key(asset_id):
    return {"PK": f"ASSET#{asset_id}", "SK": "METADATA"}


def _asset_tag(tag):
    return tag.strip().upper()


def _tag_key(tag):
    return {"PK": f"ASSET_TAG#{_asset_tag(tag)}", "SK": "UNIQUE"}


def _wire_item(item):
    return {name: SERIALIZER.serialize(value) for name, value in item.items()}


def _existing_tag(tag, excluding_asset_id=None):
    """Cover assets created before unique tag reservation records existed."""
    params = {
        "FilterExpression": Attr("SK").eq("METADATA"),
        "ProjectionExpression": "assetId, assetTag",
        "ConsistentRead": True,
    }
    while True:
        page = TABLE.scan(**params)
        for item in page.get("Items", []):
            current = item.get("assetTag")
            if (isinstance(current, str) and _asset_tag(current) == _asset_tag(tag)
                    and item.get("assetId") != excluding_asset_id):
                return True
        if "LastEvaluatedKey" not in page:
            return False
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _condition_failed(exc):
    if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    return any(reason.get("Code") == "ConditionalCheckFailed"
               for reason in exc.response.get("CancellationReasons", []))

def _clean_asset(item):
    if not item:
        return None

    return {
        key: value
        for key, value in item.items()
        if key not in {"PK", "SK"}
    }


def _normalise_index_fields(item):
    for field in ("assignedUserId", "department"):
        value = item.get(field)

        if value is None or (
            isinstance(value, str)
            and not value.strip()
        ):
            item.pop(field, None)

        elif not isinstance(value, str):
            raise ValidationError(
                f"{field} must be a string.",
                [field],
            )

        else:
            item[field] = value.strip()

    return item


def _claim_photo(image_key):
    """Copy a pending photo to the prefix the S3 lifecycle rule leaves alone.

    Once an asset's imageKey points at it, the photo must outlive the 7-day
    pending/ expiration, so it's copied to claimed/ before being persisted.
    The pending object is kept until the asset write succeeds, so a rejected
    or failed save can be retried with the same imageKey. The copy is
    idempotent, so retrying simply overwrites the same claimed/ key.
    """
    if not image_key or not image_key.startswith(PENDING_PREFIX):
        return image_key

    claimed_key = CLAIMED_PREFIX + image_key[len(PENDING_PREFIX):]
    try:
        S3.copy_object(
            Bucket=PHOTO_BUCKET,
            CopySource={"Bucket": PHOTO_BUCKET, "Key": image_key},
            Key=claimed_key,
        )
    except ClientError as exc:
        raise ValidationError(
            "The uploaded photograph could not be found. Upload it again.",
            ["imageKey"],
        ) from exc
    return claimed_key


def _release_pending_photo(pending_key):
    """Best-effort removal of a pending photo once its asset has been saved.

    A failure here must not fail a save that already succeeded; the pending/
    lifecycle rule expires anything left behind.
    """
    if not pending_key or not pending_key.startswith(PENDING_PREFIX):
        return
    try:
        S3.delete_object(Bucket=PHOTO_BUCKET, Key=pending_key)
    except ClientError:
        LOGGER.warning("Could not delete claimed pending photo key=%s", pending_key, exc_info=True)


def _asset_view(item):
    asset = _clean_asset(item)

    if not asset:
        return None

    try:
        asset["depreciation"] = calculate_depreciation(
            purchase_value=asset["purchaseValue"],
            salvage_value=asset["salvageValue"],
            useful_life_months=asset["usefulLifeMonths"],
            in_service_date=asset["inServiceDate"],
        )
    except (KeyError, TypeError, ValueError, DepreciationError):
        LOGGER.warning(
            "Unable to calculate depreciation assetId=%s",
            asset.get("assetId"),
        )
        asset["depreciation"] = None

    return asset


def _create(event, claims, groups):
    if not can_create(groups):
        return response(403, {"error": "Forbidden", "message": "You do not have permission to create assets."})

    payload = _body(event)
    validate_asset(payload)

    if not validate_create_permissions(groups, payload):
        return response(
            403,
            {
                "error": "Forbidden",
                "message": "Only an Administrator can set assignment fields on a new asset.",
            },
        )

    payload["assetTag"] = _asset_tag(payload["assetTag"])

    if "Technician" in groups and "Administrator" not in groups:
        department = claims.get("custom:department")

        if not department:
            return response(
                403,
                {
                    "error": "Forbidden",
                    "message": "Your account does not have a department assigned.",
                },
            )

        payload["department"] = department

    pending_key = payload.get("imageKey")
    if pending_key:
        payload["imageKey"] = _claim_photo(pending_key)

    if _existing_tag(payload["assetTag"]):
        return response(
            409,
            {
                "error": "Conflict",
                "message": "An asset with this asset tag already exists.",
            },
        )

    asset_id = f"AST-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    item = {
        **payload,
        **_asset_key(asset_id),
        "assetId": asset_id,
        "depreciationMethod": payload.get(
            "depreciationMethod",
            "straight-line",
        ),
        "reviewStatus": payload.get(
            "reviewStatus",
            "ManualEntry",
        ),
        "createdBy": claims.get("sub"),
        "createdAt": now,
        "updatedAt": now,
    }

    item = _normalise_index_fields(item)

    item["purchaseValue"] = Decimal(str(item["purchaseValue"]))
    item["salvageValue"] = Decimal(str(item["salvageValue"]))

    # The tag reservation and the asset record commit together. Two requests
    # for the same tag cannot both succeed, even when they arrive concurrently.
    try:
        TRANSACTIONS.transact_write_items(TransactItems=[
            {"Put": {
                "TableName": TABLE.name,
                "Item": _wire_item({**_tag_key(payload["assetTag"]), "assetId": asset_id}),
                "ConditionExpression": "attribute_not_exists(PK)",
            }},
            {"Put": {
                "TableName": TABLE.name,
                "Item": _wire_item(item),
                "ConditionExpression": "attribute_not_exists(PK)",
            }},
        ])
    except ClientError as exc:
        if _condition_failed(exc):
            return response(409, {"error": "Conflict", "message": "An asset with this asset tag already exists."})
        raise

    _release_pending_photo(pending_key)
    LOGGER.info("Asset created assetId=%s actorSub=%s", asset_id, claims.get("sub"))
    return response(201, {"assetId": asset_id, "message": "Asset created successfully."})


def _get(asset_id, claims, groups):
    item = TABLE.get_item(Key=_asset_key(asset_id), ConsistentRead=True).get("Item")
    if not item:
        return response(404, {"error": "NotFound", "message": "Asset was not found."})
    if not can_read(groups, claims, item):
        return response(403, {"error": "Forbidden", "message": "You do not have permission to view this asset."})
    return response(200, _asset_view(item))

def _encode_next_token(last_evaluated_key):
    if not last_evaluated_key:
        return None

    raw = json.dumps(last_evaluated_key, default=_json_default).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _decode_next_token(token):
    if not token:
        return None

    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError("Invalid nextToken.")


def _photo_analysis_key(photo_key):
    # Analyses are recorded against the original upload key, so a claimed
    # photo is looked up under the pending/ key it was uploaded as.
    if photo_key.startswith(CLAIMED_PREFIX):
        photo_key = PENDING_PREFIX + photo_key[len(CLAIMED_PREFIX):]

    return {
        "PK": f"PHOTO#{photo_key}",
        "SK": "ANALYSIS",
    }


def _load_readable_asset(asset_id, claims, groups, denied_message):
    """Return (asset, None) or (None, error response)."""
    asset = TABLE.get_item(
        Key=_asset_key(asset_id),
        ConsistentRead=True,
    ).get("Item")

    if not asset:
        return None, response(
            404,
            {
                "error": "NotFound",
                "message": "Asset was not found.",
            },
        )

    if not can_read(groups, claims, asset):
        return None, response(
            403,
            {
                "error": "Forbidden",
                "message": denied_message,
            },
        )

    return asset, None


def _get_photo(asset_id, claims, groups):
    item, error = _load_readable_asset(
        asset_id,
        claims,
        groups,
        (
            "You do not have permission to view "
            "this asset photograph."
        ),
    )

    if error:
        return error

    photo_key = item.get("imageKey")

    if not photo_key:
        return response(
            404,
            {
                "error": "NotFound",
                "message": "This asset does not have a photograph.",
            },
        )

    if (
        not PHOTO_BUCKET
        or not photo_key.startswith((PENDING_PREFIX, CLAIMED_PREFIX, "assets/"))
    ):
        LOGGER.error(
            "Invalid photo configuration assetId=%s photoKey=%s",
            asset_id,
            photo_key,
        )
        return response(
            500,
            {
                "error": "InternalServerError",
                "message": "The asset photograph is unavailable.",
            },
        )

    photo_url = S3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": PHOTO_BUCKET,
            "Key": photo_key,
        },
        ExpiresIn=PHOTO_URL_EXPIRES_IN,
    )

    analysis = TABLE.get_item(
        Key=_photo_analysis_key(photo_key),
        ConsistentRead=True,
    ).get("Item")

    LOGGER.info(
        "Asset photo viewed assetId=%s actorSub=%s",
        asset_id,
        claims.get("sub"),
    )

    return response(
        200,
        {
            "assetId": asset_id,
            "photoUrl": photo_url,
            "expiresIn": PHOTO_URL_EXPIRES_IN,
            "analysisStatus": (
                analysis.get("status", "Processing")
                if analysis
                else "Processing"
            ),
            "suggestion": (
                analysis.get("suggestion")
                if analysis
                else None
            ),
        },
    )

def _list(event, claims, groups):
    params = event.get("queryStringParameters") or {}

    filters = Attr("SK").eq("METADATA")

    if params.get("status"):
        filters &= Attr("status").eq(params["status"])

    if params.get("category"):
        filters &= Attr("category").eq(params["category"])

    if params.get("q"):
        query = params["q"]
        filters &= (
            Attr("assetTag").contains(query)
            | Attr("description").contains(query)
            | Attr("manufacturer").contains(query)
        )

    request = {
        "FilterExpression": filters,
        "Limit": 100,
    }

    if params.get("nextToken"):
        request["ExclusiveStartKey"] = _decode_next_token(params["nextToken"])

    if groups.intersection({"Administrator", "Auditor"}):
        result = TABLE.scan(**request)

    elif groups.intersection({"Manager", "Technician"}):
        department = claims.get("custom:department")

        if not department:
            return response(403, {
                "error": "Forbidden",
                "message": "Your account does not have a department assigned.",
            })

        request["IndexName"] = "DepartmentIndex"
        request["KeyConditionExpression"] = Key("department").eq(department)
        result = TABLE.query(**request)

    elif "Employee" in groups:
        request["IndexName"] = "AssignedUserIndex"
        request["KeyConditionExpression"] = Key("assignedUserId").eq(claims["sub"])
        result = TABLE.query(**request)

    else:
        return response(403, {
            "error": "Forbidden",
            "message": "You do not have permission to list assets.",
        })

    items = [_asset_view(item) for item in result.get("Items", [])]

    body = {
            "items": items,
            "count": len(items),
    }

    if result.get("LastEvaluatedKey"):
        body["nextToken"] = _encode_next_token(result["LastEvaluatedKey"])

    return response(200, body)


def _update(event, asset_id, claims, groups):
    existing = TABLE.get_item(Key=_asset_key(asset_id), ConsistentRead=True).get("Item")
    if not existing:
        return response(404, {"error": "NotFound", "message": "Asset was not found."})

    if not can_read(groups, claims, existing):
        return response(
            403,
            {
                "error": "Forbidden",
                "message": "You cannot modify assets outside your authorized scope.",
            },
        )

    payload = _body(event)
    immutable = {"assetId", "PK", "SK", "createdAt", "createdBy"}
    changed_fields = set(payload) - immutable
    if not changed_fields:
        raise ValidationError("No editable fields were supplied.")
    if not validate_update_permissions(groups, changed_fields):
        return response(403, {"error": "Forbidden", "message": "You do not have permission to update these asset fields."})

    current = _clean_asset(existing)
    # DynamoDB returns numbers as Decimal; validation expects an int.
    if isinstance(current.get("usefulLifeMonths"), Decimal):
        current["usefulLifeMonths"] = int(current["usefulLifeMonths"])
    candidate = {
        **current,
        **{
            key: value
            for key, value in payload.items()
            if key not in immutable
        },
    }

    validate_asset(candidate)
    candidate = _normalise_index_fields(candidate)

    candidate["assetTag"] = _asset_tag(candidate["assetTag"])
    candidate["purchaseValue"] = Decimal(str(candidate["purchaseValue"]))
    candidate["salvageValue"] = Decimal(str(candidate["salvageValue"]))
    candidate["updatedAt"] = datetime.now(timezone.utc).isoformat()
    candidate["updatedBy"] = claims.get("sub")

    pending_key = None
    if "imageKey" in changed_fields and candidate.get("imageKey"):
        pending_key = candidate["imageKey"]
        candidate["imageKey"] = _claim_photo(pending_key)

    old_tag = _asset_tag(existing["assetTag"])
    new_tag = candidate["assetTag"]

    if old_tag != new_tag:
        if _existing_tag(new_tag, excluding_asset_id=asset_id):
            return response(409, {"error": "Conflict", "message": "An asset with this asset tag already exists."})

        writes = [
            {"Put": {
                "TableName": TABLE.name,
                "Item": _wire_item({**_tag_key(new_tag), "assetId": asset_id}),
                "ConditionExpression": "attribute_not_exists(PK)",
            }},
            {"Put": {
                "TableName": TABLE.name,
                "Item": _wire_item({**candidate, **_asset_key(asset_id)}),
                "ConditionExpression": "attribute_exists(PK) AND assetTag = :old_tag",
                "ExpressionAttributeValues": {":old_tag": SERIALIZER.serialize(existing["assetTag"])},
            }},
        ]
        old_reservation = TABLE.get_item(Key=_tag_key(old_tag), ConsistentRead=True).get("Item")
        if old_reservation and old_reservation.get("assetId") == asset_id:
            writes.append({"Delete": {
                "TableName": TABLE.name,
                "Key": _wire_item(_tag_key(old_tag)),
                "ConditionExpression": "assetId = :asset_id",
                "ExpressionAttributeValues": {":asset_id": SERIALIZER.serialize(asset_id)},
            }})
        try:
            TRANSACTIONS.transact_write_items(TransactItems=writes)
        except ClientError as exc:
            if _condition_failed(exc):
                return response(409, {"error": "Conflict", "message": "The asset tag is already in use or the asset changed during your update."})
            raise
    else:
        try:
            TABLE.put_item(
                Item={**candidate, **_asset_key(asset_id)},
                ConditionExpression="attribute_exists(PK) AND assetTag = :old_tag",
                ExpressionAttributeValues={":old_tag": existing["assetTag"]},
            )
        except TABLE.meta.client.exceptions.ConditionalCheckFailedException:
            return response(409, {"error": "Conflict", "message": "The asset changed during your update. Refresh and try again."})
    _release_pending_photo(pending_key)
    LOGGER.info("Asset updated assetId=%s actorSub=%s fields=%s", asset_id, claims.get("sub"), sorted(changed_fields))
    return response(200, {"assetId": asset_id, "message": "Asset updated successfully."})

def _maintenance_key(asset_id, performed_date, maintenance_id):
    return {
        "PK": f"ASSET#{asset_id}",
        "SK": f"MAINTENANCE#{performed_date}#{maintenance_id}",
    }


def _find_maintenance(asset_id, maintenance_id):
    """The sort key embeds the date, so the record is located by its ID."""
    params = {
        "KeyConditionExpression": (
            "PK = :pk AND begins_with(SK, :maintenance)"
        ),
        "FilterExpression": "maintenanceId = :maintenance_id",
        "ExpressionAttributeValues": {
            ":pk": f"ASSET#{asset_id}",
            ":maintenance": "MAINTENANCE#",
            ":maintenance_id": maintenance_id,
        },
        "ConsistentRead": True,
    }

    while True:
        page = TABLE.query(**params)

        for item in page.get("Items", []):
            if item.get("maintenanceId") == maintenance_id:
                return item

        if "LastEvaluatedKey" not in page:
            return None

        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _authorized_maintenance(asset_id, maintenance_id, claims, groups):
    """Return (record, None) or (None, error response)."""
    asset, error = _load_readable_asset(
        asset_id,
        claims,
        groups,
        "You cannot change maintenance for this asset.",
    )

    if error:
        return None, error

    # can_read lets Auditors see every department, so a Technician who is
    # also an Auditor would pass it. Changes stay scoped to the caller's
    # own department unless they are an Administrator.
    department = claims.get("custom:department")

    if "Administrator" not in groups and (
        not department or department != asset.get("department")
    ):
        return None, response(
            403,
            {
                "error": "Forbidden",
                "message": (
                    "You can only change maintenance for assets "
                    "in your department."
                ),
            },
        )

    record = _find_maintenance(asset_id, maintenance_id)

    if not record:
        return None, response(
            404,
            {
                "error": "NotFound",
                "message": "Maintenance record was not found.",
            },
        )

    return record, None


def _create_maintenance(event, asset_id, claims, groups):
    asset, error = _load_readable_asset(
        asset_id,
        claims,
        groups,
        "You cannot add maintenance to this asset.",
    )

    if error:
        return error

    if (
        "Administrator" not in groups
        and "Technician" not in groups
    ):
        return response(
            403,
            {
                "error": "Forbidden",
                "message": (
                    "Only an Administrator or Technician can "
                    "record maintenance."
                ),
            },
        )

    maintenance = validate_maintenance(_body(event))
    now = datetime.now(timezone.utc).isoformat()
    maintenance_id = f"MNT-{uuid.uuid4().hex[:8].upper()}"

    item = {
        **maintenance,
        **_maintenance_key(
            asset_id,
            maintenance["performedDate"],
            maintenance_id,
        ),
        "maintenanceId": maintenance_id,
        "assetId": asset_id,
        "performedBy": claims.get("sub"),
        "performedByEmail": claims.get("email"),
        "createdAt": now,
    }

    item = {
        key: value
        for key, value in item.items()
        if value is not None
    }

    TABLE.put_item(
        Item=item,
        ConditionExpression=(
            "attribute_not_exists(PK) AND "
            "attribute_not_exists(SK)"
        ),
    )

    LOGGER.info(
        "Maintenance created assetId=%s maintenanceId=%s actorSub=%s",
        asset_id,
        maintenance_id,
        claims.get("sub"),
    )

    return response(
        201,
        {
            "assetId": asset_id,
            "maintenanceId": maintenance_id,
            "message": "Maintenance recorded successfully.",
        },
    )

def _maintenance_unchanged_condition(existing):
    """Condition that the stored record is still the version that was read."""
    values = {":maintenance_id": existing["maintenanceId"]}

    if existing.get("updatedAt"):
        values[":updated_at"] = existing["updatedAt"]
        return (
            "maintenanceId = :maintenance_id AND updatedAt = :updated_at",
            values,
        )

    return (
        "maintenanceId = :maintenance_id AND attribute_not_exists(updatedAt)",
        values,
    )


def _maintenance_conflict():
    return response(
        409,
        {
            "error": "Conflict",
            "message": (
                "The maintenance record changed during your "
                "update. Refresh and try again."
            ),
        },
    )


def _update_maintenance(
    event,
    asset_id,
    maintenance_id,
    claims,
    groups,
):
    if (
        "Administrator" not in groups
        and "Technician" not in groups
    ):
        return response(
            403,
            {
                "error": "Forbidden",
                "message": (
                    "Only an Administrator or Technician can "
                    "edit maintenance."
                ),
            },
        )

    existing, error = _authorized_maintenance(
        asset_id,
        maintenance_id,
        claims,
        groups,
    )

    if error:
        return error

    if (
        "Administrator" not in groups
        and existing.get("performedBy") != claims.get("sub")
    ):
        return response(
            403,
            {
                "error": "Forbidden",
                "message": (
                    "A Technician can only edit maintenance "
                    "they recorded."
                ),
            },
        )

    body = _body(event)
    maintenance = validate_maintenance(body)

    # The client sends the updatedAt it last saw so an edit made from a
    # stale form cannot silently overwrite someone else's change.
    if (
        "expectedUpdatedAt" in body
        and body["expectedUpdatedAt"] != existing.get("updatedAt")
    ):
        return _maintenance_conflict()

    unchanged, unchanged_values = _maintenance_unchanged_condition(
        existing,
    )

    # Identity and audit fields always come from the stored record or the
    # authenticated caller, never from the request body.
    item = {
        **maintenance,
        **_maintenance_key(
            asset_id,
            maintenance["performedDate"],
            maintenance_id,
        ),
        "maintenanceId": maintenance_id,
        "assetId": asset_id,
        "performedBy": existing.get("performedBy"),
        "performedByEmail": existing.get("performedByEmail"),
        "createdAt": existing.get("createdAt"),
        "updatedBy": claims.get("sub"),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }

    item = {
        key: value
        for key, value in item.items()
        if value is not None
    }

    if item["SK"] == existing["SK"]:
        try:
            TABLE.put_item(
                Item=item,
                ConditionExpression=unchanged,
                ExpressionAttributeValues=unchanged_values,
            )
        except TABLE.meta.client.exceptions.ConditionalCheckFailedException:
            return _maintenance_conflict()
    else:
        # A new performed date moves the record to a new sort key, so the
        # old item is removed in the same transaction.
        try:
            TRANSACTIONS.transact_write_items(TransactItems=[
                {"Put": {
                    "TableName": TABLE.name,
                    "Item": _wire_item(item),
                    "ConditionExpression": "attribute_not_exists(SK)",
                }},
                {"Delete": {
                    "TableName": TABLE.name,
                    "Key": _wire_item({
                        "PK": existing["PK"],
                        "SK": existing["SK"],
                    }),
                    "ConditionExpression": unchanged,
                    "ExpressionAttributeValues": _wire_item(
                        unchanged_values,
                    ),
                }},
            ])
        except ClientError as exc:
            if _condition_failed(exc):
                return _maintenance_conflict()
            raise

    LOGGER.info(
        "Maintenance updated assetId=%s maintenanceId=%s actorSub=%s",
        asset_id,
        maintenance_id,
        claims.get("sub"),
    )

    return response(
        200,
        {
            "assetId": asset_id,
            "maintenanceId": maintenance_id,
            "message": "Maintenance record updated successfully.",
        },
    )


def _delete_maintenance(asset_id, maintenance_id, claims, groups):
    if "Administrator" not in groups:
        return response(
            403,
            {
                "error": "Forbidden",
                "message": (
                    "Only an Administrator can delete maintenance."
                ),
            },
        )

    existing, error = _authorized_maintenance(
        asset_id,
        maintenance_id,
        claims,
        groups,
    )

    if error:
        return error

    try:
        TABLE.delete_item(
            Key={"PK": existing["PK"], "SK": existing["SK"]},
            ConditionExpression="maintenanceId = :maintenance_id",
            ExpressionAttributeValues={
                ":maintenance_id": maintenance_id,
            },
        )
    except TABLE.meta.client.exceptions.ConditionalCheckFailedException:
        return response(
            404,
            {
                "error": "NotFound",
                "message": "Maintenance record was not found.",
            },
        )

    LOGGER.info(
        "Maintenance deleted assetId=%s maintenanceId=%s actorSub=%s",
        asset_id,
        maintenance_id,
        claims.get("sub"),
    )

    return response(
        200,
        {
            "assetId": asset_id,
            "maintenanceId": maintenance_id,
            "message": "Maintenance record deleted successfully.",
        },
    )


def _list_maintenance(asset_id, claims, groups):
    asset, error = _load_readable_asset(
        asset_id,
        claims,
        groups,
        (
            "You do not have permission to view "
            "maintenance for this asset."
        ),
    )

    if error:
        return error
    params = {
        "KeyConditionExpression": (
            "PK = :pk AND begins_with(SK, :maintenance)"
        ),
        "ExpressionAttributeValues": {
            ":pk": f"ASSET#{asset_id}",
            ":maintenance": "MAINTENANCE#",
        },
        "ScanIndexForward": False,
    }
    items = []

    # A long history can exceed one 1 MB query page; read every page so
    # older records stay visible and editable.
    while True:
        result = TABLE.query(**params)
        items.extend(
            _clean_asset(item)
            for item in result.get("Items", [])
        )

        if "LastEvaluatedKey" not in result:
            break

        params["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    try:
        recommendation = calculate_maintenance_recommendation(
            _clean_asset(asset),
            maintenance_history=items,
        )
    except MaintenanceRecommendationError as exc:
        recommendation = {
            "maintenanceStatus": "Unavailable",
            "message": str(exc),
        }

    return response(
        200,
        {
            "assetId": asset_id,
            "items": items,
            "count": len(items),
            "recommendation": recommendation,
        },
    )

def _generate_maintenance_recommendation(
    asset_id,
    claims,
    groups,
):
    asset, error = _load_readable_asset(
        asset_id,
        claims,
        groups,
        (
            "You cannot generate recommendations "
            "for this asset."
        ),
    )

    if error:
        return error

    if (
        "Administrator" not in groups
        and "Technician" not in groups
    ):
        return response(
            403,
            {
                "error": "Forbidden",
                "message": (
                    "Only an Administrator or Technician can "
                    "generate AI maintenance recommendations."
                ),
            },
        )

    history_result = TABLE.query(
        KeyConditionExpression=(
            "PK = :pk AND begins_with(SK, :maintenance)"
        ),
        ExpressionAttributeValues={
            ":pk": f"ASSET#{asset_id}",
            ":maintenance": "MAINTENANCE#",
        },
        ScanIndexForward=False,
        Limit=10,
    )

    history = [
        _clean_asset(item)
        for item in history_result.get("Items", [])
    ]

    clean_asset = _clean_asset(asset)

    try:
        schedule = calculate_maintenance_recommendation(
            clean_asset,
            maintenance_history=history,
        )
    except MaintenanceRecommendationError as exc:
        return response(
            422,
            {
                "error": "ScheduleUnavailable",
                "message": str(exc),
            },
        )

    try:
        ai_recommendation = generate_maintenance_advice(
            clean_asset,
            history,
            schedule,
        )
    except ClientError as exc:
        LOGGER.warning("Bedrock maintenance request failed: %s", exc)
        raise MaintenanceAiError("Bedrock request failed.") from exc

    LOGGER.info(
        "AI maintenance recommendation generated "
        "assetId=%s actorSub=%s",
        asset_id,
        claims.get("sub"),
    )

    return response(
        200,
        {
            "assetId": asset_id,
            "schedule": schedule,
            "aiRecommendation": ai_recommendation,
            "generatedForReview": True,
        },
    )

def lambda_handler(event, _context):
    method = event.get("httpMethod", "")
    path_parameters = event.get("pathParameters") or {}
    asset_id = path_parameters.get("assetId")
    maintenance_id = path_parameters.get("maintenanceId")
    route = event.get("resource") or event.get("path") or ""
    claims, groups = _identity(event)

    if not claims.get("sub"):
        return response(
            401,
            {
                "error": "Unauthorized",
                "message": "Sign in to access this resource.",
            },
        )

    try:
        if (
            method == "POST"
            and asset_id
            and route.endswith(
                "/maintenance-recommendation"
            )
        ):
            return _generate_maintenance_recommendation(
                asset_id,
                claims,
                groups,
            )

        if method == "PUT" and asset_id and maintenance_id:
            return _update_maintenance(
                event,
                asset_id,
                maintenance_id,
                claims,
                groups,
            )

        if method == "DELETE" and asset_id and maintenance_id:
            return _delete_maintenance(
                asset_id,
                maintenance_id,
                claims,
                groups,
            )

        if (
            method == "POST"
            and asset_id
            and route.endswith("/maintenance")
        ):
            return _create_maintenance(
                event,
                asset_id,
                claims,
                groups,
            )

        if (
            method == "GET"
            and asset_id
            and route.endswith("/maintenance")
        ):
            return _list_maintenance(
                asset_id,
                claims,
                groups,
            )

        if method == "POST" and not asset_id:
            return _create(event, claims, groups)

        if (
            method == "GET"
            and asset_id
            and route.endswith("/photo")
        ):
            return _get_photo(
                asset_id,
                claims,
                groups,
            )
        if method == "GET" and asset_id:
            return _get(asset_id, claims, groups)

        if method == "GET":
            return _list(event, claims, groups)

        if method == "PUT" and asset_id:
            return _update(
                event,
                asset_id,
                claims,
                groups,
            )

        return response(
            405,
            {
                "error": "MethodNotAllowed",
                "message": "Method is not supported.",
            },
        )

    except MaintenanceAiError as exc:
        LOGGER.warning(
            "Invalid Bedrock maintenance response: %s",
            exc,
        )
        return response(
            502,
            {
                "error": "AiRecommendationError",
                "message": (
                    "The AI recommendation could not be "
                    "validated. Try again later."
                ),
            },
        )

    except MaintenanceValidationError as exc:
        return response(
            400,
            {
                "error": "ValidationError",
                "message": str(exc),
                "fields": exc.fields,
            },
        )

    except ValidationError as exc:
        return response(
            400,
            {
                "error": "ValidationError",
                "message": str(exc),
                "fields": exc.fields,
            },
        )

    except Exception:
        LOGGER.exception("Unhandled asset API error")
        return response(
            500,
            {
                "error": "InternalServerError",
                "message": "The request could not be completed.",
            },
        )