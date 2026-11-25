# 微信 ClawBot 渠道

Kiwi 通过腾讯官方 **微信 ClawBot（iLink）** 接入个人微信：在微信里直接向
知识库提问、确认写操作、创建每天定时推送。机器人登录、允许联系人、知识库
绑定与推送任务都在 **设置 → 微信** 管理。

> 这是官方 Bot API（`ilinkai.weixin.qq.com`），不是个人号 Hook。只处理文本
> 消息；图片 / 文件收发暂未接入。

## 1. 启用

服务端默认关闭。在 `.env` / `.env.prod` 设置：

```dotenv
KIWI_WECHAT_ENABLED=true
# 可选：登录状态与定时任务 JSON，默认 data/wechat_channel.json
# KIWI_WECHAT_STORE_FILE=
# 登录有效期（小时），默认 24
KIWI_WECHAT_SESSION_HOURS=24
# 主动推送的 context_token 窗口（小时），默认 24
KIWI_WECHAT_PUSH_WINDOW_HOURS=24
```

然后重启 backend。Docker 生产环境请确认主机可以访问
`https://ilinkai.weixin.qq.com`；登录状态保存在 `kiwi_data` 卷的
`/app/data/wechat_channel.json`，不要把它提交到仓库。

## 2. 扫码登录

打开 **设置 → 微信**，点击「扫码登录」：

1. 后端调用 `get_bot_qrcode?bot_type=3` 获取二维码；
2. 页面直接显示二维码图片，并每 2 秒刷新登录状态；
3. 用手机微信扫码确认后，后端保存加密的 `bot_token`，页面显示「已连接」；
4. 登录有效期约 24 小时；到期前会向最近联系人发送续连提醒，也可以在页面
   点「重新扫码」。

登录状态只保存在运行时 JSON 中，不写数据库；`bot_token` 使用
`KIWI_FERNET_KEY` 加密。重新扫码后 Bot ID 可能变化，旧会话自然失效。

## 3. 授权联系人

首次给 Bot 发消息的微信用户会收到一条「未授权」回复，其中包含其
`xxx@im.wechat` 联系人 ID；该用户也会出现在设置页的「待授权联系人」中，
点击「允许」或在「允许的联系人」里手动添加即可。默认拒绝所有未授权用户。

## 4. 问答与知识库

- 在设置页选择 **默认知识库**；微信里的问题会绑定到该库。
- 发送 `/kb` 查看知识库；`/kb 名称` 切换当前联系人的知识库。
- 常用指令：`/help`、`/status`、`/time`、`/reset`。
- 问答会复用 Kiwi 的 Agent：检索、工具、引用与行动计划都一致；回复以文本
  发送，过长的回答按段落拆分。

### 写操作确认

「允许写操作」默认关闭。开启后，新建 / 修改 / 删除笔记仍会先推送操作摘要：

```
需要确认：新建笔记《…》
回复「确认」执行，回复「取消」放弃（15 分钟内有效）。
```

确认后继续执行；超时或取消不会修改知识库。

## 5. 定时主动推送

有三种创建方式：

1. **设置页**：填写时间（如 `09:00`）、推送内容、知识库与联系人；
2. **微信里直接说**：例如「每天早上九点给我 XXX 知识库的待办」，Agent 会
   调用 `schedule_wechat_push` 创建任务并回复确认；
3. **API**：`POST /api/wechat/schedules`。

任务每天在指定时间运行一次，使用创建时绑定的知识库执行这段提示词，并把
回答主动发送到微信。可用 `/status` 或设置页查看、暂停、删除。

### 官方窗口限制

主动消息必须带最近一次收到的消息的 `context_token`，且通常只在 **24 小时**
窗口内有效。窗口过期时 Kiwi 不会丢弃内容：

- 推送内容进入队列；
- 用户下次给 Bot 发消息时，先补发一条带 `[补发]` 前缀的内容，再回复本次问题。

因此「每天早上 9 点推送」需要用户在前一天有过互动；否则会延迟到下一次互动。
登录本身也需要每 24 小时扫码续连，这是 ClawBot 平台限制。

## 6. 部署与排障

- 后端需要出站 HTTPS 到 `ilinkai.weixin.qq.com`；如果使用代理，配置容器
  的 `HTTPS_PROXY`。
- 登录二维码不显示：
  - 检查设置页是否提示 `KIWI_WECHAT_ENABLED=false`；
  - 检查 backend 日志中的 `微信 iLink 返回异常`；
  - 确认 `KIWI_FERNET_KEY` 可用（bot_token 加密依赖它）。
- 消息收不到：
  - 设置页「已连接」是否仍为真、剩余时间是否过期；
  - 联系人是否在允许列表；
  - 后端日志是否有 `getupdates` 失败。
- 主动推送没有到达：检查是否超出 24 小时窗口；内容会排队，下一次互动补发。
- 定时任务不执行：确认 `KIWI_WECHAT_ENABLED=true`、任务启用、时间按
  `KIWI_TIMEZONE`（默认 Asia/Shanghai）计算。

## 7. 主要接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/wechat/status` | 连接、登录二维码、允许联系人、任务 |
| PUT | `/api/wechat/settings` | 启用、默认知识库、写权限、允许联系人 |
| POST | `/api/wechat/login` | 获取二维码并开始扫码轮询 |
| POST | `/api/wechat/logout` | 断开并清除 token |
| GET/POST | `/api/wechat/schedules` | 列出 / 创建定时推送 |
| PATCH/DELETE | `/api/wechat/schedules/{id}` | 暂停 / 删除 |
| POST | `/api/wechat/test` | 向最近联系人发测试消息 |

以上接口都在现有访问令牌保护下。
