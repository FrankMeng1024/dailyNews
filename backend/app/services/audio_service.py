import asyncio
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.news import News
from app.models.audio import AudioRecording, AudioNews
from app.services.glm_service import glm_service
from app.services.tts_service import tts_service

logger = logging.getLogger(__name__)

# In-memory progress tracking
_audio_progress: Dict[int, Dict[str, Any]] = {}


def get_audio_progress(audio_id: int) -> Optional[Dict[str, Any]]:
    """Get progress for an audio generation task"""
    return _audio_progress.get(audio_id)


def set_audio_progress(audio_id: int, progress: int, stage: str):
    """Set progress for an audio generation task"""
    _audio_progress[audio_id] = {
        "progress": progress,
        "stage": stage
    }


def clear_audio_progress(audio_id: int):
    """Clear progress after completion"""
    _audio_progress.pop(audio_id, None)


def get_user_friendly_error(error_msg: str) -> str:
    """将技术错误转换为用户友好的错误信息"""
    if not error_msg:
        return "生成失败，请稍后重试"

    error_lower = error_msg.lower()

    if 'connectionerror' in error_lower or 'timeout' in error_lower or 'connection' in error_lower:
        return "网络连接失败，请检查网络后重试"
    if '429' in error_msg or 'rate limit' in error_lower:
        return "AI服务暂时繁忙，请稍后再试"
    if '对话脚本太短' in error_msg:
        return "生成的对话内容过短，请尝试选择更多新闻"
    if '音频时长太短' in error_msg:
        return "生成的音频过短，请选择内容更丰富的新闻"
    if '语音合成失败' in error_msg:
        return "语音合成服务暂时不可用，请稍后重试"
    if 'glm' in error_lower or 'api' in error_lower:
        return "AI服务暂时不可用，请稍后重试"
    if '解析失败' in error_msg or 'json' in error_lower:
        return "AI返回格式错误，请重试"

    # 如果已经是用户友好的消息，直接返回
    if any(x in error_msg for x in ['请', '失败', '错误', '不可用']):
        return error_msg

    return "生成失败，请稍后重试"


class AudioService:
    """Service for audio generation orchestration"""

    async def create_audio(
        self,
        db: Session,
        user_id: int,
        news_ids: List[int],
        title: Optional[str] = None,
        language: str = "zh",
        voice_female: Optional[str] = None,
        voice_male: Optional[str] = None,
        host_female_name: Optional[str] = None,
        host_male_name: Optional[str] = None,
        speed: float = 1.15
    ) -> AudioRecording:
        """
        Create a new audio recording from selected news

        Args:
            db: Database session
            user_id: User ID
            news_ids: List of news IDs to include
            title: Optional custom title from user
            language: Audio language (zh, en, bilingual)
            voice_female: Female voice ID
            voice_male: Male voice ID
            host_female_name: Custom female host name
            host_male_name: Custom male host name
            speed: Speech speed (0.5-2.0)

        Returns:
            Created AudioRecording object
        """
        # Fetch news articles
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()

        if not news_list:
            raise ValueError("No valid news articles found")

        # Use custom title if provided, otherwise generate default
        if title and title.strip():
            audio_title = title.strip()[:100]  # Limit to 100 chars
        else:
            # Generate default title from first news
            audio_title = f"AI资讯 - {news_list[0].title[:50]}..."
            if len(news_list) > 1:
                audio_title = f"AI资讯 ({len(news_list)} 篇)"

        # Create audio record
        audio = AudioRecording(
            user_id=user_id,
            title=audio_title,
            file_path="",
            language=language,
            status="pending"
        )
        db.add(audio)
        db.commit()
        db.refresh(audio)

        # Create audio-news associations
        for i, news in enumerate(news_list):
            audio_news = AudioNews(
                audio_id=audio.id,
                news_id=news.id,
                display_order=i
            )
            db.add(audio_news)
        db.commit()

        # Start background generation
        asyncio.create_task(self._generate_audio_background(
            db, audio.id, news_list, language, voice_female, voice_male,
            host_female_name, host_male_name, speed
        ))

        return audio

    async def _generate_audio_background(
        self,
        db: Session,
        audio_id: int,
        news_list: List[News],
        language: str,
        voice_female: Optional[str] = None,
        voice_male: Optional[str] = None,
        host_female_name: Optional[str] = None,
        host_male_name: Optional[str] = None,
        speed: float = 1.15
    ):
        """
        Background task to generate audio with progress tracking

        Args:
            db: Database session
            audio_id: Audio recording ID
            news_list: List of news articles
            language: Audio language
            voice_female: Female voice ID
            voice_male: Male voice ID
            host_female_name: Custom female host name
            host_male_name: Custom male host name
            speed: Speech speed (0.5-2.0)
        """
        from app.database import SessionLocal

        # Use new session for background task
        db = SessionLocal()

        try:
            # Update status to processing
            audio = db.query(AudioRecording).filter(AudioRecording.id == audio_id).first()
            if not audio:
                return

            audio.status = "processing"
            db.commit()

            # Progress: 0-30% for dialogue generation
            set_audio_progress(audio_id, 5, "准备新闻内容")
            logger.info(f"Audio {audio_id}: Starting dialogue generation")

            # Generate dialogue script with custom host names
            set_audio_progress(audio_id, 10, "生成对话脚本")
            dialogue = await glm_service.generate_dialogue_script(
                news_list, language,
                host_female_name=host_female_name,
                host_male_name=host_male_name
            )

            # Validate dialogue has enough turns
            if len(dialogue) < 5:
                raise Exception(f"对话脚本太短，只有{len(dialogue)}轮，需要至少5轮")

            set_audio_progress(audio_id, 30, "对话脚本完成")
            logger.info(f"Audio {audio_id}: Dialogue generated with {len(dialogue)} turns")

            # Progress callback for TTS (30-90%)
            def tts_progress_callback(progress: int, stage: str):
                set_audio_progress(audio_id, progress, stage)
                logger.info(f"Audio {audio_id}: {stage} ({progress}%)")

            # Generate audio from dialogue
            result = await tts_service.generate_dialogue_audio(
                dialogue,
                language=language,
                voice_female=voice_female,
                voice_male=voice_male,
                speed=speed,
                progress_callback=tts_progress_callback
            )

            # Validate audio duration
            if result["duration"] < 30:
                raise Exception(f"音频时长太短，只有{result['duration']}秒，需要至少30秒")

            # Update audio record
            set_audio_progress(audio_id, 95, "保存音频文件")
            audio.file_path = result["file_path"]
            audio.file_size = result["file_size"]
            audio.duration = result["duration"]
            audio.transcript = result.get("transcript")
            audio.status = "completed"
            db.commit()

            set_audio_progress(audio_id, 100, "完成")
            logger.info(f"Audio {audio_id}: Generation complete - {result['duration']}s, {result['file_size']} bytes")

        except Exception as e:
            logger.error(f"Audio {audio_id}: Generation failed - {e}")
            # Update status to failed with user-friendly error message
            audio = db.query(AudioRecording).filter(AudioRecording.id == audio_id).first()
            if audio:
                audio.status = "failed"
                audio.error_message = get_user_friendly_error(str(e))
                db.commit()
            set_audio_progress(audio_id, 0, f"失败: {get_user_friendly_error(str(e))[:30]}")

        finally:
            db.close()
            # Clear progress after a delay to allow final status check
            await asyncio.sleep(5)
            clear_audio_progress(audio_id)

    def get_audio_with_news(self, db: Session, audio_id: int) -> Optional[dict]:
        """
        Get audio recording with associated news

        Args:
            db: Database session
            audio_id: Audio recording ID

        Returns:
            Dict with audio and news data
        """
        audio = db.query(AudioRecording).filter(AudioRecording.id == audio_id).first()

        if not audio:
            return None

        # Get associated news
        audio_news_items = db.query(AudioNews).filter(
            AudioNews.audio_id == audio_id
        ).order_by(AudioNews.display_order).all()

        news_ids = [an.news_id for an in audio_news_items]
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()

        # Sort news by display order
        news_map = {n.id: n for n in news_list}
        sorted_news = [news_map[nid] for nid in news_ids if nid in news_map]

        return {
            "audio": audio,
            "news": sorted_news
        }

    def delete_audio(self, db: Session, audio_id: int, user_id: int) -> bool:
        """
        Delete audio recording

        Args:
            db: Database session
            audio_id: Audio recording ID
            user_id: User ID (for authorization)

        Returns:
            True if deleted, False otherwise
        """
        audio = db.query(AudioRecording).filter(
            AudioRecording.id == audio_id,
            AudioRecording.user_id == user_id
        ).first()

        if not audio:
            return False

        # Delete file
        if audio.file_path:
            tts_service.delete_audio(audio.file_path)

        # Delete record (cascade deletes audio_news)
        db.delete(audio)
        db.commit()

        return True


audio_service = AudioService()
