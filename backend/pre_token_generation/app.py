import json
from urllib.parse import unquote


OKTA_TO_APPLICATION_ROLE = {
    "AWS-Asset-Administrator": "Administrator",
    "AWS-Asset-Technician": "Technician",
    "AWS-Asset-Manager": "Manager",
    "AWS-Asset-Employee": "Employee",
    "AWS-Asset-Auditor": "Auditor",
}

APPLICATION_ROLES = set(OKTA_TO_APPLICATION_ROLE.values())


def _parse_okta_groups(raw_value):
    if not raw_value:
        return set()

    decoded = unquote(raw_value)

    try:
        parsed = json.loads(decoded)
    except (json.JSONDecodeError, TypeError):
        return set()

    if not isinstance(parsed, list):
        return set()

    return {
        value
        for value in parsed
        if isinstance(value, str)
        and value in OKTA_TO_APPLICATION_ROLE
    }


def lambda_handler(event, _context):
    request = event.get("request") or {}
    response = event.setdefault("response", {})
    username = event.get("userName", "")

    group_configuration = request.get("groupConfiguration") or {}
    current_groups = set(
        group_configuration.get("groupsToOverride") or []
    )

    # Native Cognito users retain their existing Cognito groups.
    if not username.startswith("Okta_"):
        response["claimsOverrideDetails"] = {
            "groupOverrideDetails": group_configuration
        }
        return event

    attributes = request.get("userAttributes") or {}
    okta_groups = _parse_okta_groups(
        attributes.get("custom:oktaGroups")
    )

    mapped_roles = {
        OKTA_TO_APPLICATION_ROLE[group]
        for group in okta_groups
    }

    # Example segregation-of-duties control.
    if {"Administrator", "Auditor"}.issubset(mapped_roles):
        raise ValueError(
            "Conflicting Asset Tracker roles: "
            "Administrator and Auditor."
        )

    # For federated users, Okta is authoritative for application roles.
    # Remove manually assigned application roles, but preserve the
    # automatic Cognito identity-provider group.
    preserved_groups = current_groups - APPLICATION_ROLES
    final_groups = sorted(preserved_groups | mapped_roles)

    override = dict(group_configuration)
    override["groupsToOverride"] = final_groups

    response["claimsOverrideDetails"] = {
        "groupOverrideDetails": override
    }

    return event
