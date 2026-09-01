from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import httpx
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import AsyncSessionLocal
from app.models.user import Submission, SubmissionStatus
from app.repositories.form_repository import FormRepository


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sync_entry(state: str, message: str, *, details: dict | None = None) -> dict:
    payload = {"state": state, "message": message, "updated_at": _now_iso()}
    if details:
        payload["details"] = details
    return payload


def _stringify_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def validate_google_sheets_config(
    sheet_url: str | None, worksheet_name: str | None
) -> dict:
    if not sheet_url:
        raise ValueError("A spreadsheet URL is required.")

    parsed = urlparse(sheet_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("A valid spreadsheet URL is required.")
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/" not in parsed.path:
        raise ValueError("Google Sheets must point to a Google Spreadsheet URL.")

    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", parsed.path)
    if not match:
        raise ValueError("Could not find a spreadsheet ID in the URL.")

    worksheet = (worksheet_name or "Sheet1").strip() or "Sheet1"
    return {
        "sheet_url": sheet_url.strip(),
        "spreadsheet_id": match.group(1),
        "worksheet_name": worksheet,
    }


def validate_notion_config(database_id: str | None, notion_token: str | None) -> dict:
    if not database_id or not notion_token:
        raise ValueError("Notion database ID and token are required.")

    cleaned_database_id = database_id.strip().replace("-", "")
    if len(cleaned_database_id) != 32 or not re.fullmatch(
        r"[0-9a-fA-F]{32}", cleaned_database_id
    ):
        raise ValueError("Notion database ID must be a 32-character UUID-like value.")

    cleaned_token = notion_token.strip()
    if not cleaned_token:
        raise ValueError("Notion token is required.")

    return {
        "database_id": cleaned_database_id,
        "notion_token": cleaned_token,
    }


def build_pending_sync_status(integrations: list[dict]) -> dict:
    return {
        integration["provider"]: _sync_entry(
            "pending",
            "Queued for background sync",
        )
        for integration in integrations
    }


async def sync_submission_integrations(submission_id: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Submission)
                .options(selectinload(Submission.form))
                .where(Submission.id == submission_id)
            )
            submission = result.scalar_one_or_none()
            if not submission:
                return

            if submission.status != SubmissionStatus.ACCEPTED:
                return

            form = submission.form
            if not form:
                return

            repository = FormRepository(db)
            integrations = await repository.get_enabled_integrations(str(form.id))
            if not integrations:
                return

            current_status = dict(submission.integration_sync_status or {})

            for integration in integrations:
                provider = integration["provider"]
                config = dict(integration.get("config") or {})

                try:
                    if provider == "notion":
                        current_status[provider] = await _sync_to_notion(
                            submission, config
                        )
                    elif provider == "google_sheets":
                        current_status[provider] = await _sync_to_google_sheets(
                            submission, config, integration
                        )
                    else:
                        current_status[provider] = _sync_entry(
                            "skipped",
                            f"Provider '{provider}' is not supported yet",
                        )
                except Exception as exc:  # noqa: BLE001
                    log.exception(
                        "Submission sync failed for %s via %s: %s",
                        submission.id,
                        provider,
                        exc,
                    )
                    current_status[provider] = _sync_entry(
                        "failed",
                        str(exc),
                    )

            submission.integration_sync_status = current_status
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.exception(
                "Unhandled submission sync failure for %s: %s", submission_id, exc
            )


async def _sync_to_notion(submission: Submission, config: dict) -> dict:
    validated = validate_notion_config(
        config.get("database_id"), config.get("notion_token")
    )
    notion_token = validated["notion_token"]
    database_id = validated["database_id"]

    title_field = config.get("title_field") or "Name"
    title_value = config.get("title_value")
    if not title_value:
        title_value = next(
            (
                str(value)
                for value in submission.payload.values()
                if _stringify_value(value)
            ),
            "New submission",
        )

    properties: dict[str, dict] = {
        title_field: {"title": [{"text": {"content": _stringify_value(title_value)}}]}
    }
    field_map = config.get("field_map") or {}
    for key, value in submission.payload.items():
        notion_field = field_map.get(key, key)
        if notion_field == title_field:
            continue
        properties[notion_field] = {
            "rich_text": [{"text": {"content": _stringify_value(value)}}]
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={
                "parent": {"database_id": database_id},
                "properties": properties,
            },
        )

    if response.status_code >= 400:
        raise ValueError(f"Notion sync failed: {response.text}")

    return _sync_entry(
        "synced",
        "Synced to Notion",
        details={"page_id": response.json().get("id")},
    )


async def _sync_to_google_sheets(
    submission: Submission, config: dict, integration: dict
) -> dict:
    validated = validate_google_sheets_config(
        config.get("sheet_url"), config.get("worksheet_name")
    )
    access_token = integration.get("access_token")
    if not access_token:
        return _sync_entry(
            "awaiting_auth",
            "Google Sheets is configured but waiting for an authenticated access token",
        )

    values = [[_stringify_value(value) for value in submission.payload.values()]]
    worksheet = quote(validated["worksheet_name"], safe="")
    append_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{validated['spreadsheet_id']}"
        f"/values/{worksheet}!A1:append?valueInputOption=USER_ENTERED"
        "&insertDataOption=INSERT_ROWS"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            append_url,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"values": values},
        )

    if response.status_code >= 400:
        raise ValueError(f"Google Sheets sync failed: {response.text}")

    return _sync_entry(
        "synced",
        "Synced to Google Sheets",
        details={
            "updated_range": response.json().get("updates", {}).get("updatedRange")
        },
    )
