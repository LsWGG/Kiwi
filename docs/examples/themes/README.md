# 主题插件示例

本目录只保留 Kiwi 系统内置主题「极光」的完整源码，随开发套件分发；进入目录后直接压缩即可导入：

```bash
cd aurora && zip -r ../aurora-1.0.0.zip .
```

| 示例 | 说明 | 适合参考 |
|---|---|---|
| [`aurora/`](aurora/) | 深色极光：冷色玻璃面板 + 青绿强调色 | 完整颜色令牌、背景图（`video` 字段的占位写法）、面板透明度 / 毛玻璃、`theme.css` 装饰样式、预览图 |

> 第三方主题插件（「伟大航路」`grand-line`、「墨霞」`ink-dusk`、「霓虹禁语」
> `neon-hush` 等）的源码统一维护在
> [`kiwi-timer-plugins`](https://github.com/LsWGG/kiwi-timer-plugins) 仓库的
> `themes/` 下，由该仓库负责版本、打包与发布；Kiwi 仓库只保留内置主题
> 「经典紫」与「极光」。

主题示例遵循以下约定：

- `plugin.json` 的 `kind` 固定为 `theme`，`entry` 与 `blocks` 为空；
- 颜色只使用规范列出的令牌（`app.background`、`surface.*`、`border.*`、`text.*`、`accent`）；
- 深色主题同时覆盖表面、文本、边框三组色阶，避免只改背景导致不可读；
- 背景图、预览图、字体与背景视频放在 `assets/`；图片 / 字体单个 ≤ 4MB，
  视频单个 ≤ 48MB，资源合计 ≤ 60MB；
- `theme.css` 的每条规则都限定在 `html[data-kiwi-theme="<key>"]` 下，并提供真实可用的背景；
- 预览图必须使用「欢迎使用 Kiwi」笔记页面的真实截图（640×400），不能用设计稿
  或纯背景图；示例里的 `aurora/assets/preview.svg` 只是占位；
- 设计前先联网检索 UI 设计规范（对比度、色彩体系、排版层级）与优秀主题样例，
  把调研结论落成色板后再写实现。

完整规范见 [`docs/THEME_SPEC.md`](../../THEME_SPEC.md)，AI 辅助开发见
[`.claude/skills/kiwi-theme/SKILL.md`](../../../.claude/skills/kiwi-theme/SKILL.md)。
