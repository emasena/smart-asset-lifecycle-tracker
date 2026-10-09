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

## Asset access patterns

| Access pattern | Implementation |
|---|---|
| Create asset | Conditional `TransactWriteItems` (asset item + asset-tag lock item) |
| View asset by ID | Strongly consistent `GetItem` |
| Administrator and Auditor listing | Paginated `Scan` |
| Employee listing | `Query` on `AssignedUserIndex` using the Cognito `sub` claim |
| Manager and Technician listing | `Query` on `DepartmentIndex` using the Cognito `custom:department` claim |
| Continue a large result set | Return and accept an encoded `nextToken` |

## Global secondary indexes

| Index | Partition key | Purpose |
|---|---|---|
| `AssignedUserIndex` | `assignedUserId` | Find assets assigned to a particular employee |
| `DepartmentIndex` | `department` | Find assets belonging to a particular department |

DynamoDB returns results in pages. When more results are available, the API returns a `nextToken`, which the frontend can use to load the next page.

Optional index fields that are empty or unknown are omitted from the DynamoDB item because a global secondary index key cannot contain an empty string or `null`.

Financial values are stored as DynamoDB numbers created from Python `Decimal`. Unknown optional data is stored as `null`, never guessed.

## Maintenance history records

Maintenance events use the asset partition and a date-ordered sort key:

```text
PK = ASSET#<assetId>
SK = MAINTENANCE#<performedDate>#<maintenanceId>