import asyncio
import edge_tts
import os
import uuid
import logging
import io
import re
from typing import List, Dict, Optional, Callable
from pathlib import Path

from pydub import AudioSegment

from app.config import settings

logger = logging.getLogger(__name__)

# Preview cache directory
PREVIEW_CACHE_DIR = Path(settings.AUDIO_STORAGE_PATH) / "previews"


class TTSService:
    """Service for Text-to-Speech using Edge TTS (free, reliable)"""

    # Voice options for UI selection
    VOICE_OPTIONS = {
        "female": [
            {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "desc": "温暖亲切"},
            {"id": "zh-CN-XiaoyiNeural", "name": "晓伊", "desc": "活泼可爱"},
            {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻 (台湾)", "desc": "台湾腔"},
            {"id": "zh-TW-HsiaoYuNeural", "name": "曉雨 (台湾)", "desc": "台湾腔"},
            {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北 (东北)", "desc": "东北腔"},
            {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮 (陕西)", "desc": "陕西腔"},
        ],
        "male": [
            {"id": "zh-CN-YunxiNeural", "name": "云希", "desc": "阳光活泼"},
            {"id": "zh-CN-YunjianNeural", "name": "云健", "desc": "激情澎湃"},
            {"id": "zh-CN-YunyangNeural", "name": "云扬", "desc": "专业可靠"},
            {"id": "zh-CN-YunxiaNeural", "name": "云夏", "desc": "可爱少年"},
            {"id": "zh-TW-YunJheNeural", "name": "雲哲 (台湾)", "desc": "台湾腔"},
        ]
    }

    # Default voices
    DEFAULT_VOICE_FEMALE = "zh-CN-XiaoxiaoNeural"
    DEFAULT_VOICE_MALE = "zh-CN-YunxiNeural"

    # Legacy voice mapping (for backward compatibility)
    VOICES = {
        "zh_female": "zh-CN-XiaoxiaoNeural",
        "zh_male": "zh-CN-YunxiNeural",
        "小雅": "zh-CN-XiaoxiaoNeural",
        "小明": "zh-CN-YunxiNeural",
        "Alice": "zh-CN-XiaoxiaoNeural",
        "Bob": "zh-CN-YunxiNeural",
        "en_female": "en-US-JennyNeural",
        "en_male": "en-US-GuyNeural",
        "female": "zh-CN-XiaoxiaoNeural",
        "male": "zh-CN-YunxiNeural",
    }

    @classmethod
    def get_voice_options(cls):
        """Get available voice options for API"""
        return cls.VOICE_OPTIONS

    @classmethod
    def is_valid_voice(cls, voice_id: str, gender: str) -> bool:
        """Check if voice ID is valid for given gender"""
        options = cls.VOICE_OPTIONS.get(gender, [])
        return any(v["id"] == voice_id for v in options)

    @staticmethod
    def normalize_numbers_for_tts(text: str) -> str:
        """
        Convert numbers, percentages, and symbols to readable Chinese text.
        This prevents TTS from reading "40%" as "四十百分号" instead of "百分之四十".
        """
        if not text:
            return text

        # Chinese number mapping
        cn_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
        cn_units = ['', '十', '百', '千', '万', '十万', '百万', '千万', '亿']

        def int_to_chinese(num_str: str) -> str:
            """Convert integer string to Chinese"""
            if not num_str or not num_str.isdigit():
                return num_str
            n = int(num_str)
            if n == 0:
                return '零'
            if n < 0:
                return '负' + int_to_chinese(str(-n))

            # For small numbers, read digit by digit for clarity
            if n < 10:
                return cn_nums[n]
            if n < 100:
                tens = n // 10
                ones = n % 10
                result = ('' if tens == 1 else cn_nums[tens]) + '十'
                if ones > 0:
                    result += cn_nums[ones]
                return result

            # For larger numbers, use standard Chinese number reading
            result = ''
            num_str = str(n)
            length = len(num_str)
            for i, digit in enumerate(num_str):
                d = int(digit)
                pos = length - i - 1
                if d != 0:
                    result += cn_nums[d]
                    if pos >= 8:
                        result += '亿'
                    elif pos >= 4:
                        if pos == 4:
                            result += '万'
                        elif pos == 5:
                            result += '十万'
                        elif pos == 6:
                            result += '百万'
                        elif pos == 7:
                            result += '千万'
                    elif pos == 3:
                        result += '千'
                    elif pos == 2:
                        result += '百'
                    elif pos == 1:
                        result += '十'
                elif result and not result.endswith('零') and i < length - 1:
                    result += '零'
            # Clean up trailing zeros
            result = re.sub(r'零+$', '', result)
            return result if result else '零'

        def decimal_to_chinese(num_str: str) -> str:
            """Convert decimal string to Chinese"""
            if '.' not in num_str:
                return int_to_chinese(num_str)
            parts = num_str.split('.')
            int_part = int_to_chinese(parts[0]) if parts[0] else '零'
            dec_part = ''.join(cn_nums[int(d)] for d in parts[1])
            return f"{int_part}点{dec_part}"

        # Percentage: 40% → 百分之四十, 3.5% → 百分之三点五
        def replace_percent(match):
            num = match.group(1)
            return f"百分之{decimal_to_chinese(num)}"
        text = re.sub(r'(\d+(?:\.\d+)?)\s*%', replace_percent, text)

        # Currency: $100 → 100美元, ¥100 → 100元, €50 → 50欧元
        text = re.sub(r'\$\s*(\d+(?:\.\d+)?)', lambda m: f"{decimal_to_chinese(m.group(1))}美元", text)
        text = re.sub(r'¥\s*(\d+(?:\.\d+)?)', lambda m: f"{decimal_to_chinese(m.group(1))}元", text)
        text = re.sub(r'€\s*(\d+(?:\.\d+)?)', lambda m: f"{decimal_to_chinese(m.group(1))}欧元", text)
        text = re.sub(r'£\s*(\d+(?:\.\d+)?)', lambda m: f"{decimal_to_chinese(m.group(1))}英镑", text)

        # Large numbers with units: 10亿, 5000万 (keep as is, already readable)
        # But convert standalone large numbers: 1000000 → 一百万
        def replace_large_number(match):
            num = match.group(0)
            if len(num) >= 5:  # Only convert numbers with 5+ digits
                return int_to_chinese(num)
            return num
        text = re.sub(r'\b\d{5,}\b', replace_large_number, text)

        # Time format: 10:30 → 十点三十分
        def replace_time(match):
            hour = int(match.group(1))
            minute = int(match.group(2))
            result = int_to_chinese(str(hour)) + '点'
            if minute > 0:
                result += int_to_chinese(str(minute)) + '分'
            return result
        text = re.sub(r'\b(\d{1,2}):(\d{2})\b', replace_time, text)

        # Date format: 2024-01-15 → 2024年1月15日
        def replace_date(match):
            year = match.group(1)
            month = match.group(2).lstrip('0')
            day = match.group(3).lstrip('0')
            return f"{year}年{month}月{day}日"
        text = re.sub(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', replace_date, text)

        # Fractions: 1/2 → 二分之一, 3/4 → 四分之三
        def replace_fraction(match):
            num = match.group(1)
            denom = match.group(2)
            return f"{int_to_chinese(denom)}分之{int_to_chinese(num)}"
        text = re.sub(r'\b(\d+)/(\d+)\b', replace_fraction, text)

        # Multiplication: 10x → 十倍, 2x → 两倍
        def replace_multiplier(match):
            num = match.group(1)
            n = int(num)
            if n == 2:
                return '两倍'
            return int_to_chinese(num) + '倍'
        text = re.sub(r'(\d+)\s*[xX×]\b', replace_multiplier, text)

        # Plus/minus signs: +5 → 正五, -3 → 负三
        text = re.sub(r'\+(\d+)', lambda m: f"正{int_to_chinese(m.group(1))}", text)
        text = re.sub(r'-(\d+)(?!\d)', lambda m: f"负{int_to_chinese(m.group(1))}", text)

        return text

    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        Enhanced text preprocessing for TTS to improve pronunciation and reduce unnatural pauses.

        Fixes:
        - Remove hyphens in English terms (GPT-4 → GPT4) to prevent "dash" pronunciation
        - Remove spaces between Chinese characters (prevents word splitting like "哈利 波特")
        - Remove spaces between Chinese and English/numbers (prevents pauses in mixed text)
        - Clean up punctuation that causes unnatural pauses
        """
        if not text:
            return text

        # 1. Remove all hyphens in English terms (GPT-4 → GPT4, chatgpt-4 → chatgpt4)
        # This prevents TTS from reading "-" as "横杠" or "dash"
        text = re.sub(r'([a-zA-Z0-9]+)-([a-zA-Z0-9]+)', r'\1\2', text)

        # 2. Remove spaces between Chinese characters (prevents splitting proper nouns)
        # Example: "哈利 波特" → "哈利波特"
        text = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', text)

        # 3. Remove spaces between Chinese and English/numbers (prevents pauses)
        # Example: "中文 AI" → "中文AI", "AI 模型" → "AI模型"
        text = re.sub(r'([\u4e00-\u9fff])\s+([a-zA-Z0-9])', r'\1\2', text)
        text = re.sub(r'([a-zA-Z0-9])\s+([\u4e00-\u9fff])', r'\1\2', text)

        # 4. Remove excessive spaces between English words (keep single space)
        text = re.sub(r'([a-zA-Z])\s{2,}([a-zA-Z])', r'\1 \2', text)

        # 5. Remove spaces around Chinese punctuation
        text = re.sub(r'\s*([，。！？、；：""''（）【】])\s*', r'\1', text)

        # 6. Remove dashes and ellipsis that cause pauses
        text = re.sub(r'\s*[-—–]+\s*', '', text)  # Dashes
        text = re.sub(r'\.{2,}', '', text)  # Ellipsis

        # 7. Normalize whitespace and newlines
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    @staticmethod
    def calculate_silence_duration(prev_turn: Dict, curr_turn: Dict) -> float:
        """
        Calculate dynamic silence duration based on dialogue context.

        Args:
            prev_turn: Previous dialogue turn with speaker and text
            curr_turn: Current dialogue turn with speaker and text

        Returns:
            Silence duration in seconds
        """
        prev_text = prev_turn.get("text", "")
        curr_text = curr_turn.get("text", "")
        prev_speaker = prev_turn.get("speaker", "")
        curr_speaker = curr_turn.get("speaker", "")

        # Base silence duration
        base_silence = 0.3

        # Same speaker continues - reduce pause
        if prev_speaker == curr_speaker:
            base_silence = 0.2

        # Question ending - increase pause (waiting for answer)
        if prev_text.endswith('？') or prev_text.endswith('?'):
            return base_silence + 0.2

        # Long sentence - increase pause (give listener time to digest)
        if len(prev_text) > 50:
            return base_silence + 0.15

        # Exclamation ending - increase pause (emphasize emotion)
        if prev_text.endswith('！') or prev_text.endswith('!'):
            return base_silence + 0.1

        # Connecting words at start - reduce pause (maintain flow)
        if curr_text.startswith(('那么', '所以', '因此', '然后', '而且', '不过', '但是')):
            return max(0.15, base_silence - 0.1)

        # Interjections at start - reduce pause (quick response)
        if curr_text.startswith(('嗯', '哦', '啊', '诶', '对', '是', '好')):
            return max(0.15, base_silence - 0.15)

        return base_silence

    def __init__(self):
        self.storage_path = Path(settings.AUDIO_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.preview_path = self.storage_path / "previews"
        self.preview_path.mkdir(parents=True, exist_ok=True)

    def get_preview_path(self, voice_id: str) -> Path:
        """Get path to cached preview file for a voice"""
        safe_name = voice_id.replace("-", "_")
        return self.preview_path / f"{safe_name}.mp3"

    def has_cached_preview(self, voice_id: str) -> bool:
        """Check if preview is already cached"""
        return self.get_preview_path(voice_id).exists()

    async def generate_all_previews(self):
        """Pre-generate preview audio for all voices (called at startup)"""
        logger.info("Generating voice previews...")

        preview_texts = {
            "female": "大家好，欢迎收听今天的AI资讯播客。",
            "male": "没错，今天我们来聊聊最新的科技动态。"
        }

        for gender, voices in self.VOICE_OPTIONS.items():
            text = preview_texts[gender]
            for voice in voices:
                voice_id = voice["id"]
                preview_file = self.get_preview_path(voice_id)

                if preview_file.exists():
                    logger.debug(f"Preview already exists: {voice_id}")
                    continue

                try:
                    logger.info(f"Generating preview for {voice_id}...")
                    audio_bytes = await self.text_to_speech(text, voice=voice_id, speed=1.0)
                    with open(preview_file, "wb") as f:
                        f.write(audio_bytes)
                    logger.info(f"Preview saved: {voice_id}")
                except Exception as e:
                    logger.error(f"Failed to generate preview for {voice_id}: {e}")

        logger.info("Voice preview generation complete")

    async def text_to_speech(
        self,
        text: str,
        voice: str = "female",
        speed: float = 1.15,
        language: str = "zh",
        max_retries: int = 5
    ) -> bytes:
        """
        Convert text to speech using Edge TTS with retry logic

        Args:
            text: Text to convert
            voice: Voice type, name, or direct voice ID (e.g. zh-CN-XiaoxiaoNeural)
            speed: Speech speed (0.5-2.0), default 1.15 for slightly faster
            language: Language code (zh/en)
            max_retries: Maximum retry attempts

        Returns:
            Audio bytes (MP3 format)
        """
        # Normalize numbers and symbols for proper pronunciation
        text = self.normalize_numbers_for_tts(text)
        # Preprocess text to fix pronunciation issues
        text = self.preprocess_text(text)

        # Get voice ID - support direct voice ID or legacy mapping
        if voice.startswith("zh-") or voice.startswith("en-"):
            # Direct voice ID provided
            voice_id = voice
        else:
            # Legacy mapping
            voice_id = self.VOICES.get(voice)
            if not voice_id:
                if language == "en":
                    voice_id = self.VOICES["en_female"]
                else:
                    voice_id = self.DEFAULT_VOICE_FEMALE

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
                    wait_time = 2 * (attempt + 1)  # Exponential backoff: 2, 4, 6, 8 seconds
                    logger.info(f"TTS waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)

        logger.error(f"TTS failed after {max_retries} attempts - voice: {voice_id}, rate: {rate}, text: {text[:200]}..., error: {last_error}")
        raise Exception(f"语音合成失败，已重试{max_retries}次: {last_error}")

    async def generate_dialogue_audio(
        self,
        dialogue: List[Dict[str, str]],
        output_filename: Optional[str] = None,
        language: str = "zh",
        voice_female: Optional[str] = None,
        voice_male: Optional[str] = None,
        speed: float = 1.15,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, any]:
        """
        Generate audio from dialogue script

        Args:
            dialogue: List of dialogue turns with speaker and text
            output_filename: Optional output filename
            language: Language code (zh/en/bilingual)
            voice_female: Voice ID for female speaker (default: 晓晓)
            voice_male: Voice ID for male speaker (default: 云希)
            speed: Speech speed (0.5-2.0), default 1.15
            progress_callback: Optional callback(progress_percent, stage_message)

        Returns:
            Dict with file_path, duration, file_size, transcript
        """
        if not output_filename:
            output_filename = f"{uuid.uuid4().hex}.mp3"

        # Use provided voices or defaults
        female_voice = voice_female or self.DEFAULT_VOICE_FEMALE
        male_voice = voice_male or self.DEFAULT_VOICE_MALE

        output_path = self.storage_path / output_filename
        audio_segments = []
        transcript = []  # Store dialogue with timestamps

        total_turns = len(dialogue)
        logger.info(f"Generating audio for {total_turns} dialogue turns (female: {female_voice}, male: {male_voice})")

        current_time = 0.0  # Track current position in seconds

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
                    voice = female_voice
                else:
                    voice = male_voice

                audio_bytes = await self.text_to_speech(
                    text,
                    voice=voice,
                    speed=speed,
                    language=language
                )

                # Get segment duration using pydub
                segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
                segment_duration = len(segment) / 1000.0  # Convert ms to seconds

                # Add dynamic silence before (except first segment)
                if i > 0:
                    silence_duration = self.calculate_silence_duration(dialogue[i-1], turn)
                    current_time += silence_duration

                # Record transcript with timing
                transcript.append({
                    "speaker": speaker,
                    "text": text,
                    "start": round(current_time, 2),
                    "end": round(current_time + segment_duration, 2)
                })

                current_time += segment_duration
                audio_segments.append(audio_bytes)
                logger.info(f"Generated segment {i+1}/{total_turns}: {len(audio_bytes)} bytes, {segment_duration:.2f}s")
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

        logger.info(f"Audio saved: {output_filename}, {file_size} bytes, {duration}s, {len(transcript)} segments")

        return {
            "file_path": str(output_filename),
            "file_size": file_size,
            "duration": duration,
            "transcript": transcript
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
