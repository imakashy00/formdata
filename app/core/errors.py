from enum import Enum

from fastapi import status


class ToastType(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    toast_type: ToastType = ToastType.ERROR  # Enforced by Enum
    default_message: str = "Something went wrong."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "That item could not be found."


class DuplicateError(AppError):
    status_code = status.HTTP_409_CONFLICT
    toast_type = ToastType.ERROR
    default_message = "This already exists."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "You do not have permission to perform this action."


class TypeCoversionError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    toast_type = ToastType.ERROR
    default_message = "Invalid Input"


class WorkbookFailed(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    toast_type = ToastType.ERROR
    default_message = "Failed To initialize XLS WorkBook"


class IncorrectCloudflareTournstileKey(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    toast_type = ToastType.ERROR
    default_message = "Tournstile secret key length must be 40"
