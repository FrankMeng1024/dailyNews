import asyncio
import edge_tts
import os
import uuid
import logging
import io
from typing import List, Dict, Optional, Callable
from pathlib import Path

from pydub import AudioSegment

from app.config import settings

logger = logging.getLogger(__name__)


class TTSService:
    """Service for Text-to-Speech using Edge TTS (free, reliable)"""

    # Edge TTS voice mapping
    VOICES = {
        # Chinese voices
        "zh_female": "zh-CN-XiaoxiaoNeural",
        "zh_male": "zh-CN-YunxiNeural",
        "小雅": "zh-CN-XiaoxiaoNeural",
        "小明": "zh-CN-YunxiNeural",
        "Alice": "zh-CN-XiaoxiaoNeural",
        "Bob": "zh-CN-YunxiNeural",
        # English voices
        "en_female": "en-US-JennyNeural",
        "en_male": "en-US-GuyNeural",
        "female": "zh-CN-XiaoxiaoNeural",
        "male": "zh-CN-YunxiNeural",
    }

    def __init__(self):
        self.storage_path = Path(settings.AUDIO_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def text_to_speech(
        self,
        text: str,
        voice: str = "female",
        speed: float = 1.0,
        language: str = "zh",
        max_retries: int = 3
    ) -> bytes:
        """
        Convert text to speech using Edge TTS with retry logic

        Args:
            text: Text to convert
            voice: Voice type or name
            speed: Speech speed (0.5-2.0)
            language: Language code (zh/en)
            max_retries: Maximum retry attempts

        Returns:
            Audio bytes (MP3 format)
        """
        # Get voice ID
        voice_id = self.VOICES.get(voice)
        if not voice_id:
            # Default based on language
            if language == "en":
                voice_id = self.VOICES["en_female"]
            else:
                voice_id = self.VOICES["zh_female"]

        # Convert speed to Edge TTS rate format (+0% to +100% or -50% etc)
        rate_percent = int((speed - 1.0) * 100)
        rate = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"

        last_error = None
        for attempt in range(max_retries):
            try:
                logger.debug(f"TTS request - voice: {voice_id}, rate: {rate}, text_len: {len(text)}, text_preview: {text[:100]}...")
                communicate = edge_tts.Communicate(text, voice_id, rate=rate)
                audio_data = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data += chunk["data"]

                # Validate audio data is not empty
                if not audio_data or len(audio_data) < 100:
                    raise Exception(f"Empty or invalid audio data received ({len(audio_data)} bytes)")

                return audio_data
            except Exception as e:
                last_error = e
                logger.warning(f"TTS attempt {attempt + 1}/{max_retries} failed - voice: {voice_id}, rate: {rate}, text_len: {len(text)}, error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.5)  # Wait before retry

        logger.error(f"TTS failed after {max_retries} attempts - voice: {voice_id}, rate: {rate}, text: {text[:200]}..., error: {last_error}")
        raise last_error

    async def generate_dialogue_audio(
        self,
        dialogue: List[Dict[str, str]],
        output_filename: Optional[str] = None,
        language: str = "zh",
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, any]:
        """
        Generate audio from dialogue script

        Args:
            dialogue: List of dialogue turns with speaker and text
            output_filename: Optional output filename
            language: Language code (zh/en/bilingual)
            progress_callback: Optional callback(progress_percent, stage_message)

        Returns:
            Dict with file_path, duration, file_size
        """
        if not output_filename:
            output_filename = f"{uuid.uuid4().hex}.mp3"

        output_path = self.storage_path / output_filename
        audio_segments = []

        total_turns = len(dialogue)
        logger.info(f"Generating audio for {total_turns} dialogue turns")

        # Generate audio for each dialogue turn
        for i, turn in enumerate(dialogue):
            speaker = turn.get("speaker", "小雅")
            text = turn.get("text", "")

            if not text.strip():
                continue

            # Report progress - 30-90% for TTS generation
            if progress_callback:
                progress = 30 + int(((i + 1) / total_turns) * 60)  # 30-90%
                progress_callback(progress, f"语音合成 ({i+1}/{total_turns})")

            try:
                # Determine voice based on speaker
                if speaker in ["Alice", "小雅", "女"]:
                    voice = "zh_female" if language != "en" else "en_female"
                else:
                    voice = "zh_male" if language != "en" else "en_male"

                audio_bytes = await self.text_to_speech(
                    text,
                    voice=voice,
                    language=language
                )
                audio_segments.append(audio_bytes)
                logger.info(f"Generated segment {i+1}/{total_turns}: {len(audio_bytes)} bytes")
            except Exception as e:
                logger.error(f"TTS error for segment {i+1}: {e}")
                raise Exception(f"TTS failed for segment {i+1}: {e}")

        if not audio_segments:
            raise Exception("No audio segments generated")

        # Report combining progress
        if progress_callback:
            progress_callback(92, "合并音频...")

        # Combine audio segments using pydub
        combined_audio, duration = self._combine_audio_segments_pydub(audio_segments)
        logger.info(f"Combined audio: {len(combined_audio)} bytes, {duration}s")

        # Save to file
        with open(output_path, "wb") as f:
            f.write(combined_audio)

        # Get file info
        file_size = os.path.getsize(output_path)

        if progress_callback:
            progress_callback(100, "Audio generation complete")

        logger.info(f"Audio saved: {output_filename}, {file_size} bytes, {duration}s")

        return {
            "file_path": str(output_filename),
            "file_size": file_size,
            "duration": duration
        }

    def _combine_audio_segments_pydub(self, segments: List[bytes]) -> tuple:
        """
        Combine multiple MP3 audio segments using pydub for proper handling

        Args:
            segments: List of MP3 audio bytes

        Returns:
            Tuple of (combined audio bytes, duration in seconds)
        """
        combined = AudioSegment.empty()
        silence = AudioSegment.silent(duration=300)  # 300ms silence between segments

        for i, segment_bytes in enumerate(segments):
            try:
                # Load MP3 from bytes
                segment = AudioSegment.from_mp3(io.BytesIO(segment_bytes))

                # Add silence between segments (except before first)
                if i > 0:
                    combined += silence

                combined += segment
            except Exception as e:
                logger.error(f"Error processing segment {i}: {e}")
                continue

        # Export to MP3 bytes
        output_buffer = io.BytesIO()
        combined.export(output_buffer, format="mp3", bitrate="128k")
        output_bytes = output_buffer.getvalue()

        # Get accurate duration in seconds
        duration = int(len(combined) / 1000)  # pydub uses milliseconds

        return output_bytes, duration

    def get_audio_path(self, filename: str) -> Path:
        """Get full path to audio file"""
        return self.storage_path / filename

    def delete_audio(self, filename: str) -> bool:
        """Delete audio file"""
        try:
            path = self.storage_path / filename
            if path.exists():
                path.unlink()
                return True
            return False
        except:
            return False


tts_service = TTSService()
