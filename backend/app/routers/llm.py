"""大模型配置路由：CRUD + 动态模型列表 + 测试连接。

安全：明文 api_key 仅入站，响应只含 has_api_key。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMConfig
from app.db.session import get_session
from app.schemas.llm import (
    LLMConfigCreate,
    LLMConfigOut,
    LLMConfigUpdate,
    ModelInfo,
    ModelsListRequest,
    TestConnRequest,
    TestConnResult,
)
from app.services.desktop_guard import validate_model_url
from app.services.llm_factory import CryptoError, LLMCrypto, llm_factory

router = APIRouter(prefix="/api/llm", tags=["llm"])


async def _get_config_or_404(session: AsyncSession, cfg_id: uuid.UUID) -> LLMConfig:
    cfg = await session.get(LLMConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "配置不存在")
    return cfg


def _out(cfg: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=cfg.id,
        name=cfg.name,
        provider=cfg.provider,
        base_url=cfg.base_url,
        model_name=cfg.model_name,
        has_api_key=bool(cfg.encrypted_api_key),
        is_default=cfg.is_default,
        extra_params=cfg.extra_params or {},
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


@router.get("/configs", response_model=list[LLMConfigOut])
async def list_configs(session: AsyncSession = Depends(get_session)):
    rows = (
        (await session.execute(select(LLMConfig).order_by(LLMConfig.created_at.desc())))
        .scalars()
        .all()
    )
    return [_out(c) for c in rows]


@router.post("/configs", response_model=LLMConfigOut, status_code=201)
async def create_config(data: LLMConfigCreate, session: AsyncSession = Depends(get_session)):
    base_url = validate_model_url(data.base_url)
    encrypted = ""
    if data.api_key:
        try:
            encrypted = LLMCrypto.encrypt(data.api_key)
        except CryptoError as e:
            raise HTTPException(500, str(e))
    cfg = LLMConfig(
        name=data.name,
        provider=data.provider,
        base_url=base_url,
        model_name=data.model_name,
        encrypted_api_key=encrypted,
        is_default=data.is_default,
        extra_params=data.extra_params or {},
    )
    if cfg.is_default:
        await session.execute(update(LLMConfig).values(is_default=False))
    session.add(cfg)
    await session.commit()
    await session.refresh(cfg)
    return _out(cfg)


@router.patch("/configs/{cfg_id}", response_model=LLMConfigOut)
async def update_config(
    cfg_id: uuid.UUID, data: LLMConfigUpdate, session: AsyncSession = Depends(get_session)
):
    cfg = await _get_config_or_404(session, cfg_id)
    if data.name is not None:
        cfg.name = data.name
    if data.provider is not None:
        cfg.provider = data.provider
    if data.base_url is not None:
        cfg.base_url = validate_model_url(data.base_url)
    if data.model_name is not None:
        cfg.model_name = data.model_name
    if data.api_key is not None:
        try:
            cfg.encrypted_api_key = LLMCrypto.encrypt(data.api_key) if data.api_key else ""
        except CryptoError as e:
            raise HTTPException(500, str(e))
    if data.is_default is not None:
        if data.is_default:
            await session.execute(update(LLMConfig).values(is_default=False))
        cfg.is_default = data.is_default
    if data.extra_params is not None:
        cfg.extra_params = data.extra_params
    await session.commit()
    await session.refresh(cfg)
    return _out(cfg)


@router.delete("/configs/{cfg_id}", status_code=204)
async def delete_config(cfg_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    cfg = await _get_config_or_404(session, cfg_id)
    await session.delete(cfg)
    await session.commit()


@router.post("/test", response_model=TestConnResult)
async def test_connection(data: TestConnRequest):
    base_url = validate_model_url(data.base_url)
    api_key = data.api_key or None
    ok, msg, err_type = await llm_factory.test_connection(base_url, api_key, data.model_name)
    return TestConnResult(ok=ok, message=msg, error_type=err_type)


@router.post("/models", response_model=list[ModelInfo])
async def list_models(data: ModelsListRequest, session: AsyncSession = Depends(get_session)):
    base_url = validate_model_url(data.base_url)
    api_key = data.api_key or None
    if data.config_id and api_key is None:
        cfg = await session.get(LLMConfig, data.config_id)
        if cfg and cfg.encrypted_api_key:
            try:
                api_key = LLMCrypto.decrypt(cfg.encrypted_api_key)
            except CryptoError:
                api_key = None
    try:
        models = await llm_factory.list_models(base_url, api_key)
        if not models:
            # Ollama 可能不支持 /models
            return [ModelInfo(id="gpt-oss:20b")]
        return [ModelInfo(id=m["id"], owned_by=m.get("owned_by", "")) for m in models]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"拉取模型列表失败：{e}")
