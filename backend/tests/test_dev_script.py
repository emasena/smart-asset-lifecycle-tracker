import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV_SCRIPT = ROOT / "scripts" / "dev.sh"

# Stands in for the AWS CLI: credentials always check out, every Lambda invoke
# returns FAKE_LAMBDA_RESPONSE, and stack outputs come from FAKE_STACK_OUTPUT.
FAKE_AWS = """#!/usr/bin/env bash
case "$1 $2" in
  "sts get-caller-identity") echo 123456789012 ;;
  "lambda invoke") printf '%s' "$FAKE_LAMBDA_RESPONSE" > "${@: -1}" ;;
  "cloudformation describe-stacks") echo "${FAKE_STACK_OUTPUT:-None}" ;;
  *) echo "unexpected aws call: $*" >&2; exit 1 ;;
esac
"""


@unittest.skipUnless(shutil.which("bash"), "bash is required to run scripts/dev.sh")
class DevScriptTests(unittest.TestCase):
    def setUp(self):
        self.bin_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bin_dir)
        for name, body in (("aws", FAKE_AWS), ("sam", "#!/usr/bin/env bash\nexit 0\n")):
            path = Path(self.bin_dir) / name
            path.write_text(body)
            path.chmod(0o755)

    def run_script(self, *args, **env):
        return subprocess.run(
            ["bash", str(DEV_SCRIPT), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
                "ENVIRONMENT": "dev",
                "STACK_NAME": "smart-asset-tracker-dev",
                **env,
            },
        )

    def seed(self, response):
        return self.run_script("seed", FAKE_LAMBDA_RESPONSE=json.dumps(response))

    def test_seed_succeeds_when_assets_are_created(self):
        result = self.seed({"statusCode": 201, "body": "{}"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created", result.stdout)

    def test_seed_treats_existing_tags_as_success(self):
        result = self.seed({"statusCode": 409, "body": "{}"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already present", result.stdout)

    def test_seed_fails_on_unexpected_status(self):
        result = self.seed({"statusCode": 400, "body": '{"message": "bad asset"}'})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Seed failed", result.stderr)
        self.assertIn("status 400", result.stderr)

    def test_seed_fails_when_lambda_errors_without_status_code(self):
        result = self.seed({"errorMessage": "boom", "errorType": "KeyError"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status None", result.stderr)

    def test_env_fails_without_writing_when_stack_output_is_missing(self):
        env_file = ROOT / "frontend" / ".env"
        before = env_file.read_bytes() if env_file.exists() else None

        result = self.run_script("env", FAKE_STACK_OUTPUT="None")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has no output UserPoolId", result.stderr)
        after = env_file.read_bytes() if env_file.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
