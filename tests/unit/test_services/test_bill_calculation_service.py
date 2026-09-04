import pytest

from app.models.user import Subscription
from app.services.bill_calculation import Overage, calculate_overage


def test_overage_dataclass():
    """Verify Overage dataclass calculation logic."""
    o1 = Overage(submission_blocks=0, storage_gb=0)
    assert o1.has_charge is False

    o2 = Overage(submission_blocks=2, storage_gb=1)
    assert o2.has_charge is True


def test_calculate_overage_within_limits():
    """Verify calculate_overage returns zero overage when usage is within limits."""
    sub = Subscription(
        price_id="pri_test_solo",
        monthly_submissions_count=500,
        storage_bytes=0,
    )
    overage = calculate_overage(sub)
    assert overage.submission_blocks == 0
    assert overage.storage_gb == 0
    assert overage.has_charge is False
