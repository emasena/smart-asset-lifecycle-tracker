# Cognito Groups and Application Permissions

## Authentication

The Smart Asset Lifecycle Tracker uses Amazon Cognito User Pools for user authentication.

Amazon API Gateway uses a Cognito authorizer to validate the ID token before allowing access to protected API endpoints. The Lambda functions then enforce role-based and asset-level authorization.

## Groups and Permissions

| Cognito group | Asset access | Create assets | Update assets | Maintenance access | AI recommendations |
|---|---|---:|---:|---|---:|
| Administrator | All assets | Yes | All fields | View and create | Yes |
| Auditor | All assets | No | No | View only | No |
| Manager | Assets in assigned department | No | No | View department history | No |
| Technician | Assets in assigned department | Yes | Operational fields only | View and create | Yes |
| Employee | Assets assigned to the user | No | No | View authorized records only | No |

## Authorization Rules

### Administrator

Administrators have full application access, including:

- Creating assets
- Viewing all assets
- Updating all supported asset fields
- Viewing and creating maintenance records
- Generating AI-assisted maintenance recommendations
- Viewing authorized private photographs

### Auditor

Auditors have read-only access:

- View all assets
- View asset maintenance history
- View authorized private photographs
- Cannot create or update assets
- Cannot create maintenance records
- Cannot generate AI maintenance recommendations

### Manager

Managers are restricted to assets matching the `custom:department` claim in their Cognito identity:

- View department assets
- View maintenance history for department assets
- View photographs for department assets
- Cannot create or modify assets
- Cannot create maintenance records

### Technician

Technicians are restricted to their assigned department:

- View department assets
- Create assets
- Update approved operational fields
- Create maintenance records
- Generate AI-assisted maintenance recommendations
- Access photographs for authorized assets

### Employee

Employees can access only assets where:

```text
assignedUserId == authenticated Cognito subject
