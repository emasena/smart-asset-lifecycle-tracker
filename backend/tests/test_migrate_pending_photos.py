"""Tests the one-time pending/ -> claimed/ backfill script."""

import importlib.util
import pathlib
import unittest
from unittest.mock import MagicMock, patch


SCRIPT = pathlib.Path(__file__).parents[2] / "scripts" / "migrate_pending_photos.py"
spec = importlib.util.spec_from_file_location("migrate_pending_photos", SCRIPT)
migrate_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_script)


class _ClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


def _item(asset_id, key):
    return {"PK": f"ASSET#{asset_id}", "SK": "METADATA", "assetId": asset_id, "imageKey": key}


class MigratePendingPhotosTests(unittest.TestCase):
    def setUp(self):
        self.table = MagicMock(name="table")
        self.s3 = MagicMock(name="s3")

    def _run(self, items, apply=True):
        self.table.scan.return_value = {"Items": items}
        return migrate_script.migrate(self.table, self.s3, "photos", apply=apply)

    def test_dry_run_reports_without_changing_anything(self):
        result = self._run([_item("AST-1", "pending/u/a.jpg")], apply=False)

        self.assertEqual(result["migrated"], [("AST-1", "pending/u/a.jpg")])
        self.s3.copy_object.assert_not_called()
        self.table.update_item.assert_not_called()
        self.s3.delete_object.assert_not_called()

    def test_apply_copies_updates_asset_then_deletes_pending(self):
        result = self._run([_item("AST-1", "pending/u/a.jpg")])

        self.assertEqual(result["migrated"], [("AST-1", "pending/u/a.jpg")])
        self.s3.copy_object.assert_called_once_with(
            Bucket="photos",
            CopySource={"Bucket": "photos", "Key": "pending/u/a.jpg"},
            Key="claimed/u/a.jpg",
        )
        update = self.table.update_item.call_args.kwargs
        self.assertEqual(update["Key"], {"PK": "ASSET#AST-1", "SK": "METADATA"})
        self.assertEqual(update["ConditionExpression"], "imageKey = :pending")
        self.assertEqual(update["ExpressionAttributeValues"][":claimed"], "claimed/u/a.jpg")
        self.s3.delete_object.assert_called_once_with(Bucket="photos", Key="pending/u/a.jpg")

    def test_scan_follows_pagination(self):
        self.table.scan.side_effect = [
            {"Items": [_item("AST-1", "pending/u/a.jpg")], "LastEvaluatedKey": {"PK": "x"}},
            {"Items": [_item("AST-2", "pending/u/b.jpg")]},
        ]

        result = migrate_script.migrate(self.table, self.s3, "photos", apply=True)

        self.assertEqual([asset for asset, _ in result["migrated"]], ["AST-1", "AST-2"])
        self.assertEqual(self.table.scan.call_args_list[1].kwargs["ExclusiveStartKey"], {"PK": "x"})

    def test_missing_source_without_claimed_copy_is_reported_and_asset_untouched(self):
        self.s3.copy_object.side_effect = _ClientError("NoSuchKey")
        self.s3.head_object.side_effect = _ClientError("404")

        result = self._run([_item("AST-1", "pending/u/gone.jpg")])

        self.assertEqual(result["missing"], [("AST-1", "pending/u/gone.jpg")])
        self.table.update_item.assert_not_called()

    def test_rerun_after_partial_failure_reuses_existing_claimed_copy(self):
        self.s3.copy_object.side_effect = _ClientError("NoSuchKey")

        result = self._run([_item("AST-1", "pending/u/a.jpg")])

        self.assertEqual(result["migrated"], [("AST-1", "pending/u/a.jpg")])
        self.s3.head_object.assert_called_once_with(Bucket="photos", Key="claimed/u/a.jpg")
        self.table.update_item.assert_called_once()

    def test_concurrent_edit_is_reported_and_pending_photo_kept(self):
        self.table.update_item.side_effect = _ClientError("ConditionalCheckFailedException")

        result = self._run([_item("AST-1", "pending/u/a.jpg")])

        self.assertEqual(result["failed"], [("AST-1", "pending/u/a.jpg", "ConditionalCheckFailedException")])
        self.s3.delete_object.assert_not_called()

    def test_cleanup_failure_still_counts_as_migrated(self):
        self.s3.delete_object.side_effect = _ClientError("AccessDenied")

        result = self._run([_item("AST-1", "pending/u/a.jpg")])

        self.assertEqual(result["migrated"], [("AST-1", "pending/u/a.jpg")])
        self.assertEqual(result["failed"], [])


class VerifyGateTests(unittest.TestCase):
    def _main(self, items, *flags):
        boto3 = MagicMock(name="boto3")
        table = boto3.resource.return_value.Table.return_value
        table.scan.return_value = {"Items": items}
        with patch.dict("sys.modules", {"boto3": boto3}), patch("builtins.print"):
            code = migrate_script.main(["--table", "t", "--bucket", "b", *flags])
        return code, table, boto3.client.return_value

    def test_verify_fails_while_pending_references_remain(self):
        code, table, s3 = self._main([_item("AST-1", "pending/u/a.jpg")], "--verify")

        self.assertEqual(code, 1)
        table.update_item.assert_not_called()
        s3.copy_object.assert_not_called()

    def test_verify_passes_when_no_pending_references_remain(self):
        code, _, _ = self._main([], "--verify")

        self.assertEqual(code, 0)

    def test_plain_dry_run_still_exits_zero_with_pending_references(self):
        code, _, _ = self._main([_item("AST-1", "pending/u/a.jpg")])

        self.assertEqual(code, 0)

    def test_verify_and_apply_are_mutually_exclusive(self):
        with patch.dict("sys.modules", {"boto3": MagicMock()}), patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                migrate_script.main(["--table", "t", "--bucket", "b", "--verify", "--apply"])


if __name__ == "__main__":
    unittest.main()
