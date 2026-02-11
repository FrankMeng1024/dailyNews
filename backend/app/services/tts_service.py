import httpx
import os
import uuid
from typing import List, Dict, Optional
from pathlib import Path

from app.config import settings


class TTSService:
    """Service for Zhipu GLM Text-to-Speech"""

    def __init__(self):
        self.api_key = settings.GLM_API_KEY
        self.tts_url = settings.GLM_TTS_URL
        self.storage_path = Path(settings.AUDIO_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def text_to_speech(
        self,
        text: str,
        voice: str = "female",
        speed: float = 1.0
    ) -> bytes:
        """
        Convert text to speech using GLM-TTS

        Args:
            text: Text to convert
            voice: Voice type (female/male)
            speed: Speech speed (0.5-2.0)

        Returns:
            Audio bytes (MP3 format)
        """
        # Map voice to GLM voice IDs
        voice_map = {
            "female": "female-1",
            "male": "male-1",
            "Alice": "female-1",
            "Bob": "male-1",
            "小雅": "female-1",
            "小明": "male-1"
        }

        voice_id = voice_map.get(voice, "female-1")

        payload = {
            "model": "glm-4-voice",
            "input": text,
            "voice": voice_id,
            "speed": speed,
            "response_format": "mp3"
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                self.tts_url,
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            return response.content

    async def generate_dialogue_audio(
        self,
        dialogue: List[Dict[str, str]],
        output_filename: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Generate audio from dialogue script

        Args:
            dialogue: List of dialogue turns with speaker and text
            output_filename: Optional output filename

        Returns:
            Dict with file_path, duration, file_size
        """
        if not output_filename:
            output_filename = f"{uuid.uuid4().hex}.mp3"

        output_path = self.storage_path / output_filename
        audio_segments = []

        # Generate audio for each dialogue turn
        for turn in dialogue:
            speaker = turn.get("speaker", "Alice")
            text = turn.get("text", "")

            if not text.strip():
                continue

            try:
                audio_bytes = await self.text_to_speech(text, voice=speaker)
                audio_segments.append(audio_bytes)
            except Exception as e:
                # Log error but continue with other segments
                print(f"TTS error for segment: {e}")
                continue

        if not audio_segments:
            raise Exception("No audio segments generated")

        # Combine audio segments
        combined_audio = self._combine_audio_segments(audio_segments)

        # Save to file
        with open(output_path, "wb") as f:
            f.write(combined_audio)

        # Get file info
        file_size = os.path.getsize(output_path)
        duration = self._estimate_duration(combined_audio)

        return {
            "file_path": str(output_filename),
            "file_size": file_size,
            "duration": duration
        }

    def _combine_audio_segments(self, segments: List[bytes]) -> bytes:
        """
        Combine multiple MP3 audio segments

        For simplicity, we concatenate MP3 files directly.
        For production, consider using pydub for proper merging.

        Args:
            segments: List of MP3 audio bytes

        Returns:
            Combined audio bytes
        """
        # Simple concatenation for MP3 files
        # Note: This works for basic cases but may have issues with headers
        combined = b""
        for segment in segments:
            combined += segment
        return combined

    def _estimate_duration(self, audio_bytes: bytes) -> int:
        """
        Estimate audio duration in seconds

        Args:
            audio_bytes: MP3 audio bytes

        Returns:
            Estimated duration in seconds
        """
        # Rough estimate: MP3 at 128kbps = 16KB per second
        return len(audio_bytes) // 16000

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
