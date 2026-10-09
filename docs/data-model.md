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

## Maintenance access patterns

| Access pattern | Implementation |
|---|---|
| Record maintenance | Conditional `PutItem` with SK `MAINTENANCE#<performedDate>#<maintenanceId>` |
| List an asset's history | `Query` on `PK` with `begins_with(SK, "MAINTENANCE#")`, newest first, following `LastEvaluatedKey` through every page |
| Find one record | Same `Query` filtered on `maintenanceId` (the SK embeds the date) |
| Edit, same performed date | `PutItem` on the existing key, conditioned on the stored `updatedAt` being unchanged |
| Edit, new performed date | `TransactWriteItems`: put the new key and delete the old key together; the delete carries the same `updatedAt` condition |
| Delete | Conditional `DeleteItem` (Administrator only) |

`performedBy`, `performedByEmail`, and `createdAt` are set from the authenticated Cognito identity when the record is created and are never taken from the request body, including on edits. Edits add `updatedBy` and `updatedAt`. The client sends the `updatedAt` it last saw as `expectedUpdatedAt` (`null` for a record that has never been edited); a mismatch returns `409 Conflict` instead of overwriting a newer change.

A Technician may edit only records they recorded, on assets in their own `custom:department`. This department check is separate from read access, so a Technician who also holds the Auditor role still cannot change maintenance in other departments.

## Global secondary indexes

| Index | Partition key | Purpose |
|---|---|---|
| `AssignedUserIndex` | `assignedUserId` | Find assets assigned to a particular employee |
| `DepartmentIndex` | `department` | Find assets belonging to a particular department |

DynamoDB returns results in pages. When more results are available, the API returns a `nextToken`, which the frontend can use to load the next page.

Optional index fields that are empty or unknown are omitted from the DynamoDB item because a global secondary index key cannot contain an empty string or `null`.

Financial values are stored as DynamoDB numbers created from Python `Decimal`. Unknown optional data is stored as `null`, never guessed.

