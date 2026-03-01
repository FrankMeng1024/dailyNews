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
    AudioListResponse, AudioStatusResponse, VoiceListResponse,
    TranscriptResponse, TranscriptItem
)
from app.schemas.news import NewsResponse
from app.services.audio_service import audio_service, get_audio_progress
from app.services.tts_service import tts_service, TTSService
from app.services.glm_tts_service import glm_tts_service, GLMTTSService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["Audio"])


@router.get("/voices", response_model=VoiceListResponse)
async def get_voices():
    """
    Get available voice options for audio generation
    """
    options = TTSService.get_voice_options()
    return VoiceListResponse(
        female=options["female"],
        male=options["male"]
    )


@router.get("/voices/glm")
async def get_glm_voices():
    """
    Get available GLM-TTS voice options
    """
    return GLMTTSService.get_voice_options()


@router.get("/tts-compare")
async def compare_tts(
    text: str = Query(default="大家好，欢迎收听今天的AI资讯播客，精彩内容马上开始。", description="要合成的文本"),
    voice_type: str = Query(default="female", description="语音类型: female 或 male")
):
    """
    对比 Edge TTS 和 GLM-TTS 的效果
    返回两个引擎生成的音频供试听
    """
    # 选择对应的语音
    if voice_type == "female":
        edge_voice = "zh-CN-XiaoxiaoNeural"
        glm_voice = "female-tianmei"
    else:
        edge_voice = "zh-CN-YunxiNeural"
        glm_voice = "male-qinqie"

    results = {}
    errors = {}

    # 生成 Edge TTS
    try:
        edge_audio = await tts_service.text_to_speech(text, voice=edge_voice)
        results["edge_tts"] = edge_audio
    except Exception as e:
        logger.error(f"Edge TTS error: {e}")
        errors["edge_tts"] = str(e)

    # 生成 GLM TTS
    try:
        glm_audio = await glm_tts_service.text_to_speech(text, voice=glm_voice)
        results["glm_tts"] = glm_audio
    except Exception as e:
        logger.error(f"GLM TTS error: {e}")
        errors["glm_tts"] = str(e)

    if not results:
        raise HTTPException(status_code=500, detail=f"Both TTS failed: {errors}")

    # 返回对比信息
    return {
        "text": text,
        "voice_type": voice_type,
        "edge_voice": edge_voice,
        "glm_voice": glm_voice,
        "available": list(results.keys()),
        "errors": errors if errors else None
    }


@router.get("/tts-compare/edge")
async def get_edge_tts_preview(
    text: str = Query(default="大家好，欢迎收听今天的AI资讯播客，精彩内容马上开始。"),
    voice_type: str = Query(default="female")
):
    """
    获取 Edge TTS 试听音频
    """
    voice = "zh-CN-XiaoxiaoNeural" if voice_type == "female" else "zh-CN-YunxiNeural"
    try:
        audio_bytes = await tts_service.text_to_speech(text, voice=voice)
        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=edge_preview.mp3"}
        )
    except Exception as e:
        logger.error(f"Edge TTS preview error: {e}")
        raise HTTPException(status_code=500, detail=f"Edge TTS failed: {str(e)}")


@router.get("/tts-compare/glm")
async def get_glm_tts_preview(
    text: str = Query(default="大家好，欢迎收听今天的AI资讯播客，精彩内容马上开始。"),
    voice_type: str = Query(default="female")
):
    """
    获取 GLM TTS 试听音频
    """
    voice = "female-tianmei" if voice_type == "female" else "male-qinqie"
    try:
        audio_bytes = await glm_tts_service.text_to_speech(text, voice=voice)
        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=glm_preview.mp3"}
        )
    except Exception as e:
        logger.error(f"GLM TTS preview error: {e}")
        raise HTTPException(status_code=500, detail=f"GLM TTS failed: {str(e)}")


@router.get("/voices/preview/{voice_id}")
async def preview_voice(voice_id: str):
    """
    Get a short audio preview for a voice (returns cached file)
    """
    # Validate voice exists
    is_female = TTSService.is_valid_voice(voice_id, "female")
    is_male = TTSService.is_valid_voice(voice_id, "male")

    if not is_female and not is_male:
        raise HTTPException(status_code=400, detail="Invalid voice ID")

    # Check for cached preview
    preview_path = tts_service.get_preview_path(voice_id)
    if preview_path.exists():
        return FileResponse(
            path=str(preview_path),
            media_type="audio/mpeg",
            filename="preview.mp3"
        )

    # Fallback: generate on-the-fly if cache missing
    if is_female:
        preview_text = "大家好，欢迎收听今天的AI资讯播客。"
    else:
        preview_text = "没错，今天我们来聊聊最新的科技动态。"

    try:
        audio_bytes = await tts_service.text_to_speech(preview_text, voice=voice_id)
        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"inline; filename=preview.mp3"}
        )
    except Exception as e:
        logger.error(f"Voice preview error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate preview")


@router.get("/{audio_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get transcript/subtitles for an audio recording
    """
    audio = db.query(AudioRecording).filter(
        AudioRecording.id == audio_id,
        AudioRecording.user_id == current_user.id
    ).first()

    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")

    if audio.status != "completed":
        raise HTTPException(status_code=400, detail="Audio not ready")

    if not audio.transcript:
        raise HTTPException(status_code=404, detail="Transcript not available")

    return TranscriptResponse(
        audio_id=audio_id,
        transcript=[TranscriptItem(**item) for item in audio.transcript]
    )


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

    if len(request.news_ids) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 articles per audio")

    # Validate voice IDs if provided
    if request.voice_female and not TTSService.is_valid_voice(request.voice_female, "female"):
        raise HTTPException(status_code=400, detail="Invalid female voice ID")
    if request.voice_male and not TTSService.is_valid_voice(request.voice_male, "male"):
        raise HTTPException(status_code=400, detail="Invalid male voice ID")

    # Validate speed range (if provided, otherwise use default)
    speed = getattr(request, 'speed', 1.15) or 1.15
    if not 0.5 <= speed <= 2.0:
        raise HTTPException(status_code=400, detail="Speed must be between 0.5 and 2.0")

    try:
        audio = await audio_service.create_audio(
            db=db,
            user_id=current_user.id,
            news_ids=request.news_ids,
            title=request.title,
            language=request.language.value,
            voice_female=request.voice_female,
            voice_male=request.voice_male,
            host_female_name=request.host_female_name,
            host_male_name=request.host_male_name,
            speed=speed
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
