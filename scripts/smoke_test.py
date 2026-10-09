#!/usr/bin/env python3
"""Smoke-test a deployed dev or test stack and record the results as Markdown.

The script calls each deployed Lambda directly with synthetic Cognito claims,
the same way `scripts/dev.sh seed` does. That exercises every execution role
against real AWS resources without needing Cognito users or passwords. It then
scans the functions' logs for authorization failures.

Usage:
  python3 scripts/smoke_test.py [--env dev|test] [--stack NAME] [--image PHOTO] [--output FILE] [--keep]

It needs only the Python standard library and a configured AWS CLI. Data it
creates is tagged SMOKE-<timestamp> and removed at the end unless --keep is set.
"""

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zlib
from datetime import datetime, timezone

SAMPLE_PHOTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "sample-data", "images", "dell-latitude-5420-demo.jpg")

LOG_PATTERN = '?AccessDenied ?AccessDeniedException ?AuthorizationError ?"is not authorized"'


class SmokeTest:
    def __init__(self, env, region, image=None, stack=None):
        self.env = env
        self.image = image
        self.region = region
        self.stack = stack or f"smart-asset-tracker-{env}"
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.started_ms = int(time.time() * 1000)
        self.results = []
        self.asset_id = None
        self.tags = []
        self.photo_key = None
        self.claimed_key = None
        self.photo_url = None
        self.functions = {
            "api": f"smart-asset-api-{env}",
            "upload": f"smart-asset-photo-upload-{env}",
            "analysis": f"smart-asset-photo-analysis-{env}",
            "analysis_api": f"smart-asset-photo-analysis-api-{env}",
            "scheduler": f"smart-asset-maintenance-scheduler-{env}",
        }
        self.department = f"SMOKE{self.run_id}"
        self.employee_sub = f"smoke-employee-{self.run_id}"
        self.technician_sub = f"smoke-technician-{self.run_id}"

    # --- helpers -----------------------------------------------------------

    def aws(self, *args, check=True):
        result = subprocess.run(
            ["aws", "--region", self.region, "--output", "json", *args],
            capture_output=True, text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"aws {args[0]} failed")
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            # Some commands (aws s3 rm) print plain text, not JSON.
            return {}

    def record(self, area, check, passed, detail=""):
        self.results.append((area, check, "PASS" if passed else "FAIL", detail))
        print(f"[{'PASS' if passed else 'FAIL'}] {area}: {check}" + (f" ({detail})" if detail else ""))

    def step(self, area, check, fn):
        try:
            passed, detail = fn()
        except Exception as exc:  # noqa: BLE001 - every failure is reported, not raised
            passed, detail = False, (str(exc).strip() or type(exc).__name__).splitlines()[0][:200]
        self.record(area, check, passed, detail)
        return passed

    def invoke(self, function, event):
        with tempfile.TemporaryDirectory() as tmp:
            payload, output = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.json")
            with open(payload, "w") as handle:
                json.dump(event, handle)
            meta = self.aws(
                "lambda", "invoke", "--function-name", self.functions[function],
                "--cli-binary-format", "raw-in-base64-out",
                "--payload", f"fileb://{payload}", output,
            )
            with open(output) as handle:
                body = json.load(handle)
        if meta.get("FunctionError"):
            raise RuntimeError(f"{self.functions[function]} raised {body.get('errorType')}: {body.get('errorMessage')}")
        return body

    def api(self, function, method, resource, claims, body=None, path=None, query=None):
        event = {
            "httpMethod": method,
            "resource": resource,
            "pathParameters": path,
            "queryStringParameters": query,
            "requestContext": {"authorizer": {"claims": claims}},
            "body": json.dumps(body) if body is not None else None,
        }
        response = self.invoke(function, event)
        return response["statusCode"], json.loads(response.get("body") or "{}")

    def claims(self, role):
        return {
            "Administrator": {"sub": f"smoke-admin-{self.run_id}", "cognito:groups": "[Administrator]"},
            "Technician": {"sub": self.technician_sub, "cognito:groups": "[Technician]",
                           "custom:department": self.department},
            "Manager": {"sub": f"smoke-manager-{self.run_id}", "cognito:groups": "[Manager]",
                        "custom:department": self.department},
            "Employee": {"sub": self.employee_sub, "cognito:groups": "[Employee]"},
        }[role]

    def ddb_key(self, pk, sk):
        return json.dumps({"PK": {"S": pk}, "SK": {"S": sk}})

    def stack_output(self, key):
        stacks = self.aws("cloudformation", "describe-stacks", "--stack-name", self.stack)["Stacks"]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
        if key not in outputs:
            raise RuntimeError(f"stack has no {key} output; deploy the current template first")
        return outputs[key]

    # --- checks ------------------------------------------------------------

    def run(self):
        if not self.step("Stack", f"{self.stack} is deployed", self.check_stack):
            return
        if not self.asset_created():
            return
        self.step("Listing", "Administrator list (table Scan)", lambda: self.check_list("Administrator"))
        self.step("Listing", "Manager list (DepartmentIndex Query)", lambda: self.check_list("Manager"))
        self.step("Listing", "Technician list (DepartmentIndex Query)", lambda: self.check_list("Technician"))
        self.step("Listing", "Employee list (AssignedUserIndex Query)", lambda: self.check_list("Employee"))
        self.step("Asset tag", "Change tag (TransactWriteItems with DeleteItem)", self.check_tag_change)
        self.step("Asset tag", "Old tag reservation removed", self.check_old_tag_released)
        if self.step("Photo", "Upload form issued (PhotoUploadFunction)", self.check_upload_form):
            self.step("Photo", "Presigned POST over HTTPS accepted", self.check_upload)
            self.step("Photo", "Presigned POST over HTTP denied by bucket policy", self.check_upload_http_denied)
            self.step("Photo", "Analysis completes (S3 read, Bedrock, DynamoDB)", self.check_analysis)
            self.step("Photo", "Photo claimed on save and viewable (copy, delete, presigned GET)",
                  self.check_photo_view)
            self.step("Photo", "Presigned GET over HTTP denied by bucket policy", self.check_photo_http_denied)
        self.step("Maintenance", "Record created (PutItem)", self.check_maintenance_create)
        self.step("Maintenance", "Record moved to a new date (TransactWriteItems with Delete)",
                  self.check_maintenance_move)
        self.step("Maintenance", "Record deleted by Administrator (DeleteItem)", self.check_maintenance_delete)
        self.step("Maintenance", "AI recommendation (Bedrock via inference profile)", self.check_recommendation)
        self.step("Maintenance", "Topic encrypted with alias/aws/sns", self.check_topic_encryption)
        self.step("Maintenance", "Scheduler publishes to the encrypted topic", self.check_scheduler)
        self.step("Maintenance", "Publish over HTTP denied by topic policy", self.check_topic_http_denied)
        self.step("Maintenance", "Schedule dead-letter queue exists", self.check_dlq)

    def check_stack(self):
        stack = self.aws("cloudformation", "describe-stacks", "--stack-name", self.stack)["Stacks"][0]
        self.bucket = self.stack_output("AssetPhotoBucketName")
        self.topic_arn = self.stack_output("MaintenanceNotificationTopicArn")
        return stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}, stack["StackStatus"]

    def asset_created(self):
        tag = f"SMOKE-{self.run_id}"
        self.tags.append(tag)
        asset = {
            "assetTag": tag, "category": "Laptop", "description": "Smoke test asset",
            "purchaseDate": "2024-01-10", "inServiceDate": "2024-01-15",
            "purchaseValue": "1200.00", "salvageValue": "100.00", "usefulLifeMonths": 36,
            "condition": "Good", "status": "Available",
            "department": self.department, "assignedUserId": self.employee_sub,
        }

        def create():
            status, body = self.api("api", "POST", "/assets", self.claims("Administrator"), asset)
            self.asset_id = body.get("assetId")
            return status == 201 and bool(self.asset_id), f"HTTP {status} {self.asset_id or body}"

        return self.step("Setup", "Create smoke asset (PutItem, TransactWriteItems)", create)

    def check_list(self, role):
        status, body = self.api("api", "GET", "/assets", self.claims(role))
        if status != 200:
            return False, f"HTTP {status} {body}"
        if role == "Administrator":
            return True, f"{body['count']} assets on first page"
        ids = [item.get("assetId") for item in body["items"]]
        return self.asset_id in ids, f"{len(ids)} assets, smoke asset {'found' if self.asset_id in ids else 'missing'}"

    def check_tag_change(self):
        new_tag = f"SMOKE-{self.run_id}-B"
        status, body = self.api("api", "PUT", "/assets/{assetId}", self.claims("Administrator"),
                                {"assetTag": new_tag}, path={"assetId": self.asset_id})
        if status == 200:
            self.tags.append(new_tag)
        return status == 200, f"HTTP {status}" + ("" if status == 200 else f" {body}")

    def check_old_tag_released(self):
        item = self.aws("dynamodb", "get-item", "--table-name", f"smart-asset-tracker-{self.env}",
                        "--key", self.ddb_key(f"ASSET_TAG#{self.tags[0]}", "UNIQUE"), "--consistent-read")
        return "Item" not in item, "reservation deleted" if "Item" not in item else "reservation still present"

    def check_upload_form(self):
        status, body = self.api("upload", "POST", "/photo-uploads", self.claims("Technician"),
                                {"contentType": self.content_type()})
        self.upload = body
        self.photo_key = body.get("key")
        return status == 200 and bool(self.photo_key), f"HTTP {status}"

    def _post_form(self, url):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in self.upload["fields"].items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        photo = open(self.image, "rb").read() if self.image else sample_png()
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke"\r\n'
                     f"Content-Type: {self.content_type()}\r\n\r\n".encode() + photo + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return http_status(request)

    def content_type(self):
        return "image/jpeg" if self.image and self.image.lower().endswith((".jpg", ".jpeg")) else "image/png"

    def check_upload(self):
        status = self._post_form(self.upload["url"])
        return status == 204, f"HTTP {status}"

    def check_upload_http_denied(self):
        status = self._post_form(self.upload["url"].replace("https://", "http://", 1))
        return status == 403, f"HTTP {status}"

    def check_analysis(self):
        deadline = time.time() + 120
        status = "Processing"
        while time.time() < deadline:
            code, body = self.api("analysis_api", "GET", "/photo-analysis", self.claims("Technician"),
                                  query={"key": self.photo_key})
            status = body.get("status", f"HTTP {code}")
            if status in {"Ready", "Failed"}:
                break
            time.sleep(5)
        detail = f"status {status}"
        if status == "Failed" and not self.image:
            # The generated PNG is a plain square, so the model may not be able
            # to classify it. A real asset photo gives a meaningful result.
            detail += "; rerun with --image <asset photo>"
        return status == "Ready", detail

    def check_photo_view(self):
        status, body = self.api("api", "PUT", "/assets/{assetId}", self.claims("Administrator"),
                                {"imageKey": self.photo_key}, path={"assetId": self.asset_id})
        if status != 200:
            return False, f"attach photo HTTP {status} {body}"
        self.claimed_key = "claimed/" + self.photo_key[len("pending/"):]
        status, body = self.api("api", "GET", "/assets/{assetId}", self.claims("Administrator"),
                                path={"assetId": self.asset_id})
        if body.get("imageKey") != self.claimed_key:
            return False, f"imageKey is {body.get('imageKey')}, expected the claimed/ copy"
        pending = self.aws("s3api", "head-object", "--bucket", self.bucket, "--key", self.photo_key, check=False)
        if pending:
            return False, "pending/ object was not removed after the claim"
        status, body = self.api("api", "GET", "/assets/{assetId}/photo", self.claims("Administrator"),
                                path={"assetId": self.asset_id})
        if status != 200:
            return False, f"HTTP {status} {body}"
        self.photo_url = body["photoUrl"]
        fetched = http_status(urllib.request.Request(self.photo_url))
        return fetched == 200, (f"claimed to claimed/, pending removed, download HTTP {fetched}, "
                                f"analysis {body.get('analysisStatus')}")

    def check_photo_http_denied(self):
        if not self.photo_url:
            return False, "skipped: no presigned URL from the previous check"
        status = http_status(urllib.request.Request(self.photo_url.replace("https://", "http://", 1)))
        return status == 403, f"HTTP {status}"

    def maintenance_records(self):
        status, body = self.api("api", "GET", "/assets/{assetId}/maintenance", self.claims("Administrator"),
                                path={"assetId": self.asset_id})
        if status != 200:
            raise RuntimeError(f"list maintenance HTTP {status} {body}")
        return body["items"]

    def check_maintenance_create(self):
        status, body = self.api("api", "POST", "/assets/{assetId}/maintenance", self.claims("Administrator"),
                                {"maintenanceType": "Inspection", "description": "Smoke test inspection",
                                 "performedDate": "2024-06-01"}, path={"assetId": self.asset_id})
        self.maintenance_id = body.get("maintenanceId")
        return status == 201 and bool(self.maintenance_id), f"HTTP {status}"

    def check_maintenance_move(self):
        status, body = self.api("api", "PUT", "/assets/{assetId}/maintenance/{maintenanceId}",
                                self.claims("Administrator"),
                                {"maintenanceType": "Inspection", "description": "Smoke test inspection",
                                 "performedDate": "2024-07-01"},
                                path={"assetId": self.asset_id, "maintenanceId": self.maintenance_id})
        if status != 200:
            return False, f"HTTP {status} {body}"
        dates = [item.get("performedDate") for item in self.maintenance_records()]
        return dates == ["2024-07-01"], f"records after move: {dates}"

    def check_maintenance_delete(self):
        status, body = self.api("api", "DELETE", "/assets/{assetId}/maintenance/{maintenanceId}",
                                self.claims("Administrator"),
                                path={"assetId": self.asset_id, "maintenanceId": self.maintenance_id})
        if status != 200:
            return False, f"HTTP {status} {body}"
        remaining = len(self.maintenance_records())
        return remaining == 0, f"{remaining} records left"

    def check_recommendation(self):
        status, body = self.api("api", "POST", "/assets/{assetId}/maintenance-recommendation",
                                self.claims("Administrator"), path={"assetId": self.asset_id})
        return status == 200 and bool(body.get("aiRecommendation")), f"HTTP {status}"

    def check_topic_encryption(self):
        attributes = self.aws("sns", "get-topic-attributes", "--topic-arn", self.topic_arn)["Attributes"]
        key = attributes.get("KmsMasterKeyId", "")
        return key == "alias/aws/sns", key or "not encrypted"

    def check_scheduler(self):
        # A far-future run date makes the smoke asset overdue, so the run must publish.
        report = self.invoke("scheduler", {"time": "2099-01-01T13:00:00Z", "source": "smoke-test"})
        sent = report.get("notificationSent") is True
        return sent, f"evaluated {report.get('evaluatedCount')}, alerts {report.get('alertCount')}, notificationSent {sent}"

    def check_topic_http_denied(self):
        result = subprocess.run(
            ["aws", "--region", self.region, "sns", "publish", "--topic-arn", self.topic_arn,
             "--endpoint-url", f"http://sns.{self.region}.amazonaws.com",
             "--subject", "Smoke test: plaintext publish", "--message", "This publish should have been denied."],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return False, "plaintext publish was accepted"
        denied = "AuthorizationError" in result.stderr or "not authorized" in result.stderr
        return denied, "AuthorizationError" if denied else result.stderr.strip().splitlines()[-1][:200]

    def check_dlq(self):
        resources = self.aws("cloudformation", "describe-stack-resources", "--stack-name", self.stack)["StackResources"]
        queues = [r["PhysicalResourceId"] for r in resources
                  if r["ResourceType"] == "AWS::SQS::Queue" and "DailyMaintenanceCheck" in r["LogicalResourceId"]]
        if not queues:
            return False, "no queue in stack"
        depth = self.aws("sqs", "get-queue-attributes", "--queue-url", queues[0],
                         "--attribute-names", "ApproximateNumberOfMessages")["Attributes"]
        return True, f"{queues[0].rsplit('/', 1)[-1]}, {depth['ApproximateNumberOfMessages']} messages"

    def scan_logs(self):
        if not hasattr(self, "bucket"):
            return
        time.sleep(15)  # give CloudWatch Logs time to ingest the last invocations
        for function in self.functions.values():
            def scan(function=function):
                events = self.aws("logs", "filter-log-events", "--log-group-name", f"/aws/lambda/{function}",
                                  "--start-time", str(self.started_ms), "--filter-pattern", LOG_PATTERN)
                hits = events.get("events", [])
                return not hits, f"{len(hits)} matches" + (f": {hits[0]['message'].strip()[:160]}" if hits else "")
            self.step("Logs", f"No authorization errors in {function}", scan)

    def cleanup(self):
        table = f"smart-asset-tracker-{self.env}"
        keys = [self.ddb_key(f"ASSET_TAG#{tag}", "UNIQUE") for tag in self.tags]
        if self.asset_id:
            keys.append(self.ddb_key(f"ASSET#{self.asset_id}", "METADATA"))
            history = self.aws(
                "dynamodb", "query", "--table-name", table, "--projection-expression", "PK, SK",
                "--key-condition-expression", "PK = :pk AND begins_with(SK, :maintenance)",
                "--expression-attribute-values",
                json.dumps({":pk": {"S": f"ASSET#{self.asset_id}"}, ":maintenance": {"S": "MAINTENANCE#"}}),
                check=False,
            )
            keys += [json.dumps({"PK": item["PK"], "SK": item["SK"]}) for item in history.get("Items", [])]
        if self.photo_key:
            keys.append(self.ddb_key(f"PHOTO#{self.photo_key}", "ANALYSIS"))
            for key in (self.photo_key, self.claimed_key):
                if key:
                    self.aws("s3", "rm", f"s3://{self.bucket}/{key}", check=False)
        for key in keys:
            self.aws("dynamodb", "delete-item", "--table-name", table, "--key", key, check=False)
        print(f"Removed smoke test data for run {self.run_id}.")

    def report(self):
        failed = sum(1 for result in self.results if result[2] == "FAIL")
        lines = [
            f"## Smoke test: `{self.stack}` ({self.region})",
            "",
            f"Run `{self.run_id}` at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, "
            f"commit `{git_commit()}`. **{len(self.results) - failed} passed, {failed} failed.**",
            "",
            "Lambdas were invoked directly with synthetic Cognito claims, so each check runs under the "
            "function's real execution role.",
            "",
            "| Area | Check | Result | Detail |",
            "|---|---|---|---|",
        ]
        for area, check, outcome, detail in self.results:
            mark = "✅" if outcome == "PASS" else "❌"
            lines.append(f"| {area} | {check} | {mark} {outcome} | {detail.replace('|', '/')} |")
        return "\n".join(lines) + "\n", failed


def sample_png(size=64):
    """A small solid-colour PNG, generated so the script needs no image file."""
    row = b"\x00" + b"\x40\x70\xb0" * size
    raw = zlib.compress(row * size)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def http_status(request):
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def git_commit():
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", default=os.environ.get("ENVIRONMENT", "dev"), choices=["dev", "test"])
    parser.add_argument("--stack", default=os.environ.get("STACK_NAME"),
                        help="Stack name (default: smart-asset-tracker-<env>)")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--image", help="JPEG or PNG asset photo to upload (default: the sample laptop photo)")
    parser.add_argument("--output", default="smoke-test-results.md", help="Markdown report path")
    parser.add_argument("--keep", action="store_true", help="Keep the smoke asset, photo and analysis")
    args = parser.parse_args()
    if args.image and not os.path.isfile(args.image):
        parser.error(f"--image file not found: {args.image}")
    if not args.image and os.path.isfile(SAMPLE_PHOTO):
        args.image = os.path.normpath(SAMPLE_PHOTO)

    test = SmokeTest(args.env, args.region, args.image, args.stack)
    try:
        test.run()
        test.scan_logs()
    finally:
        if not args.keep and hasattr(test, "bucket"):
            test.cleanup()

    report, failed = test.report()
    with open(args.output, "w") as handle:
        handle.write(report)
    print(f"\nWrote {args.output}. Post it with: gh pr comment <PR> --body-file {args.output}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
