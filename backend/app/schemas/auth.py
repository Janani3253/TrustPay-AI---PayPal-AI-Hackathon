from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Schema for public customer registration."""

    name: str = Field(..., min_length=1, max_length=120, description="Full customer name")
    email: EmailStr = Field(..., description="Customer email address")
    password: str = Field(..., min_length=8, max_length=72, description="Password (8 to 72 bytes)")

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank.")
        return cleaned

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    """Schema for customer authentication / login."""

    email: EmailStr = Field(..., description="Customer email address")
    password: str = Field(..., min_length=1, max_length=256, description="Password")

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        return v.strip().lower()


class UserResponse(BaseModel):
    """Public customer profile matching frontend contract."""

    id: int
    name: str
    email: EmailStr

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Token response matching frontend contract."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse


class LogoutResponse(BaseModel):
    """Response returned after server-side session revocation."""

    message: str = "Logged out successfully"


class UserProfileResponse(BaseModel):
    """Detailed profile response for /api/users/profile."""

    id: int
    name: str
    email: EmailStr
    role: str = "customer"
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}

