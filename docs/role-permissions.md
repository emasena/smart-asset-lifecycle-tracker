# Role and SailPoint access model

## Application permissions

| Action | Employee | Technician | Manager | Administrator | Auditor |
|---|---:|---:|---:|---:|---:|
| View assigned assets | Yes | Yes | Yes | Yes | Yes |
| View department assets | No | Yes | Yes | Yes | Yes |
| View all assets | No | Yes | No | Yes | Yes |
| Create asset | No | Yes | No | Yes | No |
| Set assignment fields (`assignedUserId`, `department`) on create | No | No | No | Yes | No |
| Update operational fields | No | Yes | No | Yes | No |
| Update financial/assignment fields | No | No | No | Yes | No |
| Record maintenance | No | Planned | No | Planned | No |
| Manage users and assignments | No | No | No | Planned | No |

## SailPoint mapping

| SailPoint access profile | Cognito entitlement |
|---|---|
| Asset Tracker Employee | `Employee` group |
| Asset Tracker Technician | `Technician` group |
| Asset Tracker Manager | `Manager` group |
| Asset Tracker Administrator | `Administrator` group |
| Asset Tracker Auditor | `Auditor` group |

## Lifecycle behavior

- Joiner: provision the Cognito account and baseline Employee access.
- Mover: recalculate department and role access.
- Leaver: remove governed groups and disable the Cognito account.
- Temporary access: approve Technician or Manager access with an expiration date.
- Certification: periodically review Administrator, Technician, Manager, and Auditor membership.

## Segregation of duties

- `Auditor` conflicts with `Administrator`.
- `Auditor` conflicts with `Technician`.

These policies prevent a user from modifying the same asset records they independently audit.

A `Technician` creating a new asset cannot set `assignedUserId` or `department` — the same restriction that applies when updating an existing asset. Without this, asset creation would be a backdoor around the assignment-field lock on updates.

