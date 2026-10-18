"""LLM 工厂：OpenAI 兼容客户端动态实例化 + 密钥管理。

安全承诺：
- API Key 以 Fernet 密文存库，明文只在服务端工厂内部解密，绝不回传前端。
- 解密失败显式抛错，不静默降级。
"""

import asyncio
import logging
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


class CryptoError(Exception):
    """密钥加密/解密失败。"""


@lru_cache
def _fernet() -> Fernet:
    key = settings.fernet_key
    if not key or key.startswith("change_me"):
        raise CryptoError("KIWI_FERNET_KEY 未配置或仍为占位值，拒绝加解密。")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise CryptoError(f"KIWI_FERNET_KEY 非法：{e}") from e


class LLMCrypto:
    """Fernet 加解密封装。"""

    @staticmethod
    def encrypt(plain: str) -> str:
        return _fernet().encrypt(plain.encode()).decode()

    @staticmethod
    def decrypt(token: str) -> str:
        if not token:
            return ""
        try:
            return _fernet().decrypt(token.encode()).decode()
        except InvalidToken as e:
            # 显式抛错，绝不静默降级为明文
            raise CryptoError("API Key 解密失败（密钥不匹配或数据损坏）") from e


class LLMFactory:
    """按 base_url + api_key 动态创建 OpenAI 兼容异步客户端。"""

    def __init__(self) -> None:
        self._clients: dict[tuple[str, str], Any] = {}

    def get_client(self, base_url: str, api_key: str | None = None, model: str = ""):
        """实例化 AsyncOpenAI。api_key 缺省用 "ollama"（Ollama 兜底）。"""
        from openai import AsyncOpenAI

        key = api_key or "ollama"
        cache_key = (base_url.rstrip("/"), key)
        if cache_key not in self._clients:
            self._clients[cache_key] = AsyncOpenAI(
                base_url=f"{base_url.rstrip('/')}/v1",
                api_key=key,
                timeout=settings.llm_timeout,
                max_retries=0,
            )
        return self._clients[cache_key]

    async def list_models(self, base_url: str, api_key: str | None = None) -> list[dict]:
        """拉取该服务商的模型列表（GET /v1/models）。"""
        client = self.get_client(base_url, api_key)
        try:
            models = await asyncio.wait_for(client.models.list(), timeout=30)
            return [{"id": m.id, "owned_by": getattr(m, "owned_by", "")} for m in models.data]
        except Exception:
            # Ollama 等可能不支持 /models，尝试从模型配置白名单兜底
            return []

    async def test_connection(
        self, base_url: str, api_key: str | None, model_name: str
    ) -> tuple[bool, str, str | None]:
        """最小调用验证密钥与模型可达性。返回 (ok, message, error_type)。"""
        client = self.get_client(base_url, api_key, model_name)
        try:
            from openai import (
                APIConnectionError,
                APIError,
                AuthenticationError,
                NotFoundError,
                RateLimitError,
            )

            await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=4,
                    stream=False,
                ),
                timeout=45,
            )
            return True, f"连接成功：模型 {model_name} 可达", None
        except AuthenticationError as e:
            return False, f"认证失败：{e}", "invalid_key"
        except RateLimitError as e:
            return False, f"限流：{e}", "rate_limited"
        except NotFoundError:
            return False, f"模型不存在：{model_name}", "not_found"
        except APIConnectionError as e:
            return False, f"连接失败：{e}", "timeout"
        except APIError as e:
            return False, f"API 错误：{e}", "unknown"
        except Exception as e:  # noqa: BLE001
            return False, f"未知错误：{e}", "unknown"


llm_factory = LLMFactory()
