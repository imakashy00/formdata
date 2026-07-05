from loguru import logger
import os

def setup_logger():
    """Configure Loguru and integrate with Uvicorn/Fastapi logs"""
    logger.remove()
    if not os.path.exists("logs"):
        os.mkdir("logs")

    logger.add(
        "logs/app.log",
        rotation="1 MB",
        retention="1 days",
        compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    return logger
