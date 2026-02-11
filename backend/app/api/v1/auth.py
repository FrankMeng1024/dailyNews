from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    WeChat Mini Program login
    Exchange WeChat code for JWT token
    """
    # Exchange code for WeChat session
    openid, session_key, error = await auth_service.wechat_code_to_session(request.code)

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error
        )

    # Get or create user
    user = auth_service.get_or_create_user(db, openid, session_key)

    # Create JWT token
    token = auth_service.create_user_token(user)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user info"""
    return UserResponse.model_validate(current_user)


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(db: Session = Depends(get_db)):
    """
    Development login endpoint (bypasses WeChat)
    Only for testing purposes
    """
    # Create or get a test user
    test_openid = "dev_test_user_openid"
    user = auth_service.get_or_create_user(db, test_openid)
    token = auth_service.create_user_token(user)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )
