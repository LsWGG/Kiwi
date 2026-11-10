---
name: kiwi-theme
description: 为 Kiwi 开发、检查、打包或修复主题插件，包括设计前联网调研 UI 规范与优秀样例、plugin.json 的 theme 规格、颜色令牌、背景图与背景视频、透明度、theme.css 作用域、「欢迎使用 Kiwi」笔记预览图与导入验证。
---

# Kiwi 主题插件开发

主题插件（`kind: "theme"`）用**声明式 JSON + CSS** 定制整个 Kiwi 界面：
颜色、背景图 / 背景视频、面板透明度 / 毛玻璃、字体与装饰样式。主题不执行
JavaScript，安装后在「设置 → 主题」启用，即时生效，可随时切换回内置主题。

完整规范以仓库 `docs/THEME_SPEC.md` 为准；可运行样例在
`docs/examples/themes/aurora/`（深色极光）与 `docs/examples/themes/ink-dusk/`
（浅色古风，含符合规范的「欢迎使用 Kiwi」笔记预览图）。

## 设计前调研

先联网检索，再开始配色。跳过调研直接写令牌，通常只能得到「能看」而不是
「好看」的主题。

1. **UI 设计规范**：WCAG 2.2 对比度（正文 ≥ 4.5:1，大字号 / 图形 ≥ 3:1）、
   色彩体系（主色 / 中性色 / 语义色）、排版层级、间距与圆角节奏、背景图与
   玻璃面板的可读性边界。
2. **优秀样例**：同类笔记 / 效率工具主题、系统暗色模式指南（Material
   Design、Apple Human Interface Guidelines）、设计平台上的同风格作品。
   记录参考链接与取色依据。
3. **本项目物料**：本 skill、`docs/THEME_SPEC.md`、`examples/themes/aurora/`
   与至少一个已上线主题，确认哪些区域由令牌自动接管、哪些需要 `theme.css`。
4. 先把调研结论落成色板（底色 / 表面 / 文本四级 / 边框三级 / 强调）与背景
   方案，再写 `plugin.json` 和装饰 CSS。

## 画廊预览图

`theme.preview` **必须使用「欢迎使用 Kiwi」笔记页面的真实截图**（首次启动的
「Kiwi 上手指南」知识库中的同名笔记），不能使用设计稿、纯背景图、色板拼图
或示意图：

1. 导入并启用待验收主题，打开「欢迎使用 Kiwi」笔记页面（默认视图，保留侧栏），
   确认主题已生效。
2. 1440×900 视口、`deviceScaleFactor` 1.5–2 截图。
3. 缩放 / 裁切到 640×400 左右，保存为 `assets/preview.webp`。
4. 标题与正文清晰可辨；配色或背景改动后重新截图。

## 交付物

主题插件 zip（≤ 64MB）：

```
my-theme/
  plugin.json     # 必须：manifest + theme 规格
  theme.css       # 可选：装饰样式（style 指向它），≤ 512KB
  README.md       # 可选
  assets/         # 可选：背景图 / 视频、预览图、字体
    background.webp   # 背景图 / 视频封面
    background.mp4    # 背景视频（可选）
    preview.webp      # 必须：「欢迎使用 Kiwi」笔记真实截图（640×400）
    font.woff2
```

必须以 `.zip` 交付；资源支持图片（png / jpg / jpeg / webp / gif / svg /
avif / bmp）、字体（woff2 / woff / ttf / otf）与视频（mp4 / webm / ogv /
ogg / mov）。图片与字体单个 ≤ 4MB，视频单个 ≤ 48MB，资源合计 ≤ 60MB，
最多 40 个。

## manifest 字段

```json
{
  "manifest_version": 1,
  "kind": "theme",
  "key": "aurora",
  "name": "极光",
  "version": "1.0.0",
  "description": "深色极光渐变主题：冷色玻璃面板与青绿强调色。",
  "author": "",
  "icon": "palette",
  "homepage": "",
  "entry": "",
  "style": "theme.css",
  "blocks": [],
  "theme": {
    "mode": "dark",
    "colors": {
      "app.background": "#0b1020",
      "surface.background": "#121a30",
      "text.primary": "#e7ecff"
    },
    "background": {
      "image": "assets/aurora.svg",
      "video": "",
      "size": "cover",
      "position": "center",
      "repeat": "no-repeat",
      "dim": 0.25,
      "blur": 2
    },
    "surface": { "opacity": 0.82, "blur": 14 },
    "typography": { "body": "", "heading": "", "mono": "" },
    "preview": "assets/preview.svg"
  }
}
```

约束：

- `kind` 固定 `theme`；`entry` 必须为空；`blocks` 必须为空。
- `key`：`^[a-z0-9][a-z0-9-]{1,63}$`，全局唯一，发布后不可改，不能与内置主题
  （`kiwi-classic`）重名。
- `style` 是 zip 内相对路径；留空时自动查找根目录 `theme.css`。
- 至少声明 `theme.colors` 或 `theme.css` 之一，否则导入被拒绝。
- `theme.preview` 指向 `assets/` 下的缩略图，显示在主题画廊。

## 颜色令牌

`theme.colors` 只允许下列 key，未知 key 会被拒绝；省略的令牌由 Kiwi 默认值
补齐，因此主题可以只覆盖需要变化的部分。

| 令牌 | 作用 | 默认值 |
|---|---|---|
| `app.background` | 应用背景底色 | `#f8fafc` |
| `surface.background` | 面板 / 卡片 / 弹窗表面 | `#ffffff` |
| `surface.muted` | 次级填充（浅灰块） | `#f1f5f9` |
| `surface.strong` | 更深的填充 / 选中态 | `#e2e8f0` |
| `border.subtle` | 极浅分隔线 | `#f1f5f9` |
| `border.default` | 常规边框 | `#e2e8f0` |
| `border.strong` | 强调边框 / hover | `#cbd5e1` |
| `text.primary` | 主文本 | `#1e293b` |
| `text.strong` | 强调文本 | `#334155` |
| `text.secondary` | 次级文本 | `#475569` |
| `text.muted` | 辅助文本 | `#64748b` |
| `text.subtle` | 弱化文本 / 占位符 | `#94a3b8` |
| `text.faint` | 最弱文本 / 禁用 | `#cbd5e1` |
| `accent` | 强调色；省略时回落到内置默认色（编辑紫 / 学习绿） | 内置默认色 |
| `accent.foreground` | 强调色上的文字颜色 | `#ffffff` |

`accent` 是主题包声明的默认强调色，编辑模式与学习模式默认共用；用户可在
「设置 → 主题 → 自定义外观」里分别覆盖两种模式的强调色（对应覆盖字段
`accent` / `learn_accent`），两套颜色独立保存、互不影响。

值可以是 `#rgb` / `#rrggbb`、`rgb()`、`hsl()` 等合法 CSS 颜色，不能包含
`;` `{` `}` `<` `>`。

## 背景与表面

- `background.image`：`assets/` 相对路径、`https://` 或 `data:image/...`。
  声明 `video` 时它同时作为视频封面（poster）。
- `background.video`：`assets/` 下的 mp4 / webm / ogv / ogg / mov，或
  `https://` URL；静音自动循环播放。与 `image` 同时声明时视频优先，图片
  作为封面。只声明视频也可以，但建议提供一张压缩后的封面图。
- `background.size`：`cover` / `contain` / `auto`；`position` 为 CSS
  `background-position`；`repeat` 为 `no-repeat` / `repeat` / `repeat-x` /
  `repeat-y`。视频始终按 `cover` 铺满，`dim` / `blur` 同样生效。
- `background.dim`：暗化遮罩 0–0.9，深色背景下常用 0.2–0.4 压低图片对比度。
- `background.blur`：背景模糊 0–40px。
- `surface.opacity`：面板不透明度 0.35–1；`surface.blur`：面板毛玻璃 0–40px；
  `surface.radius`：圆角令牌 0–40，主题 CSS 可用 `var(--theme-radius)`。

背景与面板透明度由 Kiwi 兼容层统一接管：`bg-white`、`bg-slate-*`、
`text-slate-*`、`border-slate-*` 及其透明度 / hover 变体都会映射到令牌，
不需要逐个组件写覆盖。

背景解析优先级：用户视频 > 用户图片 > 主题视频 > 主题图片；用户设置背景后
会完整替换主题背景，不会叠加。

用户自定义背景与主题包资源是两套限制：主题包内图片 / 字体单个 ≤ 4MB、
视频单个 ≤ 48MB、资源合计 ≤ 60MB；用户在「设置 → 主题 → 自定义外观」
上传的背景走独立接口，≤ 100MB，支持
PNG（含 APNG）/ JPEG / GIF / WebP（含动态）/ AVIF / BMP，以及 MP4 / WebM /
Ogg / MOV 视频（静音循环，优先 MP4 / WebM）。上传后图片 URL 写入
`background_image`、视频 URL 写入 `background_video`；两者同时存在时视频优先，
`dim` / `blur` 与 `surface.*` 同样作用于视频。SVG 与 `data:` 视频会被拒绝。

## theme.css

`theme.css` 作为全局样式注入。**每条规则都必须限定在主题 key 下**：

```css
html[data-kiwi-theme="aurora"] .ProseMirror h1 {
  text-shadow: 0 0 24px rgb(94 234 212 / 0.35);
}

html[data-kiwi-theme="aurora"] ::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #5eead4, #818cf8);
}
```

- 需要覆盖兼容层时提高特异性即可，如
  `html[data-kiwi-theme="aurora"] .bg-white`。
- 字体放在 `assets/` 并用相对路径引用，会解析到
  `/api/plugins/<id>/assets/...`：

  ```css
  @font-face {
    font-family: "Theme Serif";
    src: url("assets/theme-serif.woff2") format("woff2");
    font-display: swap;
  }
  ```

- 不要使用外部 `@import`（离线 / 内网会失败），不要写 JavaScript；交互效果用
  纯 CSS transition / animation。
- 常用区域：`body`、`.ProseMirror`、`.ProseMirror h1…h6`、`.ProseMirror pre` /
  `code`、`.kiwi-editor`、`.editor-canvas`、`.editor-sheet`、
  `::-webkit-scrollbar`、`[data-kiwi-theme]`。
- 编辑器画布、纸张、正文、标题、引用块、表格与分页缝会自动跟随主题令牌
  （纸张取 `surface.background`）。需要纸张纹理或半透明时，覆盖
  `.editor-sheet` 并用 `!important` 压过引擎写入的行内底色。

## 用户可覆盖项

启用主题后，用户仍可在「设置 → 主题 → 自定义」覆盖背景（图片 / 视频）、
暗化、模糊、面板透明度 / 毛玻璃与强调色；用户覆盖优先于主题包默认值。
自定义外观按主题 key 独立保存，切到其他主题再切回来会自动恢复；删除主题时
对应的覆盖值与只被它引用的上传背景文件会一并清理。设计时不要把关键信息只
放在背景图 / 视频里，也不要把 `surface.opacity` 压到 0.6 以下而不加模糊。

## 开发流程

1. 复制 `docs/examples/themes/aurora/` 作为起点，先改 `key` / `name` 与
   颜色令牌，再补背景与装饰。
2. 按「画廊预览图」要求，用「欢迎使用 Kiwi」笔记的真实截图生成
   `assets/preview.webp`（640×400）；若使用背景视频，再准备一张同画面的
   WebP / JPEG 封面。
3. 压缩为 zip（`plugin.json` 可在 zip 根目录或单一子目录内）：

   ```bash
   cd my-theme && zip -r ../my-theme.zip .
   ```

4. 预检（不落库）：

   ```bash
   curl -F "file=@my-theme.zip" http://127.0.0.1:8011/api/themes/inspect
   ```

5. 在「设置 → 主题 → 导入主题」导入并启用，逐页检查：笔记列表、编辑器、
   阅读态、弹窗、表格、画布、聊天、设置页、登录页。使用视频时确认首屏
   显示封面、循环播放无明显跳帧，并在 DevTools Network 里确认资源请求
   返回 `206 Partial Content` 与 `Accept-Ranges: bytes`。
6. 从主题卡片「导出」下载 zip，重新导入验证往返一致。
7. 若改动了仓库代码，运行前端 `npm run type-check` / `npm run build` 与后端
   相关测试。

## 设计建议

- 深色主题必须同时调整 `surface`、`text`、`border` 三组令牌；只改背景会导致
  文字与边框不可读。
- `surface.opacity` 低于 0.7 时，提高 `surface.blur` 并加深 `background.dim`。
- 背景优先 SVG / WebP，控制在 500KB 以内；装饰元素优先用 CSS 渐变 / 伪元素，
  避免堆叠大图。
- 背景视频建议 1080p、10–20 秒无缝循环、无音轨、MP4（H.264，
  `-movflags +faststart`）或 WebM，控制在 15MB 以内；同时提供 WebP / JPEG
  封面。视频只做氛围层，不要把关键信息放进视频。
- 古风 / 科技 / 动漫等强风格主题：用 `area` 级的 `theme.css`（标题装饰、卡片
  描边、滚动条、纹理）承载风格，颜色令牌保持可读性优先。

## 验收清单

- [ ] 设计前做过调研，色板与层级有明确依据
- [ ] 正文 / 次级 / 弱化文本对比度达标（正文 ≥ 4.5:1）
- [ ] `theme.css` 全部限定在 `html[data-kiwi-theme="<key>"]` 下
- [ ] 主面板透明度 / 模糊响应 `--theme-surface-opacity` / `--theme-surface-blur`
- [ ] 逐页检查：笔记列表、编辑器、阅读态、弹窗、表格、画布、聊天、设置页、登录页
- [ ] 预览图截自「欢迎使用 Kiwi」笔记，640×400，主题已生效
- [ ] `/api/themes/inspect` 通过，导出后重新导入一致
- [ ] 背景图 / 视频体积与格式符合上限，视频同时提供封面

## 参考

- 完整规范：`docs/THEME_SPEC.md`
- 示例主题：`docs/examples/themes/aurora/`（深色）、
  `docs/examples/themes/ink-dusk/`（浅色古风，含符合规范的「欢迎使用 Kiwi」
  笔记预览图）
- 内置主题导出：`GET /api/themes/builtin/kiwi-classic/export`
- 主题开发套件：`GET /api/themes/dev-kit`（根目录 `THEME_SPEC.md`、
  `examples/themes/`、`skill/kiwi-theme/SKILL.md` 与 `AI_PROMPT.md`）
- 组件插件（在正文里放交互组件）：`.claude/skills/kiwi-plugin/SKILL.md`
