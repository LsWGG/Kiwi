"""微信 ClawBot（官方 iLink 协议）渠道。

能力：
- 前端扫码登录，bot_token 加密保存到运行时 JSON（不写数据库）；
- 长轮询接收微信消息，路由到 Kiwi 问答 Agent，回复文本；
- 写操作通过「确认 / 取消」二次确认后继续；
- 定时任务（如每天 9 点待办）主动推送；context_token 过期时排队到下次互动补发；
- 24 小时登录有效期提醒与重新扫码。

协议参考腾讯官方 iLink：get_bot_qrcode / get_qrcode_status / getupdates /
sendmessage / getconfig / sendtyping。只处理文本消息。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.config import settings
from app.db.models import KnowledgeBase
from app.db.session import async_session_factory
from app.services.channel_context import (
    current_wechat_kb_id,
    current_wechat_sender,
)
from app.services.llm_factory import CryptoError, LLMCrypto

logger = logging.getLogger("kiwi.wechat")

ILINK_BASE = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "1.0.2"
LOGIN_TIMEOUT_SECONDS = 600
CONFIRM_TTL_SECONDS = 15 * 60
MAX_HISTORY_MESSAGES = 12
MAX_TEXT_CHARS = 1800
DEDUPE_LIMIT = 200

HELP_TEXT = """ClawBot 指令：
/help  查看指令
/kb  列出知识库；/kb 名称 切换当前知识库
/status  查看连接、当前知识库与定时任务
/time  查看连接剩余时间
/reset  清空当前对话上下文

直接发送问题即可问答；写操作会先询问「确认 / 取消」。"""


def _now() -> float:
    return time.time()


def _today() -> str:
    return datetime.now(_tz()).strftime("%Y-%m-%d")


def _tz() -> ZoneInfo:
    name = (settings.timezone or "").strip()
    try:
        return ZoneInfo(name) if name else ZoneInfo("Asia/Shanghai")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Shanghai")


def _default_store() -> dict[str, Any]:
    return {
        "enabled": False,
        "bot_token": "",
        "bot_base_url": "",
        "login_at": 0,
        "allowed_users": [],
        "unknown_users": {},
        "default_kb_id": "",
        "allow_write": False,
        "contacts": {},
        "sender_kb": {},
        "history": {},
        "pending": {},
        "queued": {},
        "schedules": [],
        "get_updates_buf": "",
        "typing": {},
        "warning_sent_at": 0,
    }


class WeChatStore:
    """运行时状态 JSON；bot_token 加密，文件 0600，原子写入。"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] | None = None

    async def read(self) -> dict[str, Any]:
        async with self._lock:
            if self._data is None:
                self._data = self._load()
            return self._data

    async def write(self, data: dict[str, Any]) -> None:
        async with self._lock:
            self._data = data
            self._persist(data)

    async def update(self, mutator) -> dict[str, Any]:
        async with self._lock:
            if self._data is None:
                self._data = self._load()
            mutator(self._data)
            self._persist(self._data)
            return self._data

    def _load(self) -> dict[str, Any]:
        data = _default_store()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in data and isinstance(value, type(data[key])):
                        data[key] = value
                    elif key in data:
                        data[key] = value
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("微信渠道状态文件读取失败：%s", self.path, exc_info=True)
        return data

    def _persist(self, data: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.chmod(0o600)
            tmp.replace(self.path)
        except OSError:
            logger.exception("微信渠道状态文件写入失败：%s", self.path)


def _encrypt_token(token: str) -> str:
    return f"enc:{LLMCrypto.encrypt(token)}" if token else ""


def _decrypt_token(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("enc:"):
        return value
    try:
        return LLMCrypto.decrypt(value[4:])
    except CryptoError:
        logger.warning("微信 bot_token 解密失败，请重新扫码登录")
        return ""
    except Exception:  # noqa: BLE001
        return ""


def _uin_header() -> str:
    value = str(random.randint(0, 0xFFFFFFFF))
    return base64.b64encode(value.encode()).decode()


def _headers(token: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _uin_header(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _split_text(text: str, limit: int = MAX_TEXT_CHARS) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [part for part in parts if part]


@dataclass
class ChatResult:
    answer: str = ""
    approval: dict[str, Any] | None = None
    awaiting: bool = False
    error: str = ""
    ok: bool = True


class WeChatChannel:
    def __init__(self) -> None:
        self.store = WeChatStore(Path(settings.wechat_store_file))
        self._http: httpx.AsyncClient | None = None
        self._token = ""
        self._base_url = ILINK_BASE
        self._worker_task: asyncio.Task | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._expiry_task: asyncio.Task | None = None
        self._login_task: asyncio.Task | None = None
        self._login_state: dict[str, Any] = {"status": "disconnected"}
        self._login_qrcode = ""
        self._tasks: set[asyncio.Task] = set()
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._seen: list[str] = []
        self._started = False

    # ------------------------------------------------------------ lifecycle

    async def load(self) -> None:
        if not settings.wechat_enabled:
            return
        data = await self.store.read()
        token = _decrypt_token(str(data.get("bot_token") or ""))
        self._token = token
        self._base_url = str(data.get("bot_base_url") or ILINK_BASE)
        if data.get("enabled") and token:
            await self._start_tasks()
        else:
            self._login_state = {"status": "disconnected"}

    async def start(self) -> None:
        if not settings.wechat_enabled:
            return
        await self.load()

    async def stop(self) -> None:
        self._started = False
        for task in (
            self._worker_task,
            self._scheduler_task,
            self._expiry_task,
            self._login_task,
        ):
            if task is not None:
                task.cancel()
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _start_tasks(self) -> None:
        if self._token and self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker_loop(), name="kiwi-wechat-worker"
            )
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(
                self._scheduler_loop(), name="kiwi-wechat-scheduler"
            )
        if self._expiry_task is None:
            self._expiry_task = asyncio.create_task(
                self._expiry_loop(), name="kiwi-wechat-expiry"
            )
        self._started = True

    async def _ensure_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.wechat_request_timeout),
            )
        return self._http

    # ------------------------------------------------------------ iLink API

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure_http()
        url = f"{(base_url or self._base_url or ILINK_BASE).rstrip('/')}/{path}"
        headers = _headers(self._token if auth else "")
        response = await client.request(
            method, url, json=json_body, params=params, headers=headers
        )
        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            data = {"raw": response.text[:500]}
        if isinstance(data, dict):
            ret = data.get("ret", data.get("errcode"))
            if ret not in (None, 0, "0"):
                logger.warning("微信 iLink 返回异常（%s）：%s", path, str(data)[:300])
        return data if isinstance(data, dict) else {}

    async def _get_qrcode(self) -> dict[str, Any]:
        return await self._request(
            "GET",
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": 3},
            auth=False,
            base_url=self._base_url or ILINK_BASE,
        )

    async def _get_qrcode_status(self, qrcode: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            "ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            auth=False,
            base_url=self._base_url or ILINK_BASE,
        )

    async def _get_updates(self, buf: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "ilink/bot/getupdates",
            json_body={
                "get_updates_buf": buf,
                "base_info": {"channel_version": CHANNEL_VERSION},
            },
        )

    async def _send_message(
        self, sender: str, context_token: str, text: str
    ) -> bool:
        if not text.strip() or not sender or not context_token:
            return False
        ok = True
        for index, part in enumerate(_split_text(text)):
            payload = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": sender,
                    "client_id": f"openclaw-weixin-{uuid.uuid4().hex[:8]}",
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": part}}],
                },
                "base_info": {"channel_version": CHANNEL_VERSION},
            }
            data = await self._request(
                "POST", "ilink/bot/sendmessage", json_body=payload
            )
            ret = data.get("ret", data.get("errcode"))
            if ret not in (None, 0, "0"):
                ok = False
                logger.warning("微信消息发送被拒绝（第 %s 段）：%s", index + 1, data)
        return ok

    async def _typing_ticket(self, sender: str, context_token: str) -> str:
        data = await self.store.read()
        cached = (data.get("typing") or {}).get(sender) or {}
        if cached.get("ticket") and _now() - float(cached.get("at") or 0) < 23 * 3600:
            return str(cached["ticket"])
        cfg = await self._request(
            "POST",
            "ilink/bot/getconfig",
            json_body={
                "ilink_user_id": sender,
                "context_token": context_token,
                "base_info": {"channel_version": CHANNEL_VERSION},
            },
        )
        ticket = str(cfg.get("typing_ticket") or "")
        if ticket:
            def save(state):
                state.setdefault("typing", {})[sender] = {
                    "ticket": ticket,
                    "at": _now(),
                }

            await self.store.update(save)
        return ticket

    async def _send_typing(self, sender: str, context_token: str, status: int) -> None:
        try:
            ticket = await self._typing_ticket(sender, context_token)
            if not ticket:
                return
            await self._request(
                "POST",
                "ilink/bot/sendtyping",
                json_body={
                    "ilink_user_id": sender,
                    "typing_ticket": ticket,
                    "status": status,
                },
            )
        except Exception:  # noqa: BLE001 —— 输入状态失败不影响问答
            logger.debug("微信 typing 状态发送失败", exc_info=True)

    # ------------------------------------------------------------ login

    async def start_login(self) -> dict[str, Any]:
        if not settings.wechat_enabled:
            return {
                "status": "disabled",
                "message": "服务端未启用 ClawBot 渠道（KIWI_WECHAT_ENABLED=false）",
            }
        if self._login_task is not None and not self._login_task.done():
            return self.status()
        data = await self._get_qrcode()
        qrcode = str(data.get("qrcode") or "")
        if not qrcode:
            self._login_state = {
                "status": "error",
                "message": "获取登录二维码失败，请稍后重试",
            }
            return self.status()
        qr = str(data.get("qrcode_img_content") or qrcode)
        self._login_qrcode = qrcode
        self._login_state = {
            "status": "pending",
            "qrcode": qrcode,
            "qr": qr,
            "started_at": _now(),
            "message": "请用手机扫码并确认",
        }
        self._login_task = asyncio.create_task(
            self._poll_login(qrcode), name="kiwi-wechat-login"
        )
        return self.status()

    async def _poll_login(self, qrcode: str) -> None:
        deadline = _now() + LOGIN_TIMEOUT_SECONDS
        while _now() < deadline:
            try:
                data = await self._get_qrcode_status(qrcode)
            except Exception:  # noqa: BLE001 —— 网络抖动继续轮询
                await asyncio.sleep(1.5)
                continue
            status = str(data.get("status") or "")
            if status == "confirmed":
                token = str(data.get("bot_token") or "")
                base_url = str(data.get("baseurl") or ILINK_BASE)
                if not token:
                    break
                self._token = token
                self._base_url = base_url
                self._login_state = {
                    "status": "connected",
                    "message": "ClawBot 连接成功",
                    "at": _now(),
                }
                self._login_qrcode = ""

                def save(state):
                    state["bot_token"] = _encrypt_token(token)
                    state["bot_base_url"] = base_url
                    state["login_at"] = _now()
                    state["enabled"] = True
                    state["warning_sent_at"] = 0
                    state["typing"] = {}

                try:
                    await self.store.update(save)
                except Exception:  # noqa: BLE001
                    logger.exception("微信登录状态保存失败")
                    self._login_state = {
                        "status": "error",
                        "message": "登录状态保存失败，请检查 KIWI_FERNET_KEY",
                    }
                    return
                await self._restart_worker()
                await self._start_tasks()
                logger.info("微信 ClawBot 登录成功")
                return
            if status in ("expired", "cancelled", "canceled"):
                break
            await asyncio.sleep(1.2)
        self._login_state = {
            "status": "expired",
            "message": "二维码已过期，请重新获取",
        }
        self._login_qrcode = ""

    async def _restart_worker(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None
        if self._token:
            self._worker_task = asyncio.create_task(
                self._worker_loop(), name="kiwi-wechat-worker"
            )

    async def logout(self) -> None:
        self._token = ""
        self._base_url = ILINK_BASE
        self._login_state = {"status": "disconnected"}

        def save(state):
            state["bot_token"] = ""
            state["bot_base_url"] = ""
            state["login_at"] = 0
            state["enabled"] = False
            state["get_updates_buf"] = ""

        await self.store.update(save)
        if self._login_task is not None:
            self._login_task.cancel()
            self._login_task = None
        for task in (self._worker_task, self._scheduler_task, self._expiry_task):
            if task is not None:
                task.cancel()
        self._worker_task = self._scheduler_task = self._expiry_task = None

    # ------------------------------------------------------------ worker

    async def _worker_loop(self) -> None:
        failures = 0
        while True:
            if not self._token:
                await asyncio.sleep(5)
                continue
            try:
                data = await self.store.read()
                buf = str(data.get("get_updates_buf") or "")
                result = await self._get_updates(buf)
                new_buf = str(result.get("get_updates_buf") or "")
                if new_buf and new_buf != buf:
                    def save(state):
                        state["get_updates_buf"] = new_buf

                    await self.store.update(save)
                for msg in result.get("msgs") or []:
                    if isinstance(msg, dict):
                        self._dispatch_message(msg)
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                failures += 1
                logger.warning("微信 getupdates 失败（第 %s 次）", failures, exc_info=True)
                await asyncio.sleep(min(30, 2 * failures))

    def _dispatch_message(self, msg: dict[str, Any]) -> None:
        sender = str(msg.get("from_user_id") or "")
        if not sender or sender.endswith("@im.bot"):
            return
        if msg.get("message_type") != 1:
            return
        text = _message_text(msg)
        if not text:
            return
        key = str(msg.get("msg_id") or msg.get("message_id") or "")
        if key:
            if key in self._seen:
                return
            self._seen.append(key)
            if len(self._seen) > DEDUPE_LIMIT:
                del self._seen[: len(self._seen) - DEDUPE_LIMIT]
        task = asyncio.create_task(
            self._handle_message(msg, sender, text), name="kiwi-wechat-message"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_message(
        self, msg: dict[str, Any], sender: str, text: str
    ) -> None:
        context_token = str(msg.get("context_token") or "")
        lock = self._user_locks.setdefault(sender, asyncio.Lock())
        async with lock:
            try:
                await self._handle_message_locked(sender, text, context_token)
            except Exception:  # noqa: BLE001
                logger.exception("微信消息处理失败：%s", sender)
                await self.send_reply(sender, context_token, "处理消息时出现异常，请稍后重试。")

    async def _handle_message_locked(
        self, sender: str, text: str, context_token: str
    ) -> None:
        data = await self.store.read()
        allowed = sender in (data.get("allowed_users") or [])

        def touch(state):
            state.setdefault("contacts", {})[sender] = {
                "context_token": context_token,
                "at": _now(),
            }
            if not allowed:
                state.setdefault("unknown_users", {})[sender] = _now()

        await self.store.update(touch)

        if not allowed:
            await self.send_reply(
                sender,
                context_token,
                f"未授权。请让管理员在 Kiwi「设置 → ClawBot」中添加：\n{sender}",
            )
            return

        data = await self.store.read()
        pending = (data.get("pending") or {}).get(sender) or {}
        normalized = text.strip().lower()
        if pending:
            if normalized in ("确认", "确认执行", "执行", "y", "yes", "好", "可以"):
                await self._resolve_pending(sender, context_token, True)
                return
            if normalized in ("取消", "放弃", "n", "no", "不要"):
                await self._resolve_pending(sender, context_token, False)
                return
            await self.send_reply(
                sender,
                context_token,
                "还有待确认的操作：请回复「确认」执行或「取消」放弃。",
            )
            return

        if text.startswith("/"):
            await self._handle_command(sender, context_token, text)
            return

        await self._flush_queue(sender, context_token)
        await self._answer(sender, text, context_token)

    async def _handle_command(
        self, sender: str, context_token: str, text: str
    ) -> None:
        command, _, arg = text.partition(" ")
        command = command.strip().lower()
        arg = arg.strip()
        if command == "/help":
            await self.send_reply(sender, context_token, HELP_TEXT)
            return
        if command == "/time":
            data = await self.store.read()
            login_at = float(data.get("login_at") or 0)
            remaining = max(0, login_at + settings.wechat_session_hours * 3600 - _now())
            await self.send_reply(
                sender,
                context_token,
                f"当前连接剩余约 {remaining / 3600:.1f} 小时。",
            )
            return
        if command == "/kb":
            await self._command_kb(sender, context_token, arg)
            return
        if command == "/reset":
            def clear(state):
                state.setdefault("history", {})[sender] = []

            await self.store.update(clear)
            await self.send_reply(sender, context_token, "已清空当前对话上下文。")
            return
        if command == "/status":
            await self._command_status(sender, context_token)
            return
        await self.send_reply(sender, context_token, HELP_TEXT)

    async def _command_kb(
        self, sender: str, context_token: str, name: str
    ) -> None:
        async with async_session_factory() as session:
            kbs = (
                (
                    await session.execute(
                        select(KnowledgeBase).where(
                            KnowledgeBase.deleted_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not name:
            lines = ["当前知识库："] + [
                f"- {kb.name}（{str(kb.id)[:8]}）" for kb in kbs[:20]
            ]
            lines.append("发送 /kb 名称 切换。")
            await self.send_reply(sender, context_token, "\n".join(lines))
            return
        lowered = name.lower()
        target = next(
            (kb for kb in kbs if kb.name.lower() == lowered), None
        ) or next((kb for kb in kbs if lowered in kb.name.lower()), None)
        if target is None:
            await self.send_reply(sender, context_token, f"没有找到知识库「{name}」。")
            return

        def save(state):
            state.setdefault("sender_kb", {})[sender] = str(target.id)

        await self.store.update(save)
        await self.send_reply(sender, context_token, f"已切换到知识库「{target.name}」。")

    async def _command_status(
        self, sender: str, context_token: str
    ) -> None:
        data = await self.store.read()
        kb_id = self._kb_for(sender, data)
        kb_name = kb_id[:8]
        if kb_id:
            async with async_session_factory() as session:
                kb = await session.get(KnowledgeBase, uuid.UUID(kb_id))
                if kb is not None:
                    kb_name = kb.name
        schedules = [
            item
            for item in data.get("schedules") or []
            if item.get("sender") == sender
        ]
        login_at = float(data.get("login_at") or 0)
        remaining = max(0, login_at + settings.wechat_session_hours * 3600 - _now())
        lines = [
            f"知识库：{kb_name}",
            f"连接剩余：{remaining / 3600:.1f} 小时",
            f"定时推送：{len(schedules)} 个",
        ]
        for item in schedules[:10]:
            lines.append(
                f"- 每天 {item.get('time')}：{str(item.get('prompt'))[:40]}"
                + ("" if item.get("enabled", True) else "（已暂停）")
            )
        await self.send_reply(sender, context_token, "\n".join(lines))

    # ------------------------------------------------------------ Q&A

    def _kb_for(self, sender: str, data: dict[str, Any]) -> str:
        return str(
            (data.get("sender_kb") or {}).get(sender)
            or data.get("default_kb_id")
            or ""
        )

    async def _answer(self, sender: str, text: str, context_token: str) -> None:
        data = await self.store.read()
        kb_id = self._kb_for(sender, data)
        if not kb_id:
            await self.send_reply(
                sender,
                context_token,
                "还没有设置默认知识库，请在 Kiwi「设置 → ClawBot」中选择。",
            )
            return
        history = list((data.get("history") or {}).get(sender) or [])
        history.append({"role": "user", "content": text})
        messages = history[-MAX_HISTORY_MESSAGES:]
        await self._send_typing(sender, context_token, 1)
        try:
            result = await self._run_chat(messages, uuid.UUID(kb_id), sender)
        finally:
            await self._send_typing(sender, context_token, 2)

        if result.approval:
            await self._store_pending(sender, result.approval)
            await self.send_reply(
                sender, context_token, self._approval_text(result.approval)
            )
            return
        if result.error:
            await self.send_reply(sender, context_token, result.error)
            return
        answer = result.answer or "这次没有生成有效回答，请换个问法。"
        await self.send_reply(sender, context_token, answer)
        await self._append_history(sender, text, answer)

    async def _run_chat(
        self,
        messages: list[dict[str, Any]],
        kb_id: uuid.UUID,
        sender: str,
        *,
        resume_action_id: str | None = None,
        approve: bool | None = None,
        allow_write: bool | None = None,
    ) -> ChatResult:
        # 延迟导入，避免 routers.chat ↔ services 的循环依赖。
        from app.routers import chat as chat_router
        from app.schemas.chat import ChatRequest, SearchScope

        data = await self.store.read()
        write_allowed = (
            bool(data.get("allow_write")) if allow_write is None else allow_write
        )
        request = ChatRequest(
            messages=messages,
            scope=SearchScope(scope="kb", kb_ids=[kb_id]),
            intent="auto",
            agent=True,
            web_search=False,
            resume_action_id=resume_action_id,
            approve=approve,
            allow_write=write_allowed,
        )
        sender_token = current_wechat_sender.set(sender)
        kb_token = current_wechat_kb_id.set(str(kb_id))
        result = ChatResult()
        chunks: list[str] = []
        try:
            async with async_session_factory() as session:
                response = await chat_router.chat_stream(request, session=session)
                async for event, payload in _iter_sse(response):
                    if event == "chunk":
                        chunks.append(str(payload.get("text") or ""))
                    elif event == "approval":
                        result.approval = payload
                    elif event == "error":
                        result.error = str(payload.get("message") or "处理失败")
                        result.ok = False
                    elif event == "done":
                        result.awaiting = bool(payload.get("awaiting_approval"))
                        if payload.get("ok") is False and not result.error:
                            result.error = "本轮处理未完成，请重试。"
                        result.ok = payload.get("ok") is not False
        except Exception as exc:  # noqa: BLE001
            logger.exception("微信问答失败")
            result.error = f"问答服务暂时不可用：{exc}"
            result.ok = False
        finally:
            current_wechat_sender.reset(sender_token)
            current_wechat_kb_id.reset(kb_token)
        result.answer = "".join(chunks).strip()
        return result

    async def _append_history(
        self, sender: str, user_text: str, answer: str
    ) -> None:
        def save(state):
            history = state.setdefault("history", {}).get(sender) or []
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": answer})
            state["history"][sender] = history[-MAX_HISTORY_MESSAGES:]

        await self.store.update(save)

    def _approval_text(self, approval: dict[str, Any]) -> str:
        label = str(approval.get("label") or "操作")
        summary = str(approval.get("summary") or label)
        return (
            f"需要确认：{summary}\n"
            "回复「确认」执行，回复「取消」放弃（15 分钟内有效）。"
        )

    async def _store_pending(
        self, sender: str, approval: dict[str, Any]
    ) -> None:
        def save(state):
            state.setdefault("pending", {})[sender] = {
                "action_id": str(approval.get("action_id") or ""),
                "summary": str(approval.get("summary") or ""),
                "label": str(approval.get("label") or ""),
                "at": _now(),
            }

        await self.store.update(save)

    async def _resolve_pending(
        self, sender: str, context_token: str, approve: bool
    ) -> None:
        data = await self.store.read()
        pending = (data.get("pending") or {}).get(sender) or {}
        action_id = str(pending.get("action_id") or "")
        if not action_id:
            await self.send_reply(sender, context_token, "没有待确认的操作。")
            return
        if _now() - float(pending.get("at") or 0) > CONFIRM_TTL_SECONDS:
            def clear(state):
                state.setdefault("pending", {}).pop(sender, None)

            await self.store.update(clear)
            await self.send_reply(sender, context_token, "操作已过期，请重新提问。")
            return
        kb_id = self._kb_for(sender, data)
        if not kb_id:
            await self.send_reply(sender, context_token, "当前没有绑定知识库。")
            return
        await self._send_typing(sender, context_token, 1)
        try:
            result = await self._run_chat(
                [{"role": "user", "content": "确认执行" if approve else "取消执行"}],
                uuid.UUID(kb_id),
                sender,
                resume_action_id=action_id,
                approve=approve,
            )
        finally:
            await self._send_typing(sender, context_token, 2)

        def clear(state):
            state.setdefault("pending", {}).pop(sender, None)

        await self.store.update(clear)
        if result.error:
            await self.send_reply(sender, context_token, result.error)
            return
        answer = result.answer or ("已执行。" if approve else "已取消。")
        await self.send_reply(sender, context_token, answer)
        await self._append_history(
            sender, "确认执行" if approve else "取消执行", answer
        )

    # ------------------------------------------------------------ sending

    async def send_reply(
        self, sender: str, context_token: str, text: str
    ) -> bool:
        try:
            return await self._send_message(sender, context_token, text)
        except Exception:  # noqa: BLE001
            logger.warning("微信回复发送失败", exc_info=True)
            return False

    async def send_proactive(self, sender: str, text: str) -> bool:
        """主动推送；窗口过期时排队，等下次互动补发。"""
        data = await self.store.read()
        contact = (data.get("contacts") or {}).get(sender) or {}
        token = str(contact.get("context_token") or "")
        at = float(contact.get("at") or 0)
        if token and _now() - at <= settings.wechat_push_window_hours * 3600:
            try:
                if await self._send_message(sender, token, text):
                    return True
                logger.warning("微信主动推送被拒绝，转为排队")
            except Exception:  # noqa: BLE001
                logger.warning("微信主动推送失败，转为排队", exc_info=True)

        def queue(state):
            state.setdefault("queued", {}).setdefault(sender, []).append(
                {"text": text, "at": _now()}
            )

        await self.store.update(queue)
        return False

    async def _flush_queue(self, sender: str, context_token: str) -> None:
        data = await self.store.read()
        queued = list((data.get("queued") or {}).get(sender) or [])
        if not queued:
            return

        remaining: list[dict[str, Any]] = []
        for item in queued:
            text = str(item.get("text") or "")
            if text and not await self.send_reply(
                sender, context_token, f"[补发]\n{text}"
            ):
                remaining.append(item)

        def clear(state):
            if remaining:
                state.setdefault("queued", {})[sender] = remaining
            else:
                state.setdefault("queued", {}).pop(sender, None)

        await self.store.update(clear)

    # ------------------------------------------------------------ schedules

    async def schedule_push(
        self,
        sender: str,
        kb_id: str,
        prompt: str,
        at_time: str,
        days: str = "daily",
    ) -> dict[str, Any]:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at_time or ""):
            raise ValueError("时间格式应为 HH:MM，例如 09:00")
        item = {
            "id": uuid.uuid4().hex[:12],
            "sender": sender,
            "kb_id": str(kb_id),
            "prompt": prompt.strip()[:2000],
            "time": at_time,
            "days": days or "daily",
            "enabled": True,
            "last_run": "",
            "created_at": _now(),
        }

        def save(state):
            state.setdefault("schedules", []).append(item)

        await self.store.update(save)
        return item

    async def list_schedules(self) -> list[dict[str, Any]]:
        data = await self.store.read()
        return list(data.get("schedules") or [])

    async def delete_schedule(self, schedule_id: str) -> bool:
        removed = False

        def save(state):
            nonlocal removed
            schedules = state.setdefault("schedules", [])
            kept = [item for item in schedules if item.get("id") != schedule_id]
            removed = len(kept) != len(schedules)
            state["schedules"] = kept

        await self.store.update(save)
        return removed

    async def toggle_schedule(self, schedule_id: str, enabled: bool) -> bool:
        found = False

        def save(state):
            nonlocal found
            for item in state.setdefault("schedules", []):
                if item.get("id") == schedule_id:
                    item["enabled"] = bool(enabled)
                    found = True

        await self.store.update(save)
        return found

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(20)
                if not settings.wechat_enabled:
                    continue
                data = await self.store.read()
                if not data.get("enabled"):
                    continue
                now = datetime.now(_tz())
                current = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")
                due: list[dict[str, Any]] = []

                def mark(state):
                    for item in state.setdefault("schedules", []):
                        if not item.get("enabled", True):
                            continue
                        if item.get("time") != current:
                            continue
                        if item.get("last_run") == today:
                            continue
                        item["last_run"] = today
                        due.append(dict(item))

                await self.store.update(mark)
                for item in due:
                    task = asyncio.create_task(
                        self._run_schedule(item), name="kiwi-wechat-push"
                    )
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("微信定时任务检查失败")

    async def _run_schedule(self, item: dict[str, Any]) -> None:
        sender = str(item.get("sender") or "")
        kb_id = str(item.get("kb_id") or "")
        prompt = str(item.get("prompt") or "").strip()
        if not sender or not kb_id or not prompt:
            return
        try:
            result = await self._run_chat(
                [{"role": "user", "content": prompt}],
                uuid.UUID(kb_id),
                sender,
            )
            if result.approval:
                await self._store_pending(sender, result.approval)
                await self.send_proactive(
                    sender, self._approval_text(result.approval)
                )
                return
            text = result.answer or result.error or "定时任务没有生成内容。"
            await self.send_proactive(sender, f"[定时推送]\n{text}")
        except Exception:  # noqa: BLE001
            logger.exception("微信定时任务执行失败：%s", item.get("id"))

    # ------------------------------------------------------------ expiry

    async def _expiry_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(300)
                if not settings.wechat_enabled or not self._token:
                    continue
                data = await self.store.read()
                login_at = float(data.get("login_at") or 0)
                if not login_at:
                    continue
                remaining = login_at + settings.wechat_session_hours * 3600 - _now()
                if remaining > 3600:
                    continue
                last_warn = float(data.get("warning_sent_at") or 0)
                if _now() - last_warn < 1800:
                    continue

                def save(state):
                    state["warning_sent_at"] = _now()

                await self.store.update(save)
                login = await self.start_login()
                qr = str((login.get("login") or {}).get("qr") or "")
                allowed = set(data.get("allowed_users") or [])
                recent = [
                    (sender, contact)
                    for sender, contact in (data.get("contacts") or {}).items()
                    if sender in allowed
                ]
                if qr and recent:
                    sender, _contact = max(
                        recent, key=lambda item: item[1].get("at", 0)
                    )
                    await self.send_proactive(
                        sender,
                        "ClawBot 连接即将到期，请在 Kiwi「设置 → ClawBot」重新扫码。"
                        f"\n{qr}",
                    )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("微信连接续期检查失败")

    # ------------------------------------------------------------ admin/status

    def status(self) -> dict[str, Any]:
        # 同步视图只暴露非敏感字段；调用方需要先 await store.read() 填充。
        return {
            "system_enabled": settings.wechat_enabled,
            "login": dict(self._login_state),
        }

    async def full_status(self) -> dict[str, Any]:
        data = await self.store.read()
        login_at = float(data.get("login_at") or 0)
        contact = data.get("contacts") or {}
        last_sender, last = (
            max(contact.items(), key=lambda item: item[1].get("at", 0))
            if contact
            else ("", {})
        )
        return {
            "system_enabled": settings.wechat_enabled,
            "enabled": bool(data.get("enabled")),
            "connected": bool(self._token),
            "login_at": login_at,
            "remaining_seconds": max(
                0,
                login_at + settings.wechat_session_hours * 3600 - _now(),
            )
            if login_at
            else 0,
            "login": dict(self._login_state),
            "default_kb_id": str(data.get("default_kb_id") or ""),
            "allow_write": bool(data.get("allow_write")),
            "allowed_users": list(data.get("allowed_users") or []),
            "unknown_users": [
                {"sender": sender, "at": at}
                for sender, at in (data.get("unknown_users") or {}).items()
            ],
            "schedules": list(data.get("schedules") or []),
            "last_contact": {
                "sender": last_sender,
                "at": last.get("at", 0),
            }
            if last
            else None,
        }

    async def update_settings(
        self,
        *,
        enabled: bool | None = None,
        default_kb_id: str | None = None,
        allow_write: bool | None = None,
        allowed_users: list[str] | None = None,
    ) -> dict[str, Any]:
        def save(state):
            if enabled is not None:
                state["enabled"] = bool(enabled)
            if default_kb_id is not None:
                state["default_kb_id"] = default_kb_id
            if allow_write is not None:
                state["allow_write"] = bool(allow_write)
            if allowed_users is not None:
                users = [item.strip() for item in allowed_users if item.strip()]
                state["allowed_users"] = list(dict.fromkeys(users))
                unknown = state.setdefault("unknown_users", {})
                for user in users:
                    unknown.pop(user, None)

        await self.store.update(save)
        data = await self.store.read()
        if data.get("enabled") and self._token:
            await self._start_tasks()
        elif enabled is False:
            for task in (
                self._worker_task,
                self._scheduler_task,
                self._expiry_task,
            ):
                if task is not None:
                    task.cancel()
            self._worker_task = self._scheduler_task = self._expiry_task = None
        return await self.full_status()


async def _iter_sse(response) -> Any:
    """解析 chat_stream 的 SSE 事件。"""
    buffer = ""
    body = getattr(response, "body_iterator", None)
    if body is None:
        return
    async for chunk in body:
        if isinstance(chunk, (bytes, bytearray)):
            text = chunk.decode("utf-8", errors="replace")
        else:
            text = str(chunk)
        buffer += text
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            event = "message"
            data_lines: list[str] = []
            for line in frame.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield event, payload


def _message_text(msg: dict[str, Any]) -> str:
    for item in msg.get("item_list") or []:
        if isinstance(item, dict) and item.get("type") == 1:
            text = (item.get("text_item") or {}).get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


channel = WeChatChannel()


def get_channel() -> WeChatChannel:
    return channel


__all__ = ["WeChatChannel", "channel", "get_channel"]
