from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None


class UserCreate(BaseModel):
    code: str  # WeChat login code


class UserResponse(BaseModel):
    id: int
    openid: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginRequest(BaseModel):
    code: str
