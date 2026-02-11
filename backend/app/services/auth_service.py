import httpx
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.models.settings import UserSettings
from app.api.deps import create_access_token


class AuthService:
    """Service for WeChat authentication"""

    WECHAT_LOGIN_URL = "https://api.weixin.qq.com/sns/jscode2session"

    async def wechat_code_to_session(self, code: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Exchange WeChat login code for session info
        Returns: (openid, session_key, error_message)
        """
        params = {
            "appid": settings.WECHAT_APP_ID,
            "secret": settings.WECHAT_APP_SECRET,
            "js_code": code,
            "grant_type": "authorization_code"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.WECHAT_LOGIN_URL, params=params)
                data = response.json()

                if "errcode" in data and data["errcode"] != 0:
                    return None, None, data.get("errmsg", "WeChat login failed")

                openid = data.get("openid")
                session_key = data.get("session_key")

                if not openid:
                    return None, None, "Failed to get openid from WeChat"

                return openid, session_key, None

            except Exception as e:
                return None, None, f"WeChat API error: {str(e)}"

    def get_or_create_user(self, db: Session, openid: str, session_key: Optional[str] = None) -> User:
        """Get existing user or create new one"""
        user = db.query(User).filter(User.openid == openid).first()

        if user:
            # Update session key if provided
            if session_key:
                user.session_key = session_key
                db.commit()
            return user

        # Create new user
        user = User(openid=openid, session_key=session_key)
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create default settings for new user
        user_settings = UserSettings(
            user_id=user.id,
            fetch_hours=["8", "12", "18"],
            importance_threshold=0.5,
            theme="system",
            audio_language="zh"
        )
        db.add(user_settings)
        db.commit()

        return user

    def create_user_token(self, user: User) -> str:
        """Create JWT token for user"""
        return create_access_token(data={"sub": user.id})


auth_service = AuthService()
