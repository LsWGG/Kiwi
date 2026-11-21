# 问答 Agent 与 MCP

Kiwi 的问答 Agent 不再内置工具枚举。所有工具都通过注册表以统一的 JSON
Schema 暴露，Agent 循环只依赖 `Toolbox`：

- **内置工具**：`backend/app/services/agent_tools.py` 用 `@_tool` 注册；
- **外部工具**：配置一个或多个 MCP 服务，启动或问答时动态发现；
- **MCP 服务端**：Kiwi 也把自己的笔记工具暴露成标准 MCP 端点，供其他客户端调用。

新增工具只需要注册一个 `ToolDef` 与处理函数，不需要改 Agent 循环。

## 一、工具注册表

每个 `ToolDef` 包含：

| 字段 | 作用 |
|---|---|
| `name` | 工具名；外部工具为 `mcp__<server>__<tool>` |
| `label` | 中文短名，用于审批卡片与阶段提示 |
| `description` | 给 LLM 看的用途说明，应写清何时使用、限制与返回内容 |
| `input_schema` | JSON Schema；内置工具由 Pydantic 模型自动生成 |
| `read_only` | 只读工具自动执行；否则进入用户确认队列 |
| `destructive` | 标记删除类操作（MCP `destructiveHint`） |
| `arg_labels` | 参数名到中文标签，前端审批卡片直接使用 |

内置工具的参数使用 `Field(title=..., description=...)` 描述。`title` 进入审批
UI，`description` 进入 LLM 工具清单，因此新增参数时必须同时写清楚。

注册示例：

```python
class FindTagArgs(BaseModel):
    name: str = Field(title="标签名", description="要查找的标签名。")

@_tool("find_tag", "查找标签", "按名称查找标签，返回标签 ID 与使用次数。",
       FindTagArgs, read_only=True)
async def _find_tag(session, kb_id, args: FindTagArgs) -> dict:
    ...
```

## 二、让 Agent 调用外部 MCP 服务

配置来源（优先级从高到低）：

1. 环境变量 `KIWI_MCP_SERVERS_JSON`（JSON 字符串）；
2. 环境变量 `KIWI_MCP_SERVERS_FILE` 指向的 JSON 文件，默认
   `backend/data/mcp_servers.json`。

格式：

```json
{
  "servers": [
    {
      "name": "demo",
      "url": "https://mcp.example.com/mcp",
      "headers": {"Authorization": "Bearer <token>"},
      "timeout": 30
    }
  ]
}
```

约束：

- `name` 只能包含字母、数字、`-`、`_`，且不能重复；
- 仅支持 `http://` / `https://`。出于安全考虑，Kiwi **不会**自动拉起本地 stdio
  进程；本地工具请单独运行 MCP 服务再配置 URL；
- `headers` 可放鉴权信息。不要把含密钥的配置文件提交到仓库；
- 发现的工具名统一加 `mcp__<server>__` 前缀，避免与内置工具冲突；
- `annotations.readOnlyHint !== true` 的外部工具一律按写操作处理，必须经用户确认；
  调用失败不会影响内置工具，服务不可用时短时间缓存空结果，避免每次问答都等超时；
- 工具清单缓存 `KIWI_MCP_CACHE_TTL` 秒（默认 300），最多保留
  `KIWI_MCP_MAX_TOOLS` 个（默认 80）。

MCP 客户端使用 Streamable HTTP + JSON-RPC，支持 `application/json` 与
`text/event-stream` 两种响应。

## 三、Kiwi 作为 MCP 服务端

端点：`POST /api/mcp?kb_id=<知识库 UUID>`

鉴权与 `/api` 其他接口一致：启用 `KIWI_ACCESS_TOKEN` 时，请求需带
`X-Access-Token`、`Authorization: Bearer` 或登录 Cookie。

支持的方法：

- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list`
- `tools/call`

> 写工具必须额外携带 `X-Kiwi-Write-Approved: true`。这是独立于访问令牌的第二道
> 闸门，防止外部客户端在未确认的情况下修改笔记。只读工具不需要该请求头。

示例：

```bash
KB=00000000-0000-0000-0000-000000000000

# 列出工具
curl -s http://127.0.0.1:8000/api/mcp?kb_id=$KB \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# 只读调用
curl -s http://127.0.0.1:8000/api/mcp?kb_id=$KB \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_folders","arguments":{}}}'

# 写调用（需显式授权）
curl -s http://127.0.0.1:8000/api/mcp?kb_id=$KB \
  -H 'Content-Type: application/json' \
  -H 'X-Kiwi-Write-Approved: true' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"create_folder","arguments":{"name":"新分组"}}}'
```

返回约定：

- 工具执行成功：`result.content`（文本）与 `result.structuredContent`（结构化结果）；
- 工具业务错误：`result.isError = true`，错误文本在 `content` 中；
- 协议错误：JSON-RPC `error`，如 `-32602`（参数 / 未知工具）、`-32003`（写操作
  未经授权）；
- 所有操作都限定在 `kb_id` 指定的知识库内；上锁笔记不可读写。

该端点只暴露内置工具，不会把外部 MCP 工具再次代理出去，避免递归调用。

## 四、Agent 执行流程

1. `chat.py` 调用 `agent_tools.load_toolbox()` 构建本轮工具集（内置 + 外部）；
2. `build_messages` 把工具清单、权限、当前日期与系统提示模板写入 system 消息；
3. 模型返回 `{thought, plan, action, answer}`；
4. 只读工具直接执行；写工具登记到内存队列，本轮 SSE 结束，等待用户批准；
5. 用户批准后携带 `resume_action_id` 继续同一个循环；批准动作一次性消费；
6. 达到 `KIWI_AGENT_MAX_STEPS` 后强制模型给出总结，不再调用工具。

系统提示模板位于 `backend/app/prompts/agent_system.md`，支持
`$tool_prompt`、`$permission`、`$current_date`、`$weekday`、`$timezone`、
`$max_steps` 占位符。可用 `KIWI_AGENT_PROMPT_FILE` 指向自定义模板；模板缺失或
不可读时自动回落到内置模板。
