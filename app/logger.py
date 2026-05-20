from loguru import logger

# import logging
# import sys
import os


# class InterceptHandler(logging.Handler):
#     # Redirect standard logging to loguru
#     def emit(self, record):
#         try:
#             level = logger.level(record.levelname).name
#         except ValueError:
#             level = record.levelno
#         logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logger():
    """Configure Loguru and integrate with Uvicorn/Fastapi logs"""
    # intercept uvicorn logs
    # logging.basicConfig(handlers=[InterceptHandler()], level=0)
    # for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    #     logging.getLogger(name).handlers = [InterceptHandler()]
    # # Remove default loguru handler
    logger.remove()

    # console logs
    # logger.add(
    #     sys.stdout,
    #     format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    #     "<level>{level}</level> | "
    #     "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    #     "<level>{message}</level>",
    #     level="INFO",
    #     enqueue=True,
    #     backtrace=True,
    #     diagnose=True,
    # )
    # File logs
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
