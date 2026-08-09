"""
Async Cloudflare R2 storage helper for form-submission file uploads.

R2 is S3-API-compatible, so this just points boto3 (via aioboto3, for a
non-blocking event loop) at R2's endpoint instead of AWS's.

Env vars required:
    R2_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET

Keep the bucket PRIVATE (no public access / no custom domain). Files are
only ever reachable via short-lived presigned URLs generated for an
authenticated dashboard user.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

import aioboto3
from starlette.datastructures import UploadFile

R2_ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET = os.environ["R2_BUCKET"]
R2_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

_session = aioboto3.Session()


def _client():
    return _session.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",  # required by the SDK, unused by R2
    )


def _safe_filename(name: str | None) -> str:
    """Original filename is only used for the download's Content-Disposition
    header — never trust it as, or as part of, the storage key/path."""
    base = os.path.basename(name or "file")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:150]
    return cleaned or "file"


async def upload_submission_file(
    *,
    form_id: str,
    submission_ref: str,
    field_name: str,
    upload: UploadFile,
    max_bytes: int,
    allowed_extensions: set[str] | None = None,
    allowed_content_types: set[str] | None = None,
) -> dict[str, Any]:
    """
    Reads one UploadFile and stores it privately in R2.

    Accepts any file type and any number of files per field by default —
    call this once per (field_name, UploadFile) pair, including every file
    from a `<input type="file" multiple>` field, and it just works.

    Returns JSON-serializable metadata to embed in the submission payload —
    never the raw bytes. Raises ValueError if the file exceeds max_bytes
    (defense in depth — you should also pass max_part_size to
    request.form() so oversized parts are rejected before they're even
    fully read off the wire), or if allowed_extensions/allowed_content_types
    is given and the file doesn't match. Both are opt-in per call, so you
    can restrict, say, a "resume" field to PDFs/docs while leaving a
    "photos" field wide open — leave both None to accept anything.
    """
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if allowed_extensions is not None and ext not in allowed_extensions:
        raise ValueError(
            f"'{field_name}': '{ext or '(no extension)'}' is not an allowed file type"
        )
    if (
        allowed_content_types is not None
        and upload.content_type not in allowed_content_types
    ):
        raise ValueError(
            f"'{field_name}': content type '{upload.content_type}' is not allowed"
        )

    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"'{field_name}' exceeds the {max_bytes}-byte limit")

    ext = ext[:16]
    object_key = (
        f"submissions/{form_id}/{submission_ref}/{field_name}/{uuid.uuid4().hex}{ext}"
    )

    async with _client() as s3:
        await s3.put_object(
            Bucket=R2_BUCKET,
            Key=object_key,
            Body=data,
            ContentType=upload.content_type or "application/octet-stream",
            ContentDisposition=f'attachment; filename="{_safe_filename(upload.filename)}"',
        )

    return {
        "r2_key": object_key,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size": len(data),
    }


async def presign_download(object_key: str, expires_in: int = 300) -> str:
    """Short-lived GET URL for an authenticated dashboard user viewing a
    submission. Never persist this URL — generate it fresh per view."""
    async with _client() as s3:
        return await s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET, "Key": object_key},
            ExpiresIn=expires_in,
        )


async def delete_submission_file(object_key: str) -> None:
    async with _client() as s3:
        await s3.delete_object(Bucket=R2_BUCKET, Key=object_key)
