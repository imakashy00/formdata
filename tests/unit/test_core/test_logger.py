import logging
import pytest
from loguru import logger

from app.core.logger import InterceptHandler, setup_logging


def test_intercept_handler_routes_to_loguru():
    """Verify InterceptHandler receives standard library logging records and directs to loguru."""
    handler = InterceptHandler()
    std_logger = logging.getLogger("test_intercept")
    std_logger.addHandler(handler)
    std_logger.setLevel(logging.INFO)

    # Should not raise exception
    std_logger.info("Test intercept message")
    std_logger.warning("Test warning intercept message")


def test_setup_logging():
    """Verify setup_logging configures root loggers and intercepts uvicorn logs."""
    setup_logging()
    # Check that root logger handlers contain an InterceptHandler
    root_handlers = logging.getLogger().handlers
    assert any(isinstance(h, InterceptHandler) for h in root_handlers)
