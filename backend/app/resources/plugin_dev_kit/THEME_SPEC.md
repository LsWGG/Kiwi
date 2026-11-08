# Kiwi 主题插件规范

主题插件（`kind: "theme"`）用声明式 JSON + CSS 定制整个 Kiwi 界面：颜色、
背景、面板透明度、毛玻璃、字体与装饰样式。主题包不执行 JavaScript，安装
后在「设置 → 主题」中启用，即时生效。

## 1. 包结构

```
theme.zip
├─ plugin.json          # 必须：manifest + theme 规格
├─ theme.css            # 可选：装饰性样式
├─ README.md            # 可选
└─ assets/              # 可选：背景图 / 视频、预览图、字体
   ├─ background.mp4    # 背景视频（可选）
   ├─ background.webp   # 背景图 / 视频封面（poster）
   ├─ preview.png
   └─ font.woff2
```

限制：

| 项目 | 上限 |
|---|---|
| 整包 | 64MB |
| `plugin.json` | 1MB |
| `theme.css` | 512KB |
| 单个图片 / 字体 | 4MB |
| 单个视频 | 48MB |
| 资源总量 | 60MB |
| 资源数量 | 40 |

资源支持图片（png / jpg / jpeg / webp / gif / svg / avif / bmp）、字体
（woff2 / woff / ttf / otf）与视频（mp4 / webm / ogv / ogg / mov）。
视频建议使用 MP4（H.264）或 WebM，静音循环播放；`image` 同时作为视频
封面，避免首帧解码前露出应用底色。

## 2. plugin.json

```json
{
  "manifest_version": 1,
  "kind": "theme",
  "key": "aurora",
  "name": "极光",
  "version": "1.0.0",
  "description": "深色极光渐变主题",
  "author": "Kiwi",
  "icon": "palette",
  "homepage": "",
  "entry": "",
  "style": "theme.css",
  "blocks": [],
  "theme": {
    "mode": "dark",
    "colors": { "...": "见第 3 节" },
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

字段说明：

| 字段 | 说明 |
|---|---|
| `kind` | 固定 `theme` |
| `key` | 全局唯一小写 slug，`^[a-z0-9][a-z0-9-]{1,63}$`，不能与内置主题重名 |
| `entry` | 必须为空 |
| `style` | `theme.css` 在包内的相对路径，留空时自动查找 `theme.css` |
| `blocks` | 必须为空 |
| `theme.mode` | `light` / `dark`，决定 `color-scheme` |
| `theme.preview` | 主题画廊缩略图，`assets/` 下相对路径 |

## 3. 颜色令牌

`theme.colors` 只允许以下 key，未知 key 会被拒绝。省略的令牌由 Kiwi 默认值
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

颜色值可以是 `#rgb` / `#rrggbb`、`rgb()`、`hsl()` 等合法 CSS 颜色，不能包含
`;` `{` `}` `<` `>`。

## 4. 背景与表面

`theme.background`：

| 字段 | 说明 |
|---|---|
| `image` | 背景图：`assets/` 相对路径、`https://` 或 `data:image/...`；声明 `video` 时作为视频封面（poster） |
| `video` | 背景视频：`assets/` 下的 mp4 / webm / ogv / ogg / mov，或 `https://` URL；静音自动循环播放 |
| `size` | `cover` / `contain` / `auto` |
| `position` | CSS `background-position`，如 `center` / `top left` |
| `repeat` | `no-repeat` / `repeat` / `repeat-x` / `repeat-y` |
| `dim` | 暗化遮罩，0–0.9 |
| `blur` | 背景模糊，0–40px |

`video` 与 `image` 同时声明时优先播放视频，图片作为视频封面；只声明
`video` 也可以，但建议同时提供一张压缩后的 WebP / JPEG 封面，首屏与
视频加载失败时仍有背景。`size` / `position` / `dim` / `blur` 对视频同样
生效（视频固定按 `cover` 铺满，模糊时自动放大 6% 避免边缘露底）。

背景优先级：用户上传的视频 > 用户上传的图片 > 主题包 `video` > 主题包
`image`。用户只要在「自定义外观」里设置了背景，就会完整替换主题背景，
不会出现两层叠加。

> 主题包视频以站内资源接口下发，支持 HTTP Range（206）分段加载与跳转。
> 视频不会进入 `localStorage` 主题缓存，刷新首屏先显示封面，随后开始播放。
> 主题 CSS 中不能用 `url()` 播放视频，视频只通过 `theme.background.video`
> 声明。

`theme.surface`：

| 字段 | 说明 |
|---|---|
| `opacity` | 面板不透明度，0.35–1；配合背景图可做玻璃拟态 |
| `blur` | 面板毛玻璃，0–40px |
| `radius` | 预留圆角令牌，0–40；主题 CSS 可用 `var(--theme-radius)` |

背景图与面板透明度由 Kiwi 的兼容层统一接管：`bg-white`、`bg-slate-50/100`、
`text-slate-300…900`、`border-slate-100/200/300` 及其透明度、hover 变体都会
自动映射到令牌。主题 CSS 可以继续覆盖具体组件，但大面积表面的 alpha 必须
直接取 `--theme-surface-opacity`（见第 5 节「面板不透明度必须响应自定义外观」）。

### 用户自定义背景（运行时上传）

主题包内的背景仍受包体限制（图片与字体单个 4MB、视频单个 48MB、资源合计
60MB）；用户在「设置 → 主题 → 自定义外观」里上传的背景走独立接口与存储，
与主题包无关：

| 项目 | 限制 |
|---|---|
| 文件大小 | ≤ 100MB |
| 图片 | PNG（含 APNG）/ JPEG / GIF / WebP（含动态）/ AVIF / BMP |
| 视频 | MP4 / WebM / Ogg / MOV，静音循环播放；优先 MP4 / WebM |
| 存储位置 | `/media/theme-backgrounds/`，覆盖值只保存站内 URL |

上传接口为 `POST /api/themes/background`，返回 `url`、`kind` 与 `content_type`；
未被覆盖值引用的文件会在一段时间后自动清理，也可用
`DELETE /api/themes/background?url=` 主动删除。图片 URL 写入
`background_image`，视频 URL 写入 `background_video`；两者同时存在时视频优先。
`background_dim`、`background_blur` 与 `surface.*` 同样作用于视频背景。
出于安全考虑，SVG 与 `data:` 视频会被拒绝。

## 5. theme.css

`theme.css` 会作为全局样式注入。**所有规则必须限定在主题 key 下**：

```css
html[data-kiwi-theme="aurora"] .ProseMirror h1 {
  text-shadow: 0 0 24px rgb(94 234 212 / 0.35);
}

html[data-kiwi-theme="aurora"] ::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #5eead4, #818cf8);
}
```

约定：

- 使用 `html[data-kiwi-theme="<key>"]` 前缀，避免主题之间互相污染。
- 需要覆盖 Kiwi 的兼容层时，提高选择器特异性即可（例如
  `html[data-kiwi-theme="aurora"] .bg-white`）。
- 字体文件放在 `assets/`，用 `@font-face` 引用：
  ```css
  @font-face {
    font-family: "Theme Serif";
    src: url("assets/theme-serif.woff2") format("woff2");
    font-display: swap;
  }
  ```
  `url("assets/...")` 会解析到 `/api/plugins/<id>/assets/...`。
- 不建议使用外部 `@import`，离线 / 内网部署会加载失败。
- 不使用 JavaScript；需要交互效果请用纯 CSS（transition / animation）。

### 面板不透明度必须响应「自定义外观」

用户在「设置 → 主题 → 自定义外观」里调整的面板不透明度会写入
`--theme-surface-opacity`（0.35–1），编辑模式与学习模式共用。

**主面板的 alpha 直接取这个变量，不要再乘 0.9 / 0.8 之类的设计系数。**
实际界面和设置里的预览必须一致：用户设为 35%，侧栏、页头、页面容器、
聊天区、纸张等主面板的最终不透明度就应当是 35%。乘系数属于暗加权重，
会让人误以为滑块没生效。

```css
html[data-kiwi-theme="aurora"] .sidebar-glass {
  background-color: rgb(251 246 232 / var(--theme-surface-opacity));
  backdrop-filter: blur(var(--theme-surface-blur));
}
```

以下写法会让预览与实际不一致，禁止用于主面板：

```css
background: rgb(251 246 232 / 0.9);                    /* 写死 alpha */
background: #fbf6e8;                                   /* 完全不透明 */
background: rgb(251 246 232 / calc(0.9 * var(--...))); /* 暗加系数 */
/* 双层叠加：background-color 与半透明 background-image 同时生效，
   实际覆盖率约等于 1-(1-a)(1-b)，比设置值更实 */
background-color: rgb(251 246 232 / var(--theme-surface-opacity));
background-image: linear-gradient(rgb(251 246 232 / 0.9), rgb(251 246 232 / 0.8));
```

大面积表面只允许**一层**底色；渐变、纹理等装饰用不透明度极低
（≤ 0.05）的叠加，或放到伪元素里，避免抬高整体不透明度。

毛玻璃模糊同样跟随用户设置：一律写
`backdrop-filter: blur(var(--theme-surface-blur))`，不要写死
`blur(24px)`。用户把「毛玻璃模糊」调到 0 时，宿主会关闭主面板上的
`backdrop-filter`，包括组件里 `@apply backdrop-blur-*` 的固定模糊。

小面积控件可以保持不透明或固定 alpha / 固定模糊，以保证可读性：菜单 /
下拉框、tooltip、`kbd`、按钮、选中高亮、状态徽标，以及图表与画布内容。
判断标准：调低不透明度、调低模糊时，侧栏、页头、页面容器、卡片、编辑器
画布 / 纸张、Notebook、聊天区、数据表容器等应正确透出壁纸。

自查：把不透明度设为 35%、模糊设为 0，然后在 DevTools 检查主面板：
`backgroundColor` 的 alpha 应正好是 0.35，`backdropFilter` 应为 `none`，
`backgroundImage` 不应再叠一层半透明渐变。

常用可覆盖区域：

| 选择器 | 区域 |
|---|---|
| `body` | 应用背景 |
| `.ProseMirror` | 编辑器 / 阅读态正文 |
| `.ProseMirror h1` … `h6` | 标题 |
| `.ProseMirror pre` / `code` | 代码块 |
| `.kiwi-editor` | 编辑器外壳 |
| `.editor-canvas` | 编辑器画布（纸张外的灰色区域） |
| `.editor-sheet` | 编辑器纸张 |
| `.sheet-*` | 表格笔记（工具栏 / 单元格 / 页签 / 筛选） |
| `.db-*` | 数据表笔记（表头 / 行号 / 单元格 / 进度字段） |
| `.nb-*` / `.cm-editor` | Notebook 单元格、输出与代码编辑器 |
| `.jvs-draw-container` | 画布笔记的外围界面（工具栏 / 面板 / 魔法棒） |
| `body.theme-learn` | 学习模式（与编辑模式共用主题，强调色可独立配置） |
| `::-webkit-scrollbar` | 滚动条 |
| `[data-kiwi-theme]` | 所有界面 |

编辑器适配：安装主题启用后，编辑画布、纸张、正文、标题、引用块、表格、
分页缝与 DOCX 页眉页脚会自动改用主题令牌（纸张取 `surface.background`），
深色主题不需要额外 CSS 也能保证正文可读。表格、数据表、Notebook 与画布
外围界面同样接入主题令牌；画布内容由 `<canvas>` 绘制，深色主题下会整体反色
（同时反转色相，保持线条与填充的颜色关系），含图片 / 网页嵌入的画布保持原色
以避免负片。表格笔记中用户保存的单元格填充与文字色会在渲染时映射为同色相的
暗色 / 浅色等价物，原始格式数据不变，切回浅色主题即恢复。

学习模式：主题的 `colors`、背景与字体同时作用于编辑模式和学习模式；主题包的
`accent` 默认同时作为两种模式的强调色。用户可以在「设置 → 主题 → 自定义外观」
里分别覆盖编辑模式与学习模式的强调色，两套颜色独立保存、互不影响。若需要为
学习模式做差异化样式，使用 `html[data-kiwi-theme="<key>"] body.theme-learn` 限定。

若想给纸张加纹理或半透明效果，可在 `theme.css` 中覆盖纸张：

```css
html[data-kiwi-theme="gufeng"] .editor-sheet {
  background: #f6efe3 !important; /* 覆盖引擎写入的行内底色 */
  background-image: url("assets/paper-texture.webp");
}
```

## 6. 生命周期与优先级

1. 启动时前端读取缓存的当前主题并立即应用，随后从 `/api/themes/active` 刷新。
2. 主题包内 `theme.colors` 写入 CSS 变量；背景视频与 `theme.css` 随后注入。
3. 用户在「设置 → 主题」里的背景 / 透明度 / 强调色覆盖优先于主题包默认值；
   背景按「用户视频 > 用户图片 > 主题视频 > 主题图片」解析；编辑模式覆盖
   写入 `accent`，学习模式覆盖写入 `learn_accent`，二者互不影响。
4. 自定义外观按主题 key 独立保存：切到其他主题不会清空，切回来时自动恢复；
   只有「恢复主题默认外观」会清空当前主题的覆盖值。
5. 主题未声明 `accent` 时，编辑模式用内置冷紫、学习模式用内置翠绿；声明后两种模式默认跟随主题强调色。
6. 停用或删除当前主题会自动回退到内置「经典紫」，同时停止并释放背景视频解码器。
   删除主题时，其自定义外观记录一并删除；只被该主题引用的上传背景图片 /
   视频也会立即从 `/media/theme-backgrounds/` 清理，其他主题仍在使用的文件
   会保留。

## 7. 校验与导入

- 预检：`POST /api/themes/inspect`（multipart `file`），不落库。
- 导入：`POST /api/themes/import?overwrite=true`。
- 导出：`GET /api/plugins/{id}/export`。
- 内置主题导出：`GET /api/themes/builtin/kiwi-classic/export`。
- 开发套件：`GET /api/themes/dev-kit`。

## 8. 设计建议

- 深色主题必须同时调整 `surface`、`text`、`border` 三组令牌；只改背景会导致
  文字与边框不可读。
- `surface.opacity` 低于 0.7 时，建议提高 `surface.blur` 并加深背景暗化。
- 背景图优先使用 SVG / WebP；大图请压缩到 500KB 以内。
- 背景视频建议 1080p、10–20 秒无缝循环、无音轨、MP4（H.264，
  `-movflags +faststart`）或 WebM，控制在 15MB 以内；同时提供 WebP / JPEG
  封面。视频只做氛围层，不要把关键信息放进视频。
- 装饰元素（边框、角花、纹理）优先用 CSS 渐变 / 伪元素实现，避免堆叠大图。
- 逐页检查：笔记列表、编辑器、弹窗、表格、聊天、设置页、登录页。
