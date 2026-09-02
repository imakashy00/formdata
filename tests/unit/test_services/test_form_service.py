import pytest

from app.services.form import DISPOSABLE_EMAIL_DOMAINS, SPAM_PATTERNS


def test_disposable_email_domains():
    """Verify list of known disposable spam domains."""
    assert "mailinator.com" in DISPOSABLE_EMAIL_DOMAINS
    assert "tempmail.com" in DISPOSABLE_EMAIL_DOMAINS
    assert "gmail.com" not in DISPOSABLE_EMAIL_DOMAINS


def test_spam_patterns_detection():
    """Verify regex patterns match common spam triggers."""
    text_spam = "Buy cheap crypto airdrop now!"
    matched = any(pattern.search(text_spam) for pattern, score in SPAM_PATTERNS)
    assert matched is True

    text_clean = "Hi, I would like to inquire about your enterprise pricing."
    assert not any(pattern.search(text_clean) for pattern, score in SPAM_PATTERNS if "crypto" in pattern.pattern)
