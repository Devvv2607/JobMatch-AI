import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Credentials(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "asha@example.com", "password": "correct horse battery"}]
        }
    )

    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    """Login does not apply the registration length rule, so a wrong short password
    gets the same "invalid credentials" answer as any other wrong password."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class SessionOut(BaseModel):
    """The access token lives in memory in the browser. The refresh token is set as an
    httpOnly cookie and never appears in a response body."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int = Field(description="Seconds until the access token expires")
    user: UserOut
