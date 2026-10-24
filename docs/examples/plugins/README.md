# 组件插件示例

每个子目录都是一个完整的组件插件源码，进入目录后直接压缩即可导入：

```bash
cd counter && zip -r ../counter-1.0.0.zip .
```

| 示例 | 说明 | 适合参考 |
|---|---|---|
| [`counter/`](counter/) | 最小可运行计数器 | manifest、`setup(host)`、props 读写、只读态 |
| [`pomodoro/`](pomodoro/) | 番茄钟：专注 / 休息阶段、时长调整、完成轮次 | 时间戳持久化、定时器清理、阶段切换、`host.toast` |
| [`countdown/`](countdown/) | 倒计时：预设时长、±1 分钟微调、完成次数 | 预设交互、进度条、窄容器响应式 |

两个计时器示例都遵循以下约定：

- 运行状态保存绝对时间戳 `endsAt`，刷新、切换笔记或重新打开后继续计时；
- 只在开始 / 暂停 / 重置 / 阶段切换 / 完成时写 props，不逐秒触发自动保存；
- 颜色全部使用 `--kiwi-*` CSS 变量，跟随系统主题色；
- 用 `container-type: inline-size` + `@container` 适配窄编辑器，而不是依赖视口宽度；
- 只读态隐藏操作按钮，运行中仍显示剩余时间；
- manifest 中声明 `pinnable: true`，选中区块后可置顶为跨页面浮窗；分栏等嵌入正文的区块不要声明该字段。

完整规范见 [`docs/PLUGIN_SPEC.md`](../../PLUGIN_SPEC.md)，AI 辅助开发见
[`.claude/skills/kiwi-plugin/SKILL.md`](../../../.claude/skills/kiwi-plugin/SKILL.md)。
