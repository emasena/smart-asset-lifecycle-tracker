"""Analyze an uploaded asset photograph with Amazon Bedrock."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import unquote_plus
from decimal import Decimal
from domain import parse_groups

import boto3
from botocore.exceptions import ClientError


LOGGER = logging.getLogger()
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

S3 = boto3.client("s3")
BEDROCK = boto3.client("bedrock-runtime")
TABLE = boto3.resource("dynamodb").Table(
    os.environ["ASSET_TABLE_NAME"]
)

PHOTO_BUCKET = os.environ["ASSET_PHOTO_BUCKET"]
MODEL_ID = os.environ.get(
    "PHOTO_MODEL_ID",
    "us.amazon.nova-lite-v1:0",
)

MAX_IMAGE_BYTES = 3_750_000

PHOTO_KEY_PATTERN = re.compile(
    r"pending/[A-Za-z0-9_-]{1,128}/[0-9a-f]{32}\.(jpg|png)"
)

PROMPT = """
Analyze only what is visible in this asset photograph.

Return only a valid JSON object with these fields:

{
  "category": "string",
  "description": "string",
  "condition": "Good, Fair, Poor, or Unknown",
  "usefulLifeMonths": 48,
  "maintenanceCategory": "string",
  "reviewStatus": "NeedsReview or NeedsManualEntry"
}

Rules:

- Do not invent information that cannot be verified from the photograph.
- Do not provide serial numbers, exact model numbers, purchase values,
  purchase dates, or employee assignments.
- Keep the description short.
- If the asset cannot be identified, use NeedsManualEntry.
- If the asset can be identified, use NeedsReview.
- Return JSON only, without Markdown.
"""


def analysis_key(photo_key):
    return {
        "PK": f"PHOTO#{photo_key}",
        "SK": "ANALYSIS",
    }


def clean_model_json(raw_text):
    text = raw_text.strip()

    if text.startswith("```json"):
        text = text[7:]

    if text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def validate_suggestion(raw_text):
    result = json.loads(clean_model_json(raw_text))

    if not isinstance(result, dict):
        raise ValueError("Bedrock response must be a JSON object.")

    suggestion = {}

    for field in (
        "category",
        "description",
        "condition",
        "maintenanceCategory",
    ):
        value = result.get(field, "")

        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string.")

        value = value.strip()

        if len(value) > 400:
            raise ValueError(f"{field} is too long.")

        suggestion[field] = value

    if suggestion["condition"] not in {
        "Good",
        "Fair",
        "Poor",
        "Unknown",
        "",
    }:
        raise ValueError("Invalid condition.")

    useful_life = result.get("usefulLifeMonths")

    if useful_life is not None:
        if (
            type(useful_life) is not int
            or useful_life < 1
            or useful_life > 600
        ):
            raise ValueError("Invalid useful life.")

    suggestion["usefulLifeMonths"] = useful_life

    review_status = result.get("reviewStatus")

    if review_status not in {
        "NeedsReview",
        "NeedsManualEntry",
    }:
        raise ValueError("Invalid review status.")

    if not suggestion["category"] or not suggestion["description"]:
        review_status = "NeedsManualEntry"

    suggestion["reviewStatus"] = review_status

    return suggestion


def analyze_photo(bucket, photo_key):
    if bucket != PHOTO_BUCKET:
        LOGGER.warning("Ignoring unexpected bucket: %s", bucket)
        return

    if not PHOTO_KEY_PATTERN.fullmatch(photo_key):
        LOGGER.warning("Ignoring unexpected key: %s", photo_key)
        return

    key = analysis_key(photo_key)

    try:
        TABLE.put_item(
            Item={
                **key,
                "status": "Processing",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")

        if error_code == "ConditionalCheckFailedException":
            LOGGER.info(
                "Photo was already processed: %s",
                photo_key,
            )
            return

        raise

    try:
        photo = S3.get_object(
            Bucket=bucket,
            Key=photo_key,
        )

        content_type = photo.get("ContentType")

        image_format = {
            "image/jpeg": "jpeg",
            "image/png": "png",
        }.get(content_type)

        content_length = photo.get("ContentLength", 0)

        if not image_format:
            raise ValueError("Unsupported image content type.")

        if content_length < 1 or content_length > MAX_IMAGE_BYTES:
            raise ValueError("Image size is not supported.")

        image_bytes = photo["Body"].read(
            MAX_IMAGE_BYTES + 1
        )

        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds the size limit.")

        if image_format == "jpeg":
            if not image_bytes.startswith(b"\xff\xd8\xff"):
                raise ValueError("Invalid JPEG file.")
        else:
            if not image_bytes.startswith(
                b"\x89PNG\r\n\x1a\n"
            ):
                raise ValueError("Invalid PNG file.")

        response = BEDROCK.converse(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": image_format,
                                "source": {
                                    "bytes": image_bytes,
                                },
                            }
                        },
                        {
                            "text": PROMPT,
                        },
                    ],
                }
            ],
            inferenceConfig={
                "maxTokens": 350,
                "temperature": 0,
            },
        )

        content_blocks = response["output"]["message"]["content"]

        model_text = "".join(
            block.get("text", "")
            for block in content_blocks
        )

        suggestion = validate_suggestion(model_text)

        TABLE.update_item(
            Key=key,
            UpdateExpression=(
                "SET #analysisStatus = :ready, "
                "suggestion = :suggestion"
            ),
            ExpressionAttributeNames={
                "#analysisStatus": "status",
            },
            ExpressionAttributeValues={
                ":ready": "Ready",
                ":suggestion": suggestion,
            },
        )

        LOGGER.info(
            "Photo analysis completed for key: %s",
            photo_key,
        )

    except Exception:
        LOGGER.exception(
            "Photo analysis failed for key: %s",
            photo_key,
        )

        TABLE.update_item(
            Key=key,
            UpdateExpression=(
                "SET #analysisStatus = :failed"
            ),
            ExpressionAttributeNames={
                "#analysisStatus": "status",
            },
            ExpressionAttributeValues={
                ":failed": "Failed",
            },
        )


def lambda_handler(event, _context):
    for record in event.get("Records", []):
        bucket = (
            record.get("s3", {})
            .get("bucket", {})
            .get("name")
        )

        photo_key = unquote_plus(
            record.get("s3", {})
            .get("object", {})
            .get("key", "")
        )

        analyze_photo(bucket, photo_key)

    return {
        "processedRecords": len(
            event.get("Records", [])
        )
    }


def json_default(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)

        return float(value)

    raise TypeError(
        f"Cannot serialize {type(value).__name__}"
    )


def api_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(
            body,
            default=json_default,
        ),
    }


def api_handler(event, _context):
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )

    subject = claims.get("sub")
    groups = parse_groups(
        claims.get("cognito:groups")
    )

    if not subject:
        return api_response(
            401,
            {
                "message": (
                    "Sign in to view photo analysis."
                )
            },
        )

    parameters = (
        event.get("queryStringParameters") or {}
    )

    photo_key = parameters.get("key", "")

    if not PHOTO_KEY_PATTERN.fullmatch(photo_key):
        return api_response(
            400,
            {
                "message": "Invalid photograph key."
            },
        )

    key_parts = photo_key.split("/", 2)
    photo_owner = key_parts[1]

    is_administrator = "Administrator" in groups
    is_own_technician_photo = (
        "Technician" in groups
        and photo_owner == subject
    )

    if not (
        is_administrator
        or is_own_technician_photo
    ):
        return api_response(
            403,
            {
                "message": (
                    "You cannot view this photo analysis."
                )
            },
        )

    item = TABLE.get_item(
        Key=analysis_key(photo_key),
        ConsistentRead=True,
    ).get("Item")

    if not item:
        return api_response(
            202,
            {
                "status": "Processing"
            },
        )

    return api_response(
        200,
        {
            "status": item.get(
                "status",
                "Processing",
            ),
            "suggestion": item.get("suggestion"),
        },
    )