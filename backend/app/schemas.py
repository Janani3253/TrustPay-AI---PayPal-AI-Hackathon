from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse


class IntentRequest(BaseModel):
    request: str = Field(min_length=1, max_length=2000)
    maximumBudget: float = Field(gt=0)
    currency: Literal["USD", "INR"] = "USD"
    category: str = ""
    trustedSellersOnly: bool = True
    platformId: str = "dummyjson"


class OrderRequest(BaseModel):
    intent: dict


class VerifyOrderRequest(BaseModel):
    order_id: str


class ApprovalRequest(BaseModel):
    order_version: int = Field(ge=1)


class CartItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=99)


class CartQuantityRequest(BaseModel):
    quantity: int = Field(ge=1, le=99)


class PayPalCaptureRequest(BaseModel):
    paypal_order_id: str = Field(min_length=1, max_length=128)
