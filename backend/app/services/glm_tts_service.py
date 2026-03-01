"""
GLM-TTS Service - 智谱语音合成服务
"""
import httpx
import logging
from typing import Optional, List, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)


# GLM-TTS 支持的语音列表
GLM_VOICES = {
    "female": [
        {"id": "female-tianmei", "name": "甜美女声", "desc": "温柔甜美"},
        {"id": "female-chengshu", "name": "成熟女声", "desc": "知性成熟"},
        {"id": "female-qingxin", "name": "清新女声", "desc": "清新自然"},
    ],
    "male": [
        {"id": "male-qinqie", "name": "亲切男声", "desc": "温暖亲切"},
        {"id": "male-jingying", "name": "精英男声", "desc": "专业稳重"},
        {"id": "male-qingsong", "name": "轻松男声", "desc": "轻松活泼"},
    ]
}


class GLMTTSService:
    """GLM TTS 语音合成服务"""

    def __init__(self):
        self.api_key = settings.GLM_API_KEY
        self.api_url = settings.GLM_TTS_URL

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    @staticmethod
    def get_voice_options() -> Dict[str, List[Dict[str, str]]]:
        """获取可用的语音选项"""
        return GLM_VOICES

    @staticmethod
    def is_valid_voice(voice_id: str, gender: str = None) -> bool:
        """验证语音ID是否有效"""
        if gender:
            voices = GLM_VOICES.get(gender, [])
            return any(v["id"] == voice_id for v in voices)
        # 检查所有性别
        for voices in GLM_VOICES.values():
            if any(v["id"] == voice_id for v in voices):
                return True
        return False

    async def text_to_speech(
        self,
        text: str,
        voice: str = "female-tianmei",
        speed: float = 1.0
    ) -> bytes:
        """
        将文本转换为语音

        Args:
            text: 要合成的文本
            voice: 语音ID
            speed: 语速 (0.5-2.0)

        Returns:
            音频字节数据 (MP3格式)
        """
        payload = {
            "model": "glm-tts",
            "input": text,
            "voice": voice,
        }

        # GLM-TTS 可能支持 speed 参数
        if speed != 1.0:
            payload["speed"] = speed

        logger.info(f"[GLM-TTS] Generating speech: voice={voice}, text_len={len(text)}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.api_url,
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()

            # GLM-TTS 返回音频二进制数据
            return response.content

    async def generate_preview(self, voice: str) -> bytes:
        """
        生成语音预览

        Args:
            voice: 语音ID

        Returns:
            预览音频字节数据
        """
        # 根据性别选择预览文本
        if voice.startswith("female"):
            preview_text = "大家好，欢迎收听今天的AI资讯播客，我是你们的主播。"
        else:
            preview_text = "没错，今天我们来聊聊最新的科技动态，精彩内容马上开始。"

        return await self.text_to_speech(preview_text, voice)


# 单例
glm_tts_service = GLMTTSService()
