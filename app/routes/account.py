from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.settings import settings
from app.core.templates import temp
from app.models.user import User
from app.services.account import get_account_billing_data
from app.services.dependencies import current_user

account_router = APIRouter()


@account_router.get("/account", response_class=HTMLResponse)
async def handle_get_account_details(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):

    billing = await get_account_billing_data(
        db=db,
        user=user,
    )
    print("Hello buddy.....")
    return temp.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "page": "account",
            # Billing / subscription
            "paddle_solo_price": settings.PADDLE_PRICE_ID_SOLO,
            "paddle_studio_price": settings.PADDLE_PRICE_ID_STUDIO,
            "paddle_client_token": settings.PADDLE_CLIENT_TOKEN,
            **billing,
        },
    )


# {
#     "current_plan": "studio",
#     "subscription_status": "active",
#     "sub_id": "sub_01kzdvfz6vbrvf1vevpxm93avq",
#     "renews_at": "Sep 7, 2026",
#     "resumes_at": null,
#     "trial_days_left": null,
#     "cancel_at": null,
#     "can_undo_cancel": false,
#     "portal_links": {
#         "overview_url": "https://sandbox-customer-portal.paddle.com/cpl_01jp4tch0wfxy6nq1zyxsg37jz?action=overview&token=pga_eyJhbGciOiJFZERTQSIsImtpZCI6Imp3a18wMWhkazBuOHF3OG55NTJ5cGNocGNhazA1ayIsInR5cCI6IkpXVCJ9.eyJpZCI6InBnYV8wMW0wZ2ViN2tqa3JzcTZrMzAzMTdzbnc4eCIsInNlbGxlci1pZCI6IjI4NTU4IiwidHlwZSI6InN0YW5kYXJkIiwidmVyc2lvbiI6IjEiLCJ1c2FnZSI6ImN1c3RvbWVyLXBvcnRhbC1zZXNzaW9uIiwic2NvcGUiOiJjdXN0b21lci5hZGp1c3RtZW50LnJlYWQgY3VzdG9tZXIuY2hlY2tvdXQuY3JlYXRlIGN1c3RvbWVyLmNoZWNrb3V0LnJlYWQgY3VzdG9tZXIuY3VzdG9tZXIucmVhZCBjdXN0b21lci5jdXN0b21lci51cGRhdGUgY3VzdG9tZXIuY3VzdG9tZXItYWRkcmVzcy5yZWFkIGN1c3RvbWVyLmN1c3RvbWVyLWFkZHJlc3MudXBkYXRlIGN1c3RvbWVyLmN1c3RvbWVyLWJ1c2luZXNzLnJlYWQgY3VzdG9tZXIuY3VzdG9tZXItYnVzaW5lc3MuY3JlYXRlIGN1c3RvbWVyLmN1c3RvbWVyLWJ1c2luZXNzLnVwZGF0ZSBjdXN0b21lci5jdXN0b21lci1wYXltZW50LW1ldGhvZC5yZWFkIGN1c3RvbWVyLmN1c3RvbWVyLXBheW1lbnQtbWV0aG9kLmRlbGV0ZSBjdXN0b21lci5pbnZvaWNlLnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLWNhbmNlbC5jcmVhdGUgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLWNvbnNlbnQtcmVxdWlyZW1lbnQtZ3JhbnQuY3JlYXRlIGN1c3RvbWVyLnN1YnNjcmlwdGlvbi1jb25zZW50LXJlcXVpcmVtZW50LnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLnVwZGF0ZSBjdXN0b21lci50cmFuc2FjdGlvbi5jcmVhdGUgY3VzdG9tZXIudHJhbnNhY3Rpb24ucmVhZCBjdXN0b21lci50cmFuc2FjdGlvbi51cGRhdGUgY3VzdG9tZXIudHJhbnNhY3Rpb24ub3JpZ2luLnJlYWQiLCJpc3MiOiJndWVzdGFjY2Vzcy1zZXJ2aWNlIiwic3ViIjoiY3RtXzAxanA1M3ZlcmVnOTB3OWJhMHM4MTA0ZWRzIiwiZXhwIjoxNzg3MzQ0NzE0LCJpYXQiOjE3ODcyNTgzMTR9.WTpU4MZ3KFqnVgWwb6AuEFTkN3wL2mbpNAsr7lB5KyK6SrRPNBcdYVT5Zp5JJqLnSHpcU8R43tGJ73uZ1rU-Ag",
#         "cancel_url": "https://sandbox-customer-portal.paddle.com/cpl_01jp4tch0wfxy6nq1zyxsg37jz?action=cancel_subscription&subscription_id=sub_01kzdvfz6vbrvf1vevpxm93avq&token=pga_eyJhbGciOiJFZERTQSIsImtpZCI6Imp3a18wMWhkazBuOHF3OG55NTJ5cGNocGNhazA1ayIsInR5cCI6IkpXVCJ9.eyJpZCI6InBnYV8wMW0wZ2ViN2tqa3JzcTZrMzAzMTdzbnc4eCIsInNlbGxlci1pZCI6IjI4NTU4IiwidHlwZSI6InN0YW5kYXJkIiwidmVyc2lvbiI6IjEiLCJ1c2FnZSI6ImN1c3RvbWVyLXBvcnRhbC1zZXNzaW9uIiwic2NvcGUiOiJjdXN0b21lci5hZGp1c3RtZW50LnJlYWQgY3VzdG9tZXIuY2hlY2tvdXQuY3JlYXRlIGN1c3RvbWVyLmNoZWNrb3V0LnJlYWQgY3VzdG9tZXIuY3VzdG9tZXIucmVhZCBjdXN0b21lci5jdXN0b21lci51cGRhdGUgY3VzdG9tZXIuY3VzdG9tZXItYWRkcmVzcy5yZWFkIGN1c3RvbWVyLmN1c3RvbWVyLWFkZHJlc3MudXBkYXRlIGN1c3RvbWVyLmN1c3RvbWVyLWJ1c2luZXNzLnJlYWQgY3VzdG9tZXIuY3VzdG9tZXItYnVzaW5lc3MuY3JlYXRlIGN1c3RvbWVyLmN1c3RvbWVyLWJ1c2luZXNzLnVwZGF0ZSBjdXN0b21lci5jdXN0b21lci1wYXltZW50LW1ldGhvZC5yZWFkIGN1c3RvbWVyLmN1c3RvbWVyLXBheW1lbnQtbWV0aG9kLmRlbGV0ZSBjdXN0b21lci5pbnZvaWNlLnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLWNhbmNlbC5jcmVhdGUgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLWNvbnNlbnQtcmVxdWlyZW1lbnQtZ3JhbnQuY3JlYXRlIGN1c3RvbWVyLnN1YnNjcmlwdGlvbi1jb25zZW50LXJlcXVpcmVtZW50LnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLnVwZGF0ZSBjdXN0b21lci50cmFuc2FjdGlvbi5jcmVhdGUgY3VzdG9tZXIudHJhbnNhY3Rpb24ucmVhZCBjdXN0b21lci50cmFuc2FjdGlvbi51cGRhdGUgY3VzdG9tZXIudHJhbnNhY3Rpb24ub3JpZ2luLnJlYWQiLCJpc3MiOiJndWVzdGFjY2Vzcy1zZXJ2aWNlIiwic3ViIjoiY3RtXzAxanA1M3ZlcmVnOTB3OWJhMHM4MTA0ZWRzIiwiZXhwIjoxNzg3MzQ0NzE0LCJpYXQiOjE3ODcyNTgzMTR9.WTpU4MZ3KFqnVgWwb6AuEFTkN3wL2mbpNAsr7lB5KyK6SrRPNBcdYVT5Zp5JJqLnSHpcU8R43tGJ73uZ1rU-Ag",
#         "update_payment_url": "https://sandbox-customer-portal.paddle.com/cpl_01jp4tch0wfxy6nq1zyxsg37jz?action=update_subscription_payment_method&subscription_id=sub_01kzdvfz6vbrvf1vevpxm93avq&token=pga_eyJhbGciOiJFZERTQSIsImtpZCI6Imp3a18wMWhkazBuOHF3OG55NTJ5cGNocGNhazA1ayIsInR5cCI6IkpXVCJ9.eyJpZCI6InBnYV8wMW0wZ2ViN2tqa3JzcTZrMzAzMTdzbnc4eCIsInNlbGxlci1pZCI6IjI4NTU4IiwidHlwZSI6InN0YW5kYXJkIiwidmVyc2lvbiI6IjEiLCJ1c2FnZSI6ImN1c3RvbWVyLXBvcnRhbC1zZXNzaW9uIiwic2NvcGUiOiJjdXN0b21lci5hZGp1c3RtZW50LnJlYWQgY3VzdG9tZXIuY2hlY2tvdXQuY3JlYXRlIGN1c3RvbWVyLmNoZWNrb3V0LnJlYWQgY3VzdG9tZXIuY3VzdG9tZXIucmVhZCBjdXN0b21lci5jdXN0b21lci51cGRhdGUgY3VzdG9tZXIuY3VzdG9tZXItYWRkcmVzcy5yZWFkIGN1c3RvbWVyLmN1c3RvbWVyLWFkZHJlc3MudXBkYXRlIGN1c3RvbWVyLmN1c3RvbWVyLWJ1c2luZXNzLnJlYWQgY3VzdG9tZXIuY3VzdG9tZXItYnVzaW5lc3MuY3JlYXRlIGN1c3RvbWVyLmN1c3RvbWVyLWJ1c2luZXNzLnVwZGF0ZSBjdXN0b21lci5jdXN0b21lci1wYXltZW50LW1ldGhvZC5yZWFkIGN1c3RvbWVyLmN1c3RvbWVyLXBheW1lbnQtbWV0aG9kLmRlbGV0ZSBjdXN0b21lci5pbnZvaWNlLnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLWNhbmNlbC5jcmVhdGUgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLWNvbnNlbnQtcmVxdWlyZW1lbnQtZ3JhbnQuY3JlYXRlIGN1c3RvbWVyLnN1YnNjcmlwdGlvbi1jb25zZW50LXJlcXVpcmVtZW50LnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLnJlYWQgY3VzdG9tZXIuc3Vic2NyaXB0aW9uLnVwZGF0ZSBjdXN0b21lci50cmFuc2FjdGlvbi5jcmVhdGUgY3VzdG9tZXIudHJhbnNhY3Rpb24ucmVhZCBjdXN0b21lci50cmFuc2FjdGlvbi51cGRhdGUgY3VzdG9tZXIudHJhbnNhY3Rpb24ub3JpZ2luLnJlYWQiLCJpc3MiOiJndWVzdGFjY2Vzcy1zZXJ2aWNlIiwic3ViIjoiY3RtXzAxanA1M3ZlcmVnOTB3OWJhMHM4MTA0ZWRzIiwiZXhwIjoxNzg3MzQ0NzE0LCJpYXQiOjE3ODcyNTgzMTR9.WTpU4MZ3KFqnVgWwb6AuEFTkN3wL2mbpNAsr7lB5KyK6SrRPNBcdYVT5Zp5JJqLnSHpcU8R43tGJ73uZ1rU-Ag",
#     },
#     "submission_quota": {"usage": 0, "limit": 2000, "percentage": 0, "extra": 0},
#     "storage_quota": {
#         "used_bytes": 0,
#         "limit_bytes": 2147483648,
#         "percentage": 0,
#         "extra_bytes": 0,
#     },
# }
