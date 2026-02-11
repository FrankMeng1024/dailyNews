from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.audio import AudioRecording
from app.schemas.audio import (
    AudioCreate, AudioResponse, AudioDetailResponse,
    AudioListResponse, AudioStatusResponse
)
from app.schemas.news import NewsResponse
from app.services.audio_service import audio_service
from app.services.tts_service import tts_service

router = APIRouter(prefix="/audio", tags=["Audio"])


@router.get("", response_model=AudioListResponse)
async def list_audio(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List user's audio recordings
    """
    query = db.query(AudioRecording).filter(AudioRecording.user_id == current_user.id)

    if status:
        query = query.filter(AudioRecording.status == status)

    total = query.count()

    # Order by creation date (newest first)
    query = query.order_by(desc(AudioRecording.created_at))

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
    Check audio generation status
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
        message = "Waiting to start..."
    elif audio.status == "processing":
        message = "Generating audio..."
        progress = 50
    elif audio.status == "completed":
        message = "Audio ready"
        progress = 100
    elif audio.status == "failed":
        message = audio.error_message or "Generation failed"

    return AudioStatusResponse(
        status=audio.status,
        progress=progress,
        message=message
    )


@router.get("/{audio_id}/stream")
async def stream_audio(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stream audio file
    """
    audio = db.query(AudioRecording).filter(
        AudioRecording.id == audio_id,
        AudioRecording.user_id == current_user.id
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
