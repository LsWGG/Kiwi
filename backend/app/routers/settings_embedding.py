"""向量模型设置：读取 / 保存 / 测试 / 恢复环境变量配置。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.embedding_config import EMBEDDING_CONFIG_ID, EmbeddingConfig
from app.db.session import get_session
from app.schemas.embedding import (
    EmbeddingConfigOut,
    EmbeddingConfigUpdate,
    EmbeddingTestRequest,
    EmbeddingTestResult,
)
from app.services import embedding_settings
from app.services.desktop_guard import validate_model_url
from app.services.embedder import configure_runtime, env_runtime_config, test_remote_connection
from app.services.llm_factory import CryptoError, LLMCrypto

router = APIRouter(prefix="/api/settings/embedding", tags=["settings"])


def _out(row: EmbeddingConfig | None) -> EmbeddingConfigOut:
    env = embedding_settings.env_defaults()
    if row is not None:
        return EmbeddingConfigOut(
            provider=embedding_settings.normalize_provider(row.provider),
            api_base=row.api_base,
            api_model=row.api_model,
            api_timeout=row.api_timeout,
            api_batch_size=row.api_batch_size,
            api_concurrency=row.api_concurrency,
            has_api_key=bool(row.encrypted_api_key),
            source="saved",
            active_space=embedding_settings.space_for(row.provider, row.api_model),
            env_provider=env["provider"],
            env_api_base=env["api_base"],
            env_api_model=env["api_model"],
            env_has_api_key=env["has_api_key"],
        )
    return EmbeddingConfigOut(
        provider=env["provider"],
        api_base=env["api_base"],
        api_model=env["api_model"],
        api_timeout=env["api_timeout"],
        api_batch_size=env["api_batch_size"],
        api_concurrency=env["api_concurrency"],
        has_api_key=env["has_api_key"],
        source="env",
        active_space=embedding_settings.active_space(),
        env_provider=env["provider"],
        env_api_base=env["api_base"],
        env_api_model=env["api_model"],
        env_has_api_key=env["has_api_key"],
    )


async def _get_row(session: AsyncSession) -> EmbeddingConfig | None:
    return await session.get(EmbeddingConfig, EMBEDDING_CONFIG_ID)


@router.get("", response_model=EmbeddingConfigOut)
async def get_embedding_config(session: AsyncSession = Depends(get_session)):
    return _out(await _get_row(session))


@router.put("", response_model=EmbeddingConfigOut)
async def save_embedding_config(
    data: EmbeddingConfigUpdate, session: AsyncSession = Depends(get_session)
):
    provider = embedding_settings.normalize_provider(data.provider)
    api_base = data.api_base.strip().rstrip("/")
    api_model = data.api_model.strip()

    if provider == "openai":
        if not api_base.startswith(("http://", "https://")):
            raise HTTPException(400, "线上接口地址必须以 http:// 或 https:// 开头")
        if not api_model:
            raise HTTPException(400, "请填写线上模型名")
        api_base = validate_model_url(api_base)

    row = await _get_row(session)
    is_new = row is None
    if row is None:
        row = EmbeddingConfig(id=EMBEDDING_CONFIG_ID)
        session.add(row)

    try:
        if data.api_key is None:
            # 新建时若环境变量里已有 Key，则一并带入，避免切换配置后丢失。
            if is_new:
                env_key = env_runtime_config().api_key
                row.encrypted_api_key = LLMCrypto.encrypt(env_key) if env_key else ""
        elif data.api_key == "":
            row.encrypted_api_key = ""
        else:
            row.encrypted_api_key = LLMCrypto.encrypt(data.api_key)
    except CryptoError as exc:
        raise HTTPException(500, str(exc)) from exc

    row.provider = provider
    row.api_base = api_base
    row.api_model = api_model
    row.api_timeout = data.api_timeout
    row.api_batch_size = data.api_batch_size
    row.api_concurrency = data.api_concurrency

    await session.commit()
    await session.refresh(row)

    try:
        embedding_settings.apply_row(row)
    except CryptoError as exc:
        raise HTTPException(500, str(exc)) from exc
    return _out(row)


@router.delete("", status_code=204)
async def reset_embedding_config(session: AsyncSession = Depends(get_session)):
    row = await _get_row(session)
    if row is not None:
        await session.delete(row)
        await session.commit()
    configure_runtime(None)


@router.post("/test", response_model=EmbeddingTestResult)
async def test_embedding(
    data: EmbeddingTestRequest, session: AsyncSession = Depends(get_session)
):
    provider = embedding_settings.normalize_provider(data.provider)
    if provider == "none":
        return EmbeddingTestResult(
            ok=True, message="向量模型已关闭，检索与问答将不可用。"
        )
    if provider != "openai":
        return EmbeddingTestResult(
            ok=True, message="本地 fastembed 模型无需在线测试，导入素材时会自动加载。"
        )

    api_base = data.api_base.strip().rstrip("/")
    api_model = data.api_model.strip()
    if not api_base.startswith(("http://", "https://")):
        return EmbeddingTestResult(ok=False, message="请填写以 http:// 或 https:// 开头的接口地址")
    if not api_model:
        return EmbeddingTestResult(ok=False, message="请填写线上模型名")
    try:
        api_base = validate_model_url(api_base)
    except HTTPException as exc:
        return EmbeddingTestResult(ok=False, message=str(exc.detail))

    api_key = data.api_key
    if api_key is None:
        row = await _get_row(session)
        if row is not None and row.encrypted_api_key:
            try:
                api_key = LLMCrypto.decrypt(row.encrypted_api_key)
            except CryptoError as exc:
                return EmbeddingTestResult(ok=False, message=str(exc))
        else:
            api_key = env_runtime_config().api_key

    try:
        dimensions, latency_ms = await test_remote_connection(
            api_base, api_key or "", api_model, data.api_timeout
        )
    except Exception as exc:  # noqa: BLE001 — 连接测试需要把错误原文回显给用户
        return EmbeddingTestResult(ok=False, message=str(exc))

    return EmbeddingTestResult(
        ok=True,
        message=f"连接成功，向量维度 {dimensions}",
        dimensions=dimensions,
        latency_ms=latency_ms,
    )
