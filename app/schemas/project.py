import re

from pydantic import BaseModel, field_validator


class NewProject(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_project_name(cls, value: str) -> str:
        # 2. Strip leading/trailing whitespace
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Project name must be at least 3 characters long.")
        if len(value) > 50:
            raise ValueError("Project name must be atmost 50 characters long.")

        # 3. Reject names that are just special characters or numbers (Optional)
        if value.isdigit():
            raise ValueError("Project name cannot contain only numbers.")
        if value[0].isdigit():
            raise ValueError("Project name cannot be started with numbers.")
        # 4. Enforce character safety (Alphanumeric, spaces, hyphens, underscores)
        # Prevents XSS, SQL injection risks, and URL breaking
        if not re.match(r"^[a-zA-Z0-9_\-\s]+$", value):
            raise ValueError(
                "Project name can only contain letters, numbers, spaces, hyphens, and underscores."
            )

        return value
