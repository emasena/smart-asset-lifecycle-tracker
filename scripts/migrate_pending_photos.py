#!/usr/bin/env python3
"""One-time backfill: move photos that assets already reference out of pending/.

The S3 lifecycle rule expires everything under pending/ after 7 days. Assets
saved before the API started claiming photos still point at pending/ keys, so
run this BEFORE enabling the lifecycle rule (PendingUploadExpiration=Enabled)
in an environment.

Dry-run by default; pass --apply to make changes. Safe to re-run. Pass --verify
(read-only) as the gate before enabling expiration: it exits non-zero while any
asset still references pending/.

    python scripts/migrate_pending_photos.py --table <table> --bucket <bucket>
    python scripts/migrate_pending_photos.py --table <table> --bucket <bucket> --apply
    python scripts/migrate_pending_photos.py --table <table> --bucket <bucket> --verify
"""

import argparse
import sys

PENDING_PREFIX = "pending/"
CLAIMED_PREFIX = "claimed/"
MISSING_CODES = {"NoSuchKey", "404", "NotFound"}


def _code(exc):
    return getattr(exc, "response", {}).get("Error", {}).get("Code")


def _pending_assets(table):
    params = {
        "FilterExpression": "#sk = :sk AND begins_with(imageKey, :prefix)",
        "ExpressionAttributeNames": {"#sk": "SK"},
        "ExpressionAttributeValues": {":sk": "METADATA", ":prefix": PENDING_PREFIX},
    }
    while True:
        page = table.scan(**params)
        yield from page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _copy_to_claimed(s3, bucket, pending_key, claimed_key):
    """Copy the photo; return False if the source is gone and no claimed copy exists."""
    try:
        s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": pending_key},
            Key=claimed_key,
        )
        return True
    except Exception as exc:
        if _code(exc) not in MISSING_CODES:
            raise
    # Source is gone; an earlier run may have copied it before failing to update the asset.
    try:
        s3.head_object(Bucket=bucket, Key=claimed_key)
        return True
    except Exception as exc:
        if _code(exc) not in MISSING_CODES:
            raise
        return False


def migrate(table, s3, bucket, apply=False):
    """Return {"migrated", "missing", "failed"}: lists of (assetId, key[, reason])."""
    result = {"migrated": [], "missing": [], "failed": []}
    for item in _pending_assets(table):
        asset_id, pending_key = item["assetId"], item["imageKey"]
        claimed_key = CLAIMED_PREFIX + pending_key[len(PENDING_PREFIX):]

        if not apply:
            result["migrated"].append((asset_id, pending_key))
            continue

        try:
            if not _copy_to_claimed(s3, bucket, pending_key, claimed_key):
                result["missing"].append((asset_id, pending_key))
                continue
            table.update_item(
                Key={"PK": item["PK"], "SK": item["SK"]},
                UpdateExpression="SET imageKey = :claimed",
                ConditionExpression="imageKey = :pending",
                ExpressionAttributeValues={":claimed": claimed_key, ":pending": pending_key},
            )
        except Exception as exc:
            # The pending object is left in place so the item can be retried.
            result["failed"].append((asset_id, pending_key, _code(exc) or repr(exc)))
            continue

        result["migrated"].append((asset_id, pending_key))
        try:
            s3.delete_object(Bucket=bucket, Key=pending_key)
        except Exception as exc:
            print(f"warning: could not delete {pending_key}: {_code(exc) or exc}", file=sys.stderr)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--table", required=True, help="DynamoDB asset table name")
    parser.add_argument("--bucket", required=True, help="S3 photo bucket name")
    parser.add_argument("--region", default="us-east-1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="make changes (default is a dry run)")
    mode.add_argument(
        "--verify",
        action="store_true",
        help="read-only gate: exit 1 if any asset still references pending/",
    )
    args = parser.parse_args(argv)

    import boto3  # imported here so the migration logic can be tested without it

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    s3 = boto3.client("s3", region_name=args.region)

    result = migrate(table, s3, args.bucket, apply=args.apply)

    verb = "migrated" if args.apply else "would migrate"
    print(f"{verb}: {len(result['migrated'])}")
    for asset_id, key in result["migrated"]:
        print(f"  {asset_id}  {key}")
    print(f"source photo already missing: {len(result['missing'])}")
    for asset_id, key in result["missing"]:
        print(f"  {asset_id}  {key}")
    print(f"failed: {len(result['failed'])}")
    for asset_id, key, reason in result["failed"]:
        print(f"  {asset_id}  {key}  ({reason})")
    if args.verify:
        remaining = len(result["migrated"])
        print(f"verify: {remaining} asset(s) still reference {PENDING_PREFIX}")
        return 1 if remaining else 0
    if not args.apply:
        print("Dry run only. Re-run with --apply to make changes.")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
