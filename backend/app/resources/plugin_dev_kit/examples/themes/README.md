# 主题插件示例

每个子目录都是一个完整的主题插件源码，进入目录后直接压缩即可导入：

```bash
cd aurora && zip -r ../aurora-1.0.0.zip .
```

| 示例 | 说明 | 适合参考 |
|---|---|---|
| [`aurora/`](aurora/) | 深色极光：冷色玻璃面板 + 青绿强调色 | 完整颜色令牌、背景图、面板透明度 / 毛玻璃、`theme.css` 装饰样式、预览图 |

主题示例遵循以下约定：

- `plugin.json` 的 `kind` 固定为 `theme`，`entry` 与 `blocks` 为空；
- 颜色只使用规范列出的令牌（`app.background`、`surface.*`、`border.*`、`text.*`、`accent`）；
- 深色主题同时覆盖表面、文本、边框三组色阶，避免只改背景导致不可读；
- 背景图、预览图与字体放在 `assets/`，单文件 ≤ 4MB；
- `theme.css` 的每条规则都限定在 `html[data-kiwi-theme="<key>"]` 下，并提供真实可用的背景与预览图。

完整规范见 [`docs/THEME_SPEC.md`](../../THEME_SPEC.md)，AI 辅助开发见
[`.claude/skills/kiwi-theme/SKILL.md`](../../../.claude/skills/kiwi-theme/SKILL.md)。
