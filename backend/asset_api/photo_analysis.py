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
Analyze the primary physical asset visible in this photograph.

Return only one valid JSON object with exactly these fields:

{
  "category": "string",
  "model": null,
  "description": "string",
  "condition": "Good, Fair, Poor, or Unknown",
  "usefulLifeMonths": null,
  "estimatedProductionDate": null,
  "maintenanceCategory": "string"
}

Allowed asset categories:

- Laptop
- Desktop Computer
- Monitor
- Printer
- Network Equipment
- Server
- Storage Device
- Mobile Device
- Peripheral
- Office Equipment
- Other

Allowed maintenance categories:

- End-User Computing
- Display Equipment
- Print Services
- Network Infrastructure
- Server Infrastructure
- Storage Infrastructure
- Mobile Device Support
- Peripheral Equipment
- General Inspection

Classification rules:

- A portable computer with an integrated screen and keyboard is a Laptop.
- A standalone computer display is a Monitor.
- A printer, scanner, or multifunction printer is a Printer.
- A switch, router, firewall, or access point is Network Equipment.
- A rack-mounted or tower service computer is a Server.
- A keyboard, mouse, dock, webcam, or headset is a Peripheral.

Additional rules:

- Do not invent information that cannot be verified from the photograph.
- Set model only when it is clearly visible or can be identified confidently
  from distinctive physical characteristics. Otherwise return null.
- Do not guess an exact model from general appearance alone.
- Estimate usefulLifeMonths from the asset category, visible age, apparent
  condition, and a typical enterprise lifecycle.
- usefulLifeMonths must be an integer between 12 and 120.
- Set estimatedProductionDate in YYYY-MM-DD format only when an exact date is
  visible on the asset or its label. Otherwise return null.
- Describe the asset in five to twelve words.
- Base condition only on visible physical evidence; otherwise use Unknown.
- Do not provide serial numbers, purchase values, purchase dates, ownership,
  or employee assignments.
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

    model = result.get("model")

    if model is not None:
        if not isinstance(model, str):
            raise ValueError("model must be a string or null.")

        model = model.strip() or None

        if model and len(model) > 100:
            raise ValueError("model is too long.")

    suggestion["model"] = model

    if suggestion["condition"] not in {
        "Good",
        "Fair",
        "Poor",
        "Unknown",
        "",
    }:
        raise ValueError("Invalid condition.")

    useful_life = result.get("usefulLifeMonths")

    if (
        type(useful_life) is not int
        or useful_life < 12
        or useful_life > 120
    ):
        raise ValueError("Invalid estimated useful life.")

    suggestion["usefulLifeMonths"] = useful_life

    production_date = result.get("estimatedProductionDate")

    if production_date is not None:
        if not isinstance(production_date, str):
            raise ValueError(
                "estimatedProductionDate must be a string or null."
            )

        production_date = production_date.strip() or None

        if production_date is not None:
            try:
                datetime.strptime(production_date, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(
                    "estimatedProductionDate must use YYYY-MM-DD."
                ) from exc

    suggestion["estimatedProductionDate"] = production_date

    if not suggestion["category"] or not suggestion["description"]:
        raise ValueError("Category and description are required.")

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
