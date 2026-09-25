# DynamoDB data model

## Table keys

| Record | PK | SK |
|---|---|---|
| Asset metadata | `ASSET#<assetId>` | `METADATA` |
| Asset-tag lock | `ASSETTAG#<assetTag>` | `UNIQUE` |
| Maintenance event | `ASSET#<assetId>` | `MAINTENANCE#<date>#<maintenanceId>` |
| Recommendation | `ASSET#<assetId>` | `RECOMMENDATION#<timestamp>` |
| Audit history | `ASSET#<assetId>` | `HISTORY#<timestamp>#<eventId>` |

The asset-tag lock record enforces `assetTag` uniqueness. It is written alongside the asset metadata item in a single `TransactWriteItems` call, each conditioned on `attribute_not_exists(PK)`, so a duplicate tag cannot slip through a race between two concurrent creates. Renaming `assetTag` on update deletes the old lock item and creates the new one in the same transaction.

Week 1 uses asset metadata records. The shared partition leaves room for maintenance and immutable history without creating unrelated tables.

## Week 1 access patterns

| Access pattern | Implementation |
|---|---|
| Create asset | Conditional `TransactWriteItems` (asset item + asset-tag lock item) |
| View asset by ID | Strongly consistent `GetItem` |
| Search small demonstration dataset | Filtered `Scan`, maximum 100 evaluated items |
| Employee scope | Compare Cognito `sub` to `assignedUserId` |
| Manager scope | Compare `custom:department` claim to asset department |

The filtered scan is intentionally limited to the ten-record classroom milestone. Before production scale, add indexes or a dedicated search service for the documented query patterns.

Financial values are stored as DynamoDB numbers created from Python `Decimal`. Unknown optional data is stored as `null`, never guessed.

