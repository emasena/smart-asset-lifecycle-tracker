"""Generate validated AI-assisted maintenance advice."""

import json
import os

import boto3


MODEL_ID = os.environ.get(
    "MAINTENANCE_MODEL_ID",
    "us.amazon.nova-lite-v1:0",
)

MAX_ACTIONS = 5
MAX_TEXT_LENGTH = 500


class MaintenanceAiError(ValueError):
    pass


def _clean_model_json(raw_text):
    if not isinstance(raw_text, str):
        raise MaintenanceAiError(
            "Bedrock response must contain text."
        )

    text = raw_text.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def validate_ai_recommendation(raw_text):
    try:
        result = json.loads(_clean_model_json(raw_text))
    except json.JSONDecodeError as exc:
        raise MaintenanceAiError(
            "Bedrock response must contain valid JSON."
        ) from exc

    if not isinstance(result, dict):
        raise MaintenanceAiError(
            "Bedrock response must be a JSON object."
        )

    actions = result.get("recommendedActions")

    if not isinstance(actions, list):
        raise MaintenanceAiError(
            "recommendedActions must be a list."
        )

    if not 1 <= len(actions) <= MAX_ACTIONS:
        raise MaintenanceAiError(
            "recommendedActions must contain 1 to 5 actions."
        )

    cleaned_actions = []

    for action in actions:
        if not isinstance(action, str):
            raise MaintenanceAiError(
                "Each recommended action must be a string."
            )

        action = action.strip()

        if not action or len(action) > MAX_TEXT_LENGTH:
            raise MaintenanceAiError(
                "Recommended action is empty or too long."
            )

        cleaned_actions.append(action)

    risk_level = result.get("riskLevel")

    if risk_level not in {
        "Low",
        "Medium",
        "High",
        "Critical",
    }:
        raise MaintenanceAiError(
            "riskLevel is invalid."
        )

    rationale = result.get("rationale")

    if not isinstance(rationale, str):
        raise MaintenanceAiError(
            "rationale must be a string."
        )

    rationale = rationale.strip()

    if not rationale or len(rationale) > MAX_TEXT_LENGTH:
        raise MaintenanceAiError(
            "rationale is empty or too long."
        )

    review_status = result.get("reviewStatus")

    if review_status not in {
        "NeedsReview",
        "NeedsManualEntry",
    }:
        raise MaintenanceAiError(
            "reviewStatus is invalid."
        )

    return {
        "recommendedActions": cleaned_actions,
        "riskLevel": risk_level,
        "rationale": rationale,
        "reviewStatus": review_status,
    }


def _safe_asset_context(asset):
    return {
        "category": asset.get("category"),
        "description": asset.get("description"),
        "condition": asset.get("condition"),
        "inServiceDate": asset.get("inServiceDate"),
        "usefulLifeMonths": asset.get("usefulLifeMonths"),
        "status": asset.get("status"),
    }


def _safe_history_context(history):
    return [
        {
            "maintenanceType": item.get("maintenanceType"),
            "description": item.get("description"),
            "performedDate": item.get("performedDate"),
            "conditionAfter": item.get("conditionAfter"),
            "nextMaintenanceDate": item.get(
                "nextMaintenanceDate"
            ),
        }
        for item in history[:10]
    ]


def generate_maintenance_advice(
    asset,
    maintenance_history,
    deterministic_schedule,
    bedrock_client=None,
):
    client = (
        bedrock_client
        if bedrock_client is not None
        else boto3.client("bedrock-runtime")
    )

    context = {
        "asset": _safe_asset_context(asset),
        "maintenanceHistory": _safe_history_context(
            maintenance_history
        ),
        "authoritativeSchedule": deterministic_schedule,
    }

    prompt = f"""
You are assisting an asset-maintenance technician.

Use only the supplied asset and maintenance information.
The authoritative cleaning and maintenance dates were calculated
by application code. Do not replace or modify those dates.

Return only a valid JSON object in this format:

{{
  "recommendedActions": [
    "specific maintenance action"
  ],
  "riskLevel": "Low, Medium, High, or Critical",
  "rationale": "short explanation",
  "reviewStatus": "NeedsReview or NeedsManualEntry"
}}

Rules:

- Provide between 1 and 5 practical actions.
- Do not invent serial numbers, users, costs, dates, or failures.
- Do not claim that an inspection was performed.
- Use NeedsManualEntry when the supplied data is insufficient.
- A technician must review the recommendation before applying it.
- Return JSON only without Markdown.

Asset context:
{json.dumps(context, default=str)}
"""

    response = client.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ],
        inferenceConfig={
            "maxTokens": 450,
            "temperature": 0,
        },
    )

    content_blocks = response["output"]["message"]["content"]

    model_text = "".join(
        block.get("text", "")
        for block in content_blocks
    )

    return validate_ai_recommendation(model_text)
