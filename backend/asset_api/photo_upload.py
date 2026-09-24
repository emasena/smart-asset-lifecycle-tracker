"""Issue narrowly scoped, short-lived upload forms for private asset photos."""

import base64
import json
import logging
import os
import re
import uuid

import boto3

from domain import parse_groups


LOG = logging.getLogger(__name__)
S3 = boto3.client("s3")
BUCKET = os.environ["ASSET_PHOTO_BUCKET"]
MAX_BYTES = 3_750_000
MIME_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}


def _response(status, data):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(data),
    }


def lambda_handler(event, _context):
    claims = (event.get("requestContext") or {}).get("authorizer") or {}
    claims = claims.get("claims") or {}
    subject = claims.get("sub")
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject):
        return _response(401, {"message": "Sign in to upload a photograph."})

    groups = parse_groups(claims.get("cognito:groups"))
    if not groups.intersection({"Administrator", "Technician"}):
        return _response(403, {"message": "You cannot upload asset photographs."})
    if "Technician" in groups and "Administrator" not in groups and not claims.get("custom:department"):
        return _response(403, {"message": "Your account does not have a department assigned."})

    try:
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _response(400, {"message": "Request body must be valid JSON."})
    if not isinstance(body, dict) or body.get("contentType") not in MIME_EXTENSIONS:
        return _response(400, {"message": "Choose a JPEG or PNG image."})

    content_type = body["contentType"]
    key = f"pending/{subject}/{uuid.uuid4().hex}.{MIME_EXTENSIONS[content_type]}"
    try:
        signed = S3.generate_presigned_post(
            Bucket=BUCKET,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, MAX_BYTES],
            ],
            ExpiresIn=300,
        )
    except Exception:
        LOG.exception("Unable to sign asset photo upload")
        return _response(500, {"message": "Could not prepare an upload. Try again."})
    return _response(200, {
        "url": signed["url"],
        "fields": signed["fields"],
        "key": key,
        "expiresIn": 300,
        "maxBytes": MAX_BYTES,
    })
