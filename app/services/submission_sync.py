from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import AsyncSessionLocal
from app.core.settings import settings
from app.models.user import Submission, SubmissionStatus
from app.repositories.form_repository import FormRepository
from app.services.crypto import decrypt_token, encrypt_token


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
    sheet_url: str | None,
    worksheet_name: str | None,
    access_token: str | None = None,
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
    config: dict = {
        "sheet_url": sheet_url.strip(),
        "spreadsheet_id": match.group(1),
        "worksheet_name": worksheet,
    }
    if access_token and access_token.strip():
        config["access_token"] = access_token.strip()
    return config


def validate_notion_config(database_id: str | None, notion_token: str | None) -> dict:
    if not database_id or not notion_token:
        raise ValueError("Notion database ID and token are required.")

    raw_id = database_id.strip()
    # Support extracting 32-character hex ID from Notion URLs or raw strings
    url_match = re.search(r"([0-9a-fA-F]{32})", raw_id)
    if url_match:
        cleaned_database_id = url_match.group(1).lower()
    else:
        cleaned_database_id = raw_id.replace("-", "").lower()
        if len(cleaned_database_id) != 32 or not re.fullmatch(
            r"[0-9a-fA-F]{32}", cleaned_database_id
        ):
            raise ValueError(
                "Notion database ID must be a 32-character UUID or valid Notion database URL."
            )

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


async def sync_submission_integrations(submission_id: str | UUID) -> None:
    async with AsyncSessionLocal() as db:
        try:
            sub_uuid = (
                UUID(str(submission_id))
                if not isinstance(submission_id, UUID)
                else submission_id
            )
            result = await db.execute(
                select(Submission)
                .options(selectinload(Submission.form))
                .where(Submission.id == sub_uuid)
            )
            submission = result.scalar_one_or_none()
            if not submission:
                log.warning(f"Submission {submission_id} not found for sync.")
                return

            if submission.status != SubmissionStatus.ACCEPTED:
                log.info(
                    f"Submission {submission_id} has status {submission.status}, skipping sync."
                )
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
                            submission, config, integration
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


async def _sync_to_notion(
    submission: Submission, config: dict, integration: dict | None = None
) -> dict:
    raw_token = config.get("notion_token") or (
        integration.get("access_token") if integration else None
    )
    validated = validate_notion_config(config.get("database_id"), raw_token)
    notion_token = validated["notion_token"]
    database_id = validated["database_id"]

    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    payload = dict(submission.payload or {})
    title_field = config.get("title_field")
    title_value = config.get("title_value")
    if not title_value:
        title_value = next(
            (
                str(value)
                for value in payload.values()
                if _stringify_value(value)
            ),
            f"Submission {str(submission.id)[:8]}",
        )

    # Introspect Notion database properties to map correctly
    db_schema: dict[str, dict] = {}
    actual_title_col: str | None = None

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            db_res = await client.get(
                f"https://api.notion.com/v1/databases/{database_id}",
                headers=headers,
            )
            if db_res.status_code == 200:
                props = db_res.json().get("properties", {})
                for col_name, col_meta in props.items():
                    db_schema[col_name.lower().strip()] = {
                        "name": col_name,
                        "type": col_meta.get("type", "rich_text"),
                    }
                    if col_meta.get("type") == "title" and not actual_title_col:
                        actual_title_col = col_name
        except Exception as exc:  # noqa: BLE001
            log.warning(f"Could not introspect Notion database {database_id}: {exc}")

    # Determine title column
    if not actual_title_col:
        actual_title_col = title_field or "Name"

    properties: dict[str, dict] = {
        actual_title_col: {
            "title": [{"text": {"content": _stringify_value(title_value)[:2000]}}]
        }
    }

    field_map = config.get("field_map") or {}
    unmapped_fields: list[tuple[str, str]] = []

    for key, val in payload.items():
        val_str = _stringify_value(val)
        target_name = field_map.get(key, key)

        if target_name == actual_title_col:
            continue

        normalized = target_name.lower().strip()
        if db_schema and normalized in db_schema:
            col_info = db_schema[normalized]
            real_name = col_info["name"]
            col_type = col_info["type"]

            if col_type == "rich_text":
                properties[real_name] = {
                    "rich_text": [{"text": {"content": val_str[:2000]}}]
                }
            elif col_type == "email":
                properties[real_name] = {"email": val_str[:200].strip() or None}
            elif col_type == "url":
                properties[real_name] = {"url": val_str[:2000].strip() or None}
            elif col_type == "phone_number":
                properties[real_name] = {"phone_number": val_str[:50].strip() or None}
            elif col_type == "number":
                try:
                    num_val = float(val_str) if "." in val_str else int(val_str)
                    properties[real_name] = {"number": num_val}
                except (ValueError, TypeError):
                    unmapped_fields.append((key, val_str))
            else:
                properties[real_name] = {
                    "rich_text": [{"text": {"content": val_str[:2000]}}]
                }
        elif not db_schema:
            # If schema couldn't be loaded, attempt standard rich_text property
            properties[target_name] = {
                "rich_text": [{"text": {"content": val_str[:2000]}}]
            }
        else:
            unmapped_fields.append((key, val_str))

    # Build page body blocks for any unmapped payload fields and submission metadata
    children: list[dict] = []
    if unmapped_fields:
        children.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"text": {"content": "Submission Details"}}]
                },
            }
        )
        for field_name, field_val in unmapped_fields:
            children.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {
                                "text": {"content": f"{field_name}: "},
                                "annotations": {"bold": True},
                            },
                            {"text": {"content": field_val[:2000]}},
                        ]
                    },
                }
            )

    post_body: dict = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }
    if children:
        post_body["children"] = children

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=post_body,
        )

    if response.status_code == 403:
        raise ValueError(
            "Notion write permission denied (403). Ensure your integration token has 'Insert content' (write) capability and the database is shared with your integration."
        )
    if response.status_code == 404:
        raise ValueError(
            "Notion database not found or access denied (404). Ensure the database ID is valid and connected to your Notion integration."
        )
    if response.status_code >= 400:
        raise ValueError(f"Notion sync failed ({response.status_code}): {response.text}")

    return _sync_entry(
        "synced",
        "Synced to Notion",
        details={"page_id": response.json().get("id")},
    )


async def _refresh_google_token(refresh_token: str) -> str | None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return None
    raw_refresh_token = decrypt_token(refresh_token)
    if not raw_refresh_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": raw_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
    except Exception as exc:  # noqa: BLE001
        log.warning(f"Google token refresh failed: {exc}")
    return None


async def _sync_to_google_sheets(
    submission: Submission, config: dict, integration: dict
) -> dict:
    raw_token = config.get("access_token") or integration.get("access_token")
    access_token = decrypt_token(raw_token)
    validated = validate_google_sheets_config(
        config.get("sheet_url"), config.get("worksheet_name"), access_token
    )

    if not access_token:
        return _sync_entry(
            "awaiting_auth",
            "Google Sheets is configured but waiting for an authenticated access token",
        )

    spreadsheet_id = validated["spreadsheet_id"]
    worksheet = quote(validated["worksheet_name"], safe="")
    payload = dict(submission.payload or {})

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Check if token is expired and refresh if needed
        test_url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{worksheet}!A1:Z1"
        header_resp = await client.get(
            test_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        refresh_tok = integration.get("refresh_token") or config.get("refresh_token")
        if header_resp.status_code == 401 and refresh_tok:
            new_token = await _refresh_google_token(refresh_tok)
            if new_token:
                access_token = new_token
                header_resp = await client.get(
                    test_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

        if header_resp.status_code == 401:
            return _sync_entry(
                "awaiting_auth",
                "Google Sheets access token has expired or is invalid. Please update your token.",
            )
        if header_resp.status_code == 403:
            raise ValueError(
                "Google Sheets write permission denied (403). Ensure the spreadsheet was created by Formdata or is accessible under the 'https://www.googleapis.com/auth/drive.file' scope with Editor permissions."
            )
        if header_resp.status_code >= 400:
            raise ValueError(f"Google Sheets access error ({header_resp.status_code}): {header_resp.text}")

        header_data = header_resp.json()
        existing_rows = header_data.get("values", [])

        sorted_payload_keys = sorted(payload.keys())

        if not existing_rows or not existing_rows[0]:
            # Sheet is empty: create header row first
            header_row = ["Submitted At", "Country", *sorted_payload_keys]
            values_row = [
                submission.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                if submission.created_at
                else _now_iso(),
                submission.country or "",
                *[_stringify_value(payload.get(k)) for k in sorted_payload_keys],
            ]
            append_url = (
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
                f"/values/{worksheet}!A1:append?valueInputOption=USER_ENTERED"
                "&insertDataOption=INSERT_ROWS"
            )
            append_res = await client.post(
                append_url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"values": [header_row, values_row]},
            )
        else:
            # Map values to existing columns
            headers_list = [str(h).strip() for h in existing_rows[0]]
            lower_headers = [h.lower() for h in headers_list]

            row_map: dict[int, str] = {}
            unmatched: list[str] = []

            for key, val in payload.items():
                val_str = _stringify_value(val)
                key_lower = key.lower().strip()
                if key_lower in lower_headers:
                    idx = lower_headers.index(key_lower)
                    row_map[idx] = val_str
                else:
                    unmatched.append(f"{key}: {val_str}")

            # Fill in special columns if present in headers
            for special, special_val in [
                ("submitted at", submission.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if submission.created_at else _now_iso()),
                ("date", submission.created_at.strftime("%Y-%m-%d") if submission.created_at else ""),
                ("country", submission.country or ""),
            ]:
                if special in lower_headers and lower_headers.index(special) not in row_map:
                    row_map[lower_headers.index(special)] = special_val

            # Assemble row according to header length
            row_len = max(len(headers_list), max(row_map.keys()) + 1 if row_map else 0)
            values_row = [row_map.get(i, "") for i in range(row_len)]
            if unmatched:
                values_row.append(" | ".join(unmatched))

            append_url = (
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
                f"/values/{worksheet}!A1:append?valueInputOption=USER_ENTERED"
                "&insertDataOption=INSERT_ROWS"
            )
            append_res = await client.post(
                append_url,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"values": [values_row]},
            )

        if append_res.status_code == 403:
            raise ValueError(
                "Google Sheets write permission denied (403). Ensure the spreadsheet was created by Formdata or is accessible under the 'https://www.googleapis.com/auth/drive.file' scope with Editor permissions."
            )
        if append_res.status_code >= 400:
            raise ValueError(f"Google Sheets sync failed ({append_res.status_code}): {append_res.text}")

        return _sync_entry(
            "synced",
            "Synced to Google Sheets",
            details={
                "updated_range": append_res.json().get("updates", {}).get("updatedRange")
            },
        )
