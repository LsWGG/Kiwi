# 微信 ClawBot 渠道

Kiwi 通过腾讯官方 **微信 ClawBot（iLink）** 接入个人微信：在微信里直接向
知识库提问、确认写操作、创建定时推送。机器人登录、知识库绑定与推送任务都在
**设置 → ClawBot** 管理。

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

打开 **设置 → ClawBot**，点击「扫码登录」：

1. 后端调用 `get_bot_qrcode?bot_type=3` 获取二维码；
2. 页面直接显示二维码图片，并每 2 秒刷新登录状态；
3. 用手机微信扫码确认后，后端保存加密的 `bot_token`，页面显示「已连接」；
4. 官方返回的 `qrcode_img_content` 是登录链接，页面会在前端把它生成为二维码，
   同时提供「在手机中打开登录链接」和「复制链接」兜底；
5. 登录有效期约 24 小时；到期前会向最近联系人发送续连提醒，也可以在页面
   点「重新扫码」。

登录状态只保存在运行时 JSON 中，不写数据库；`bot_token` 使用
`KIWI_FERNET_KEY` 加密。重新扫码后 Bot ID 可能变化，旧会话自然失效。

## 3. 单联系人

ClawBot 只有一个对话窗口，相当于一个联系人，因此不需要维护联系人 ID 或
允许列表。首次给 Bot 发消息后，该会话自动成为主动推送的目标；页面只保留
连接状态、知识库与定时任务。

## 4. 问答与知识库

- 在设置页多选 **默认知识库**；微信里的问题会在这几个库内检索。
- 多选知识库时为只读：Agent 的写工具需要单库权限；如需新建 / 修改 / 删除，
  请只保留一个库并开启「允许写操作」。
- 发送 `/kb` 查看知识库；`/kb 名称` 临时切换为单库；`/kb all` 恢复默认多库。
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

支持三种计划方式：

1. **常用**：选择每天 / 工作日 / 每周X / 每月N号，再用系统时间选择器设置
   HH:MM（不使用浏览器原生时间控件）；
2. **Cron**：直接填写标准 5 段 cron（分 时 日 月 周，周日=0），例如
   `0 9 * * *`、`30 8 * * 1-5`；
3. **自然语言**：在 Cron 页输入「每天早上九点」「工作日八点半」「每周一
   10:00」「每 2 小时」等，点「解析」；后端优先调用已配置的大模型转 cron，
   失败时回退确定性规则。页面会展示 cron、中文描述与最近运行时间。

任务可以绑定一个或多个知识库，到点后执行提示词并把回答主动发送到微信。
可用 `/status` 或设置页查看、暂停、删除。也可以在微信里直接说「每天早上
九点给我 XXX 知识库的待办」，Agent 会调用 `schedule_wechat_push` 创建任务。

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
| GET | `/api/wechat/status` | 连接、登录二维码、知识库与任务 |
| PUT | `/api/wechat/settings` | 启用、默认知识库（多选）、写权限 |
| POST | `/api/wechat/login` | 获取二维码并开始扫码轮询 |
| POST | `/api/wechat/logout` | 断开并清除 token |
| GET/POST | `/api/wechat/schedules` | 列出 / 创建定时推送（cron / 自然语言） |
| POST | `/api/wechat/schedules/preview` | 自然语言 / cron → 描述与最近运行时间 |
| PATCH/DELETE | `/api/wechat/schedules/{id}` | 暂停 / 删除 |
| POST | `/api/wechat/test` | 向最近联系人发测试消息 |

以上接口都在现有访问令牌保护下。
