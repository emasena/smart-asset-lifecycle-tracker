# Migrating existing photos out of `pending/`

New uploads land under `pending/` and are copied to `claimed/` when an asset is saved (see `_claim_photo` in `backend/asset_api/app.py`). The stack's `ExpireUnclaimedPendingUploads` lifecycle rule deletes everything under `pending/` after 7 days, and is controlled by the `PendingUploadExpiration` parameter (default `Disabled`).

Assets saved **before** claiming existed still reference `pending/` keys. If expiration is enabled first, those photos are deleted and the assets point at missing objects. Backfill them with `scripts/migrate_pending_photos.py` first.

For each asset whose `imageKey` starts with `pending/`, the script copies the photo to `claimed/`, updates the asset (only if `imageKey` hasn't changed in the meantime), then deletes the pending copy. It is idempotent, so it is safe to re-run. A photo whose source object is already gone is reported and the asset is left alone. Photo-analysis records live in DynamoDB (keyed by the original upload key), so they are not affected by S3 expiration.

## Order of operations

Run per environment. The order closes the window in which a write could add a new `pending/` reference between the backfill and the lifecycle rule going live: expiration stays **off** until the backfill is verified. Replace `ENVIRONMENT` with the stack you're migrating (e.g. `test`; run `dev` only once approved).

If this environment also has pre-existing log groups, import them first (see `docs/cloudwatch-monitoring.md`).

```bash
ENVIRONMENT=test
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
TABLE=smart-asset-tracker-${ENVIRONMENT}
BUCKET=smart-asset-tracker-${ENVIRONMENT}-photos-${ACCOUNT}-us-east-1   # <stack-name>-photos-<account>-<region>
```

1. **Deploy with expiration disabled.** This ships the claiming code, so from now on every save claims its photo and no new `pending/` references can appear. `--parameter-overrides` replaces the `samconfig.toml` values, so pass `Environment` too:

   ```bash
   sam deploy --template-file infrastructure/template.yaml \
     --parameter-overrides Environment=${ENVIRONMENT} PendingUploadExpiration=Disabled
   ```

2. **Backfill.** Dry run first, then apply:

   ```bash
   python scripts/migrate_pending_photos.py --table "$TABLE" --bucket "$BUCKET"
   python scripts/migrate_pending_photos.py --table "$TABLE" --bucket "$BUCKET" --apply
   ```

   Review the "source photo already missing" and "failed" sections. Missing photos had already expired or been removed and need to be re-uploaded by hand; failures can be retried by re-running `--apply`.

3. **Gate: verify nothing references `pending/`.** This is read-only and exits non-zero while any asset still does. Do not continue until it exits 0:

   ```bash
   python scripts/migrate_pending_photos.py --table "$TABLE" --bucket "$BUCKET" --verify
   ```

4. **Enable expiration** by redeploying with the same parameters and `PendingUploadExpiration=Enabled`.

5. **Spot-check.** Confirm the rule is active and a migrated photo still loads:

   ```bash
   aws s3api get-bucket-lifecycle-configuration --bucket "$BUCKET" --query 'Rules[].[ID,Status]'
   ```

The stack name in `BUCKET` assumes the default `smart-asset-tracker-<environment>` naming from `samconfig.toml`; check the `AssetPhotoBucketName` stack output if yours differs. A brand-new environment has nothing to backfill, so step 3 passes immediately.
