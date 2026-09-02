import pytest
from loguru import logger

from app.core.logger import setup_logger


def test_setup_logger():
    """Verify setup_logger configures loguru correctly."""
    log = setup_logger()
    assert log is not None
    # Verify logger can write messages without error
    log.info("Test logging message")
    log.debug("Test debug message")

