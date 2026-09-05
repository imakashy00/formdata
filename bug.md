# Repository Bug Report

Audit date: 2026-09-06

## Fixed in this change

- **Trial length was 15 days instead of 14.** `Subscription.trial_end` now defaults to 14 days after signup.
- **Trial submissions were not counted or limited.** Accepted submissions now increment `Subscription.submissions_used`; trial submissions are rejected after the first 1,000 while the trial is active.
- **Template access was not protected server-side.** Non-Studio users can no longer load or update template settings. The Templates tab links to `/account` with an `Upgrade to Studio` action.
- **The test directory was removed on request.** The pre-removal suite completed with `3 passed`.

## Resolved bugs

### High

- **Attachment upload errors are ignored** (`app/routes/client_form.py`). Upload and dangerous-file validation responses now stop submission acceptance.
- **Trial quota checks are not concurrency-safe** (`app/routes/client_form.py`). The owner subscription row is locked before the quota check and submission commit.
- **Paid quota usage and billing use different counters** (`app/services/account.py`, `app/routes/dashboard.py`, `app/routes/client_form.py`). Every accepted submission updates `Subscription.submissions_used`; account and dashboard quota displays use the same counter, and Paddle billing-period rollover resets it after overage billing succeeds.

### Medium

- **Cancellation data can be erased by ordinary subscription updates** (`app/services/subscription.py`). `cancel_at` is now updated only when Paddle includes `scheduled_change`.
- **Paddle portal errors are not handled correctly** (`app/services/account.py`). HTTP and response-shape errors now return an empty-links state without exposing portal data.
- **The date helper creates naive datetimes** (`app/core/templates.py`). Unix timestamps are now converted with UTC.
- **Broad exception handlers hide failures** (`app/routes/form.py`). Integration handlers now catch expected HTTP, validation, JSON-shape, and database errors explicitly.

### Low

- **Debug output is left in the account route** (`app/routes/account.py`). Removed.
- **The application metadata is inconsistent** (`pyproject.toml`). The package is now named `formdata`.
- **The test widget is exposed in production** (`app/routes/form.py`). The route now returns 404 outside development.

### Product consistency

- Customer autoresponders are displayed and enforced as Studio-only.
- Public and account pricing tables now use the implemented 1,000/2,000 monthly allowances and $1 per 100/200 submission overage rates.
- Unsupported Slack, Zapier, and webhook pricing claims were removed from the pricing table.

## Validation performed

- Existing tests before removal: `3 passed in 0.16s`.
- Python compilation: `python -m compileall -q app main.py` passed.
- `pytest -q` found no test files in the repository; Python compilation passed.