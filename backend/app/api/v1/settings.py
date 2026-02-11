from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.settings import UserSettings
from app.schemas.settings import SettingsResponse, SettingsUpdate
from app.services.scheduler_service import scheduler_service

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's settings
    """
    settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()

    if not settings:
        # Create default settings
        settings = UserSettings(
            user_id=current_user.id,
            fetch_hours=["8", "12", "18"],
            importance_threshold=0.5,
            theme="system",
            audio_language="zh"
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return SettingsResponse.model_validate(settings)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    settings_update: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update current user's settings
    """
    settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()

    if not settings:
        settings = UserSettings(user_id=current_user.id)
        db.add(settings)

    # Update fields
    update_data = settings_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(settings, field, value)

    db.commit()
    db.refresh(settings)

    # Update scheduler if fetch_hours changed
    if "fetch_hours" in update_data:
        hours = [int(h) for h in settings.fetch_hours]
        scheduler_service.update_user_schedule(current_user.id, hours)

    return SettingsResponse.model_validate(settings)


@router.get("/fetch-hours")
async def get_available_fetch_hours():
    """
    Get available hours for scheduling (0-23)
    """
    return {
        "hours": list(range(24)),
        "description": "Select hours for automatic news fetching (Beijing time)"
    }
