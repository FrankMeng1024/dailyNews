from sqlalchemy import Column, Integer, String, DateTime, func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    openid = Column(String(64), unique=True, nullable=False, index=True, comment="WeChat OpenID")
    session_key = Column(String(128), comment="WeChat session key (encrypted)")
    nickname = Column(String(64), default=None)
    avatar_url = Column(String(512), default=None)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
