
from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import Iterable
from contextlib import asynccontextmanager
from typing import Any, cast

import aioboto3
from loguru import logger as log
from starlette.datastructures import UploadFile

from app.core.settings import settings

R2_ACCOUNT_ID = settings.R2_ACCOUNT_ID
R2_ACCESS_KEY_ID = settings.R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY = settings.R2_SECRET_ACCESS_KEY
R2_BUCKET = settings.R2_BUCKET
R2_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

_session = aioboto3.Session()

# How many files a single submission uploads to R2 at once. Uploads in a
# batch share one client/connection but still run in parallel up to this
# cap, so one 30-file submission can't starve every other request's
# event-loop time or blow past R2's per-connection limits.
MAX_CONCURRENT_UPLOADS = 6


@asynccontextmanager
async def _client():
    async with cast(
        Any,
        _session.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",  # required by the SDK, unused by R2
        ),
    ) as client:
        yield client


def _safe_filename(name: str | None) -> str:
    """Original filename is only used for the download's Content-Disposition
    header — never trust it as, or as part of, the storage key/path."""
    base = os.path.basename(name or "file")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:150]
    return cleaned or "file"


# --- harmful-file denylist -------------------------------------------------
# Extensions that are never acceptable on a generic upload field (resumes,
# attachments, photos, etc. never legitimately need these). Enforced
# unconditionally — a caller's `allowed_extensions` is "what I additionally
# expect for this field", not "please also let dangerous types through".
DANGEROUS_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Windows executables / installers
        ".exe",
        ".dll",
        ".com",
        ".msi",
        ".msp",
        ".msix",
        ".msixbundle",
        ".scr",
        ".pif",
        ".cpl",
        ".gadget",
        # Windows / script hosts
        ".bat",
        ".cmd",
        ".vbs",
        ".vbe",
        ".vb",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".ps1",
        ".ps1xml",
        ".psc1",
        ".psm1",
        ".psd1",
        ".hta",
        # Shortcuts, shell integration, registry
        ".lnk",
        ".scf",
        ".sct",
        ".shs",
        ".reg",
        ".url",
        # Java / mobile / disk images that commonly carry payloads
        ".jar",
        ".apk",
        ".appx",
        ".appxbundle",
        ".ipa",
        ".dmg",
        ".iso",
        # Unix / macOS executables & scripts
        ".sh",
        ".bash",
        ".command",
        ".run",
        ".bin",
        # Server-side script types — harmless sitting in a private bucket, but
        # blocked so a future misconfigured "serve this publicly" bucket can't
        # turn an uploaded resume into remote code execution
        ".php",
        ".phtml",
        ".php3",
        ".php4",
        ".php5",
        ".phar",
        ".asp",
        ".aspx",
        ".jsp",
        ".jspx",
        ".cgi",
    }
)

# Magic-byte signatures for executable formats, checked regardless of the
# claimed extension or Content-Type — both are attacker-controlled, file
# bytes aren't. Catches an "invoice.pdf" that's actually a renamed .exe.
_EXECUTABLE_SIGNATURES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE/DOS executable
    b"\x7fELF",  # Linux ELF executable
    b"\xca\xfe\xba\xbe",  # Mach-O fat binary (macOS)
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit, reverse byte order
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit, reverse byte order
    b"#!",  # shebang — Unix script
)


def _looks_executable(data: bytes) -> bool:
    return any(data.startswith(sig) for sig in _EXECUTABLE_SIGNATURES)


class RejectedFile(ValueError):
    """A file failed type/content validation. Message is safe to show the
    submitter — it never includes file bytes or internal paths."""


def _validate_extension(
    field_name: str, filename: str | None, allowed_extensions: set[str] | None
) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in DANGEROUS_EXTENSIONS:
        raise RejectedFile(f"'{field_name}': file type '{ext}' is not allowed")
    if allowed_extensions is not None and ext not in allowed_extensions:
        raise RejectedFile(
            f"'{field_name}': '{ext or '(no extension)'}' is not an allowed file type"
        )
    return ext


async def upload_submission_file(
    *,
    form_id: str,
    submission_ref: str,
    field_name: str,
    upload: UploadFile,
    max_bytes: int,
    allowed_extensions: set[str] | None = None,
    allowed_content_types: set[str] | None = None,
    s3: Any | None = None,
) -> dict[str, Any]:
    """
    Reads one UploadFile, validates it, and stores it privately in R2.

    Pass an already-entered `s3` client when uploading several files for
    the same submission (see upload_submission_files_batch) so they share
    one connection instead of each paying its own TLS handshake.

    Raises RejectedFile for a dangerous/disallowed type or content that
    looks like an executable, or ValueError if the file exceeds max_bytes
    (defense in depth — also pass max_part_size to request.form() so
    oversized parts are rejected before being fully read off the wire).
    """
    ext = _validate_extension(field_name, upload.filename, allowed_extensions)

    if (
        allowed_content_types is not None
        and upload.content_type not in allowed_content_types
    ):
        raise RejectedFile(
            f"'{field_name}': content type '{upload.content_type}' is not allowed"
        )

    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"'{field_name}' exceeds the {max_bytes}-byte limit")

    if _looks_executable(data):
        raise RejectedFile(f"'{field_name}': file content looks like an executable")

    ext = ext[:16]
    object_key = (
        f"submissions/{form_id}/{submission_ref}/{field_name}/{uuid.uuid4().hex}{ext}"
    )

    async def _put(client) -> None:
        await client.put_object(
            Bucket=R2_BUCKET,
            Key=object_key,
            Body=data,
            ContentType=upload.content_type or "application/octet-stream",
            ContentDisposition=f'attachment; filename="{_safe_filename(upload.filename)}"',
        )

    if s3 is not None:
        await _put(s3)
    else:
        async with _client() as client:
            await _put(client)

    return {
        "r2_key": object_key,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "size": len(data),
    }


async def upload_submission_files_batch(
    *,
    form_id: str,
    submission_ref: str,
    files: Iterable[tuple[str, UploadFile]],
    max_bytes: int,
    allowed_extensions: dict[str, set[str]] | None = None,
    allowed_content_types: dict[str, set[str]] | None = None,
    max_retries: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """
    Uploads every (field_name, UploadFile) pair for one submission
    concurrently, sharing a single R2 connection, capped at
    MAX_CONCURRENT_UPLOADS in flight at once.

    `allowed_extensions` / `allowed_content_types`, if given, are keyed by
    field name so different fields can have different rules (e.g.
    "resume" -> {.pdf, .doc, .docx}, "photos" -> wide open). The
    DANGEROUS_EXTENSIONS denylist and the executable-signature check are
    still enforced on every field regardless.

    Returns {field_name: [metadata, ...]} — always a list per field, even
    for a single-file field, keeping this function's contract simple.
    Callers that want a bare object for single-file fields can unwrap the
    one-element list themselves.

    If any file fails (bad type/size/looks-executable, or an R2 error that
    survives retries), every file already uploaded in this batch is
    deleted from R2 before the exception propagates — a submission with 4
    good files and 1 bad one shouldn't leave the 4 good ones orphaned in
    the bucket with no submission row pointing at them.
    """
    files = list(files)
    allowed_extensions = allowed_extensions or {}
    allowed_content_types = allowed_content_types or {}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

    async def _upload_one(client, field_name: str, upload: UploadFile):
        async with semaphore:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    meta = await upload_submission_file(
                        form_id=form_id,
                        submission_ref=submission_ref,
                        field_name=field_name,
                        upload=upload,
                        max_bytes=max_bytes,
                        allowed_extensions=allowed_extensions.get(field_name),
                        allowed_content_types=allowed_content_types.get(field_name),
                        s3=client,
                    )
                    return field_name, meta
                except (RejectedFile, ValueError):
                    raise  # the file itself is the problem — retrying won't help
                except Exception as exc:  # transient R2/network error
                    last_exc = exc
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5 * (2**attempt))
            assert last_exc is not None
            raise last_exc

    async with _client() as client:
        tasks = [
            asyncio.create_task(_upload_one(client, field_name, upload))
            for field_name, upload in files
        ]
        try:
            results = await asyncio.gather(*tasks)
        except Exception:
            for t in tasks:
                if not t.done():
                    t.cancel()
            # let cancellations (and any other in-flight results) settle
            # before we close the client and clean up what did succeed
            settled = await asyncio.gather(*tasks, return_exceptions=True)
            uploaded_meta = [r[1] for r in settled if isinstance(r, tuple)]
            if uploaded_meta:
                log.warning(
                    f"Cleaning up {len(uploaded_meta)} orphaned R2 object(s) "
                    f"for form {form_id} after a failed batch upload"
                )
                await asyncio.gather(
                    *(delete_submission_file(m["r2_key"]) for m in uploaded_meta),
                    return_exceptions=True,
                )
            raise

    grouped: dict[str, list[dict[str, Any]]] = {}
    for field_name, meta in results:
        grouped.setdefault(field_name, []).append(meta)
    return grouped


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
