# 主题插件示例

每个子目录都是一个完整的主题插件源码，进入目录后直接压缩即可导入：

```bash
cd aurora && zip -r ../aurora-1.0.0.zip .
```

| 示例 | 说明 | 适合参考 |
|---|---|---|
| [`aurora/`](aurora/) | 深色极光：冷色玻璃面板 + 青绿强调色 | 完整颜色令牌、背景图（`video` 字段的占位写法）、面板透明度 / 毛玻璃、`theme.css` 装饰样式、预览图 |
| [`ink-dusk/`](ink-dusk/) | 浅色古风「墨霞」：宣纸底色 + 朱砂强调 + 鎏金细线 | 浅色主题色板、衬线排版、编辑器纸张纹理，以及符合规范的「欢迎使用 Kiwi」笔记预览图 |
| [`grand-line/`](grand-line/) | 海贼王「伟大航路」：悬赏令报纸 + 背景视频 + 草帽骷髅旗 | 背景视频与封面、随包展示字体、伪元素装饰（报头 / 水印 / 航线）、全组件覆盖；因含 5.7MB 视频，仓库完整示例不进开发套件 |

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
