"""代码块运行：仅 Python，在 bubblewrap 安全沙箱中执行。

每次运行都是一次性进程：独立临时工作目录、清理后的环境变量、无网络、
10 秒超时与 CPU / 内存 / 文件大小限制。项目虚拟环境以只读方式挂载为
``/venv``，因此代码块可以直接导入 pandas、numpy、matplotlib 等本项目依赖。

危险操作（``rm -rf``、格式化磁盘、关机等）会在启动沙箱前被静态拦截并
返回 400；沙箱不可用时返回 503，绝不回退到宿主直跑。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    DangerousCodeError,
    SandboxUnavailable,
    run_once,
)

router = APIRouter(prefix="/api/run", tags=["run"])

TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
MAX_CODE_CHARS = 50_000


class RunCodeIn(BaseModel):
    language: Literal["python", "python3"]
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)


class RunCodeOut(BaseModel):
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False
    sandboxed: bool = True


@router.post("/code", response_model=RunCodeOut)
def run_code(payload: RunCodeIn) -> RunCodeOut:
    """在安全沙箱中执行 Python 代码并返回 stdout / stderr。"""
    code = payload.code
    if not code.strip():
        raise HTTPException(400, "代码为空")
    try:
        result = run_once(code, timeout=TIMEOUT_SECONDS)
    except DangerousCodeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except SandboxUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return RunCodeOut(
        ok=result.ok,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        truncated=result.truncated,
        sandboxed=result.sandboxed,
    )
