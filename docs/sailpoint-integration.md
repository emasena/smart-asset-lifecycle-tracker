# SailPoint integration design

> **Status: Planned design only — SailPoint is not currently implemented or deployed.**

## Purpose

This document describes a planned integration in which SailPoint Identity Security Cloud or IdentityIQ would govern access to the Asset Tracker. SailPoint is not currently connected to the application. Amazon Cognito is the implemented authentication service and JWT issuer.

## Integration pattern

```text
Authoritative identity source
        -> SailPoint identity profile / identity cube
        -> Role, access profile, approval, and policy evaluation
        -> SailPoint Web Services or custom connector
        -> Private provisioning API
        -> Provisioning Lambda
        -> Amazon Cognito administrative APIs
```

## Planned connector objects

### Account schema

| Attribute | Source |
|---|---|
| `username` | Cognito username |
| `email` | Cognito email attribute |
| `enabled` | Cognito user status |
| `department` | Cognito `custom:department` |
| `groups` | Cognito group membership; multi-valued entitlement |
| `cognitoSub` | Immutable Cognito subject identifier |

### Entitlement schema

Each governed Cognito group is aggregated as an entitlement:

- `Employee`
- `Technician`
- `Manager`
- `Administrator`
- `Auditor`

## Planned provisioning operations

| Operation | Cognito action |
|---|---|
| Create account | `AdminCreateUser` |
| Enable account | `AdminEnableUser` |
| Disable account | `AdminDisableUser` |
| Add entitlement | `AdminAddUserToGroup` |
| Remove entitlement | `AdminRemoveUserFromGroup` |
| Aggregate accounts | `ListUsers` with pagination |
| Aggregate entitlements | `ListGroups` with pagination |

The connector never receives AWS access keys. It calls a dedicated machine endpoint with short-lived authentication. The bridge execution role receives only the listed Cognito permissions for the one project user pool.

## Lifecycle states

| Lifecycle state | Governed behavior |
|---|---|
| Pre-hire | No Asset Tracker access |
| Active | Cognito account plus baseline Employee access |
| Leave | Temporarily disable Cognito account |
| Terminated | Remove groups and disable account |

Manager, Technician, Administrator, and Auditor are governed elevated-access profiles. Elevated access requires approval; temporary access includes an expiration date.

## Policy and certification controls

- Prevent simultaneous `Auditor` and `Administrator` access.
- Prevent simultaneous `Auditor` and `Technician` access.
- Certify Administrator and Technician access quarterly.
- Certify Manager access by department manager.
- Record the request, approval, fulfillment, and revocation trail in SailPoint.

## Planned demonstration scenario

1. Aggregate the five Cognito groups into SailPoint.
2. Request the Technician access profile for a test identity.
3. Approve the request and show the identity added to the Cognito group.
4. Sign in and create an asset successfully.
5. Remove the access profile and show that the restricted API action returns `403`.
6. Attempt the Auditor/Technician combination and show the policy conflict.

## Implementation boundary

The bridge belongs after the Week 1 Cognito/API milestone. This prevents a connector issue from blocking the required manual asset application and preserves a clean separation between governance, authentication, and application authorization.

