from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from typing import Optional
import logging

from app.database import get_db
from app.api.deps import get_current_user, verify_token
from app.models.user import User
from app.models.audio import AudioRecording
from app.schemas.audio import (
    AudioCreate, AudioResponse, AudioDetailResponse,
    AudioListResponse, AudioStatusResponse
)
from app.schemas.news import NewsResponse
from app.services.audio_service import audio_service, get_audio_progress
from app.services.tts_service import tts_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["Audio"])


@router.get("", response_model=AudioListResponse)
async def list_audio(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    favorite_only: bool = Query(False, description="Filter favorites only"),
    sort_by: str = Query("created_at", description="Sort field: created_at, title, duration"),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List user's audio recordings
    """
    query = db.query(AudioRecording).filter(AudioRecording.user_id == current_user.id)

    if status:
        query = query.filter(AudioRecording.status == status)

    if favorite_only:
        query = query.filter(AudioRecording.is_favorite == True)

    total = query.count()

    # Dynamic sorting (with validation)
    if sort_by not in ["created_at", "title", "duration"]:
        sort_by = "created_at"
    if sort_order not in ["asc", "desc"]:
        sort_order = "desc"

    sort_column = getattr(AudioRecording, sort_by)
    if sort_order == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(asc(sort_column))

    # Paginate
    offset = (page - 1) * limit
    audio_list = query.offset(offset).limit(limit).all()

    return AudioListResponse(
        items=[AudioResponse.model_validate(a) for a in audio_list],
        total=total,
        page=page,
        limit=limit
    )


@router.post("", response_model=AudioResponse)
async def create_audio(
    request: AudioCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create new audio from selected news articles
    """
    if not request.news_ids:
        raise HTTPException(status_code=400, detail="No news articles selected")

    if len(request.news_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 articles per audio")

    try:
        audio = await audio_service.create_audio(
            db=db,
            user_id=current_user.id,
            news_ids=request.news_ids,
            title=request.title,
            language=request.language.value
        )
        return AudioResponse.model_validate(audio)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create audio: {str(e)}")


@router.get("/{audio_id}", response_model=AudioDetailResponse)
async def get_audio_detail(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get audio recording detail with associated news
    """
    result = audio_service.get_audio_with_news(db, audio_id)

    if not result:
        raise HTTPException(status_code=404, detail="Audio not found")

    audio = result["audio"]

    # Check ownership
    if audio.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return AudioDetailResponse(
        id=audio.id,
        title=audio.title,
        file_path=audio.file_path,
        file_size=audio.file_size,
        duration=audio.duration,
        language=audio.language,
        status=audio.status,
        error_message=audio.error_message,
        created_at=audio.created_at,
        news=[NewsResponse.model_validate(n) for n in result["news"]]
    )


@router.get("/{audio_id}/status", response_model=AudioStatusResponse)
async def get_audio_status(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check audio generation status with real-time progress
    """
    audio = db.query(AudioRecording).filter(
        AudioRecording.id == audio_id,
        AudioRecording.user_id == current_user.id
    ).first()

    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")

    progress = None
    message = None

    if audio.status == "pending":
        message = "等待开始..."
        progress = 0
    elif audio.status == "processing":
        # Get real-time progress from in-memory tracking
        progress_info = get_audio_progress(audio_id)
        if progress_info:
            progress = progress_info.get("progress", 50)
            message = progress_info.get("stage", "生成中...")
        else:
            message = "生成中..."
            progress = 50
    elif audio.status == "completed":
        message = "音频已就绪"
        progress = 100
    elif audio.status == "failed":
        message = audio.error_message or "生成失败"
        progress = 0

    return AudioStatusResponse(
        status=audio.status,
        progress=progress,
        message=message
    )


@router.get("/{audio_id}/stream")
async def stream_audio(
    audio_id: int,
    token: Optional[str] = Query(None, description="Auth token (for miniprogram)"),
    db: Session = Depends(get_db)
):
    """
    Stream audio file
    Supports query param token for miniprogram audio player compatibility
    """
    if not token:
        raise HTTPException(status_code=401, detail="Token required")

    # Verify token
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    audio = db.query(AudioRecording).filter(
        AudioRecording.id == audio_id,
        AudioRecording.user_id == user.id
    ).first()

    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")

    if audio.status != "completed":
        raise HTTPException(status_code=400, detail="Audio not ready")

    if not audio.file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    file_path = tts_service.get_audio_path(audio.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        path=str(file_path),
        media_type="audio/mpeg",
        filename=f"{audio.title}.mp3"
    )


@router.delete("/{audio_id}")
async def delete_audio(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete audio recording
    """
    success = audio_service.delete_audio(db, audio_id, current_user.id)

    if not success:
        raise HTTPException(status_code=404, detail="Audio not found")

    return {"success": True, "message": "Audio deleted"}


@router.post("/{audio_id}/favorite")
async def toggle_favorite(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Toggle audio favorite status
    """
    audio = db.query(AudioRecording).filter(
        AudioRecording.id == audio_id,
        AudioRecording.user_id == current_user.id
    ).first()

    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")

    audio.is_favorite = not audio.is_favorite
    db.commit()

    return {"success": True, "is_favorite": audio.is_favorite}
