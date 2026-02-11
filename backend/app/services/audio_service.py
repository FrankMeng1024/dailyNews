import asyncio
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.news import News
from app.models.audio import AudioRecording, AudioNews
from app.services.glm_service import glm_service
from app.services.tts_service import tts_service


class AudioService:
    """Service for audio generation orchestration"""

    async def create_audio(
        self,
        db: Session,
        user_id: int,
        news_ids: List[int],
        language: str = "zh"
    ) -> AudioRecording:
        """
        Create a new audio recording from selected news

        Args:
            db: Database session
            user_id: User ID
            news_ids: List of news IDs to include
            language: Audio language (zh, en, bilingual)

        Returns:
            Created AudioRecording object
        """
        # Fetch news articles
        news_list = db.query(News).filter(News.id.in_(news_ids)).all()

        if not news_list:
            raise ValueError("No valid news articles found")

        # Generate title from first news
        title = f"AI News Discussion - {news_list[0].title[:50]}..."
        if len(news_list) > 1:
            title = f"AI News Discussion ({len(news_list)} articles)"

        # Create audio record
        audio = AudioRecording(
            user_id=user_id,
            title=title,
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
        asyncio.create_task(self._generate_audio_background(db, audio.id, news_list, language))

        return audio

    async def _generate_audio_background(
        self,
        db: Session,
        audio_id: int,
        news_list: List[News],
        language: str
    ):
        """
        Background task to generate audio

        Args:
            db: Database session
            audio_id: Audio recording ID
            news_list: List of news articles
            language: Audio language
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

            # Generate dialogue script
            dialogue = await glm_service.generate_dialogue_script(news_list, language)

            # Generate audio from dialogue
            result = await tts_service.generate_dialogue_audio(dialogue)

            # Update audio record
            audio.file_path = result["file_path"]
            audio.file_size = result["file_size"]
            audio.duration = result["duration"]
            audio.status = "completed"
            db.commit()

        except Exception as e:
            # Update status to failed
            audio = db.query(AudioRecording).filter(AudioRecording.id == audio_id).first()
            if audio:
                audio.status = "failed"
                audio.error_message = str(e)
                db.commit()

        finally:
            db.close()

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
