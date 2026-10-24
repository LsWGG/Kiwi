# 组件插件开发规范

Kiwi 只支持**组件插件**（`kind: "component"`），在「设置 → 插件与区块」
（`/settings/plugins`）中导入、预览、启停与导出。组件插件以 zip 包提供入口 ESM，
由浏览器注册 Vue 组件，效果与内置扩展组件一致。

另有**内置扩展组件**（日期、公式、文本绘图、图册、分栏、日历、数据表、待办进度），随前端发布，
可单独启停，并可导出为参考插件包。

组件插件的脚本只由浏览器在用户明确导入并启用后加载；服务端只存储和原样下发，不执行任何插件代码。
历史模板插件记录不再出现在列表与导入入口，也不能新建。

---

## 1. 内置扩展组件与导出

内置组件的停用集合保存在 `system_settings.editor_disabled_extensions`：

- `GET /api/editor/extensions` → `{ items, enabled, disabled }`
- `PUT /api/editor/extensions` → 传完整 `disabled` 集合

停用只移除「+ → 扩展组件」与斜杠菜单入口，正文里已插入的组件继续渲染。

内置组件可导出为**参考插件包**（`kind: "builtin"`）用于对照学习：

- `GET /api/editor/extensions/{key}/export` → 单个组件的 zip
- `GET /api/editor/extensions/export` → 全部内置组件的 zip 集合

导出内容包含 `plugin.json`、`preview.json`、`README.md`，以及在仓库可定位时附带的 `source/*`
源码，例如 `source/gallery.ts`。`kind: "builtin"` 的包只用于参考 / 导出，不是可直接安装的
第三方包；要基于它开发，请改成 `kind: "component"` 并提供自己的入口脚本。

---

## 2. 打包与导入

组件插件**必须**以 `.zip` 交付，JSON manifest 单独上传会被拒绝。

```
my-plugin/
  plugin.json   # kind=component，entry 默认为 index.js
  index.js      # 单文件浏览器 ESM，导出 setup(host)，≤ 2MB
  style.css     # 可选，≤ 512KB
  README.md     # 可选，不参与运行时
```

压缩包内放 `plugin.json` 或 `manifest.json`（可在单一子目录内，但只能有一个）。

限制：

- 插件包 ≤ 5MB，manifest 文件 ≤ 1MB，序列化后的 manifest ≤ 300,000 字符。
- 单个插件最多 50 个区块；`default_props` 序列化后 ≤ 20,000 字符。
- `entry` / `style` 必须是包内相对路径，禁止绝对路径与 `..` 穿越。
- `key` 全局唯一；导入同 key 插件默认返回 `409`，勾选覆盖后原地更新，启用状态保留。
- 导入前 UI 会调用 `POST /api/plugins/inspect` 预检，并明确提示第三方代码执行风险。

---

## 3. manifest 结构

### 3.1 示例

```json
{
  "manifest_version": 1,
  "kind": "component",
  "key": "counter",
  "name": "计数器",
  "version": "1.0.0",
  "description": "可增减的计数卡片",
  "author": "Kiwi",
  "icon": "checkSquare",
  "homepage": "",
  "entry": "index.js",
  "style": "style.css",
  "blocks": [
    {
      "type": "counter",
      "label": "计数器",
      "icon": "checkSquare",
      "description": "插入一个可交互的计数卡片",
      "category": "效率",
      "default_props": { "label": "计数", "count": 0 }
    }
  ],
  "settings": []
}
```

### 3.2 顶层字段

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `manifest_version` | 否 | 当前仅接受 `1` | 缺省为 `1` |
| `kind` | 否 | 固定为 `component` | 其他值会被拒绝 |
| `key` | 是 | `^[a-z0-9][a-z0-9-]{1,63}$` | 全局唯一 slug，创建后不可修改 |
| `name` | 是 | 1–100 字符 | 显示名称 |
| `version` | 否 | ≤ 32 字符，默认 `1.0.0` | 建议 semver |
| `description` | 否 | ≤ 2000 字符 | 简介 |
| `author` | 否 | ≤ 100 字符 | 作者 |
| `icon` | 否 | 内置图标名 | 如 `puzzle`、`list`、`checkSquare`；未知图标回退默认样式 |
| `homepage` | 否 | ≤ 500 字符 | 可选主页地址 |
| `entry` | 否 | 包内相对路径 | 入口 ESM，默认 `index.js` |
| `style` | 否 | 包内相对路径 | 样式文件，可选 |
| `blocks` | 是 | 1–50 项 | 区块定义，`type` 在插件内唯一 |
| `settings` | 否 | — | 预留字段，当前只保存不解释 |

### 3.3 区块字段

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `type` | 是 | `^[a-z0-9][a-z0-9_-]{0,63}$` | 区块类型，插件内唯一；最终标识为 `<key>:<type>` |
| `label` | 是 | 1–80 字符 | 斜杠菜单中的名称 |
| `icon` | 否 | 内置图标名 | 菜单图标，默认 `puzzle` |
| `description` | 否 | ≤ 300 字符 | 斜杠菜单提示 |
| `category` | 否 | ≤ 40 字符，默认 `插件区块` | 斜杠菜单内的分组 |
| `default_props` | 否 | JSON 对象，≤ 20,000 字符 | 组件插入时的默认 props |
| `pinnable` | 否 | 布尔，默认 `false` | 允许把区块置顶为全局浮窗（编辑器工具条、设置页插件卡片、预览弹窗与命令面板均可入口）。适合番茄钟、倒计时等跨页面使用的计时器；分栏卡片等嵌入正文的区块保持关闭 |

`template_markdown` 仅为历史模板记录保留，组件插件请留空。

置顶浮窗的组件状态保存在浮窗自己的 props（localStorage）中，不会回写笔记；窗口可拖动、缩放，关闭后可在编辑器中再次置顶恢复。除编辑器工具条外，也可以在「设置 → 插件与区块」的插件卡片图钉菜单、插件预览弹窗的「置顶」按钮，或 `Ctrl / ⌘ + K` 命令面板中直接置顶，无需先创建 / 插入笔记。重复置顶只会聚焦已有窗口，不会重置正在运行的组件状态。`updateProps` 仍是唯一的交互入口，插件无需为浮窗做额外适配。

`pinnable` 等能力随 manifest 一起安装入库，已有插件需重新导入更新后的包（覆盖安装）才会获得新字段。

---

## 4. 组件插件运行时契约

### 4.1 入口

入口必须是**单文件浏览器 ESM**，不能 import 裸模块（包括 `"vue"`）。所有 Vue API 从
`setup(host)` 获取。`setup` 可以是同步或 async，必须返回区块注册表。

```js
export function setup(host) {
  const { defineComponent, h } = host.vue
  const toast = host.toast // toast.success / toast.error

  const CounterBlock = defineComponent({
    props: {
      blockProps: { type: Object, default: () => ({}) },
      readonly: { type: Boolean, default: false },
      selected: { type: Boolean, default: false },
      updateProps: { type: Function, default: null },
      deleteBlock: { type: Function, default: null },
    },
    setup(props) {
      return () =>
        h(
          'button',
          {
            type: 'button',
            disabled: props.readonly,
            onClick: () => {
              if (props.readonly) return
              const count = Number(props.blockProps?.count) || 0
              props.updateProps?.({ count: count + 1 })
            },
          },
          String(props.blockProps?.count ?? 0),
        )
    },
  })

  return {
    blocks: {
      counter: { component: CounterBlock, defaultProps: { count: 0 } },
    },
  }
}
```

也支持 `export default function setup(host)` 或 `export default { setup }`。
`blocks[type]` 可以是 `{ component, defaultProps }`，也可以直接给 Vue 组件。

### 4.2 host API

| 字段 | 说明 |
|---|---|
| `vue` | Vue 运行时命名空间（`defineComponent` / `h` / `ref` / `computed` 等） |
| `toast` | 全局轻提示：`toast.success(text)` / `toast.error(text)` |
| `theme` | 主题色访问器：`version` / `accent` / `accentStrong` / `accentSoft` / `shade(step, alpha)` |
| `apiVersion` | 宿主 API 版本，当前为 `1` |

### 4.3 主题色

插件涉及颜色展示时，颜色必须跟随系统主题色（「设置 → 外观」与学习模式各自的配色），
不要写死品牌色：

- CSS 优先使用 `--kiwi-*` 变量（RGB 三元组）：

  ```css
  .my-block {
    color: rgb(var(--kiwi-600));
    background: rgb(var(--kiwi-500) / 0.12);
    border-color: rgb(var(--kiwi-500) / 0.4);
  }
  ```

  编辑模式、学习模式与自定义主题色都会自动更新，无需 JS。
- canvas / SVG / 动态内联样式使用 `host.theme`：

  ```js
  const { computed, watch } = host.vue
  const accent = computed(() => host.theme.accent.value)
  // 或 host.theme.shade(400, 0.3)，step 取 50–900，alpha 可选
  watch(host.theme.version, () => redraw())
  ```

  `accent` / `accentStrong` / `accentSoft` 是 computed，主题变化会触发重渲染；
  `theme.version` 在主题切换时自增，适合手动绘制循环。
- 危险 / 成功等语义色可以保留固定色；其余强调色、选中态、进度与描边一律使用主题色。
- 不要在 manifest `default_props` 中保存主题色十六进制值，避免主题切换后配色失真。

### 4.4 组件 props

| prop | 类型 | 说明 |
|---|---|---|
| `blockProps` | `Record<string, unknown>` | manifest `default_props` 与运行时 `defaultProps` 合并后的当前值 |
| `readonly` | `boolean` | 阅读态 / 工作区阅读视图为 `true`，必须禁用交互 |
| `selected` | `boolean` | 编辑器中是否选中 |
| `updateProps` | `(patch) => void` | 浅合并写入 props，并随 Markdown 保存 |
| `deleteBlock` | `() => void` | 删除当前区块 |

约定：

- props 只能通过 `updateProps` 修改，不要直接改写 `blockProps`。
- only-read 场景不要绑定写操作；组件必须在 props 缺失或类型不符时降级渲染。
- 样式使用唯一前缀（如 `.kiwi-counter`），`style.css` 注入全局，避免覆盖编辑器样式。
- 组件不得依赖宿主未承诺的全局变量，不得把不可信内容直接塞进 `v-html`。
- 组件抛出的异常会被宿主捕获并替换为降级卡片，不会导致整篇笔记白屏。

### 4.5 保存格式

组件区块在正文中保存为：

````markdown
```kiwi-plugin
{"plugin":"counter","block":"counter","props":{"label":"计数","count":3},"align":"center"}
```
````

- `align` 为可选的块级水平对齐：`left`（默认，省略不写）/ `center` / `right`。
  插入后选中区块可在浮出的工具条中切换；阅读态与分享占位按同一对齐方式渲染。
  插件组件自身无需处理对齐，也不要写死 `margin` 让区块失去居中能力。
- 数据以 Markdown 为唯一事实来源，可正常导出、搜索、版本管理。
- 插件停用、卸载或加载失败时显示静态降级卡片，props 保留；重新安装同 key 插件后恢复。
- 公开只读分享页不执行第三方脚本，只显示静态占位；工作区阅读视图会加载已启用插件。
- 插件样式与脚本 URL 带版本参数；更新插件后自动失效旧缓存。

### 4.6 安全边界

- 服务端不执行插件脚本，只按 `bundle.js` / `style.css` 原样下发，并设置
  `X-Content-Type-Options: nosniff`。
- 组件插件本质是第三方代码，导入后可在浏览器中访问当前页面数据；只应安装可信来源的插件。
- 删除 / 停用插件不会修改正文，随时可逆。
- 公开分享页与只读嵌入不加载插件运行时，避免把可执行代码暴露给未登录访问者。

---

## 5. HTTP API

所有接口前缀 `/api/plugins`。插件是全局注册表，不按知识库隔离。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/plugins` | 组件插件列表（入口、脚本大小、区块） |
| `GET` | `/api/plugins/blocks` | 仅已启用组件插件的扁平区块列表，编辑器使用 |
| `GET` | `/api/plugins/spec` | 开发规范摘要、组件示例、AI 提示词与 skill 名 |
| `GET` | `/api/plugins/dev-kit` | 开发套件 zip（规范 + counter 示例 + skill + AI 提示词） |
| `POST` | `/api/plugins/inspect` | 解析上传包但不落库，返回导入预检信息 |
| `POST` | `/api/plugins/import?overwrite=false` | multipart 导入 zip（不接受裸 JSON） |
| `GET` | `/api/plugins/{id}` | 插件详情 |
| `PATCH` | `/api/plugins/{id}` | 更新元数据、`enabled` 或整体替换 `blocks` |
| `GET` | `/api/plugins/{id}/bundle.js` | 组件入口脚本（停用状态也可访问，供预览） |
| `GET` | `/api/plugins/{id}/style.css` | 组件样式（无样式时 404） |
| `GET` | `/api/plugins/{id}/export` | 导出插件 zip（可再次导入） |
| `DELETE` | `/api/plugins/{id}` | 删除插件（204） |

校验失败返回 `400`（JSON / 压缩包无法解析、非组件插件、路径非法、体积超限）。

### 示例

```bash
# 预检（不落库）
curl -F "file=@counter.zip" http://localhost:8001/api/plugins/inspect

# 导入并允许覆盖
curl -X POST 'http://localhost:8001/api/plugins/import?overwrite=true' \
  -F 'file=@counter.zip'

# 导出
curl -OJ http://localhost:8001/api/plugins/<id>/export
```

---

## 6. 预览、导入、导出

| 能力 | 位置 | 说明 |
|---|---|---|
| 效果预览 | 设置页插件卡片 → 眼睛按钮 | 按默认 props 挂载真实运行时，交互只改本地副本 |
| 置顶为全局浮窗 | 插件卡片 → 图钉菜单 / 预览弹窗「置顶」/ `Ctrl / ⌘ + K` | 仅列出 `pinnable: true` 的区块；无需创建或插入笔记，浮窗跨路由保留 |
| 导入预检 | 顶部「导入插件」 | 先解析并展示 key / 区块 / 入口，显示代码执行警告；确认后才落库 |
| 单插件导出 | 插件卡片 → 下载按钮 | 生成可再次导入的 zip，含 manifest、入口脚本、样式与 README |
| 内置组件导出 | 内置区每个组件的下载按钮 | 生成参考包（manifest + 预览数据 + 源码） |
| 全部内置导出 | 内置区「全部导出」 | 所有内置组件参考包集合 |

---

## 7. 让大模型辅助开发

仓库内置 skill：`.claude/skills/kiwi-plugin/SKILL.md`。把开发套件（或本文件 + 示例插件 +
skill）交给支持 skill 的大模型，即可按同一契约生成插件包。

- 开发套件：`GET /api/plugins/dev-kit`
- 规范摘要中的 `skill` / `ai_prompt`：`GET /api/plugins/spec`
- 推荐提示词：

  > 使用 kiwi-plugin skill 为 Kiwi 开发一个组件插件。先阅读 docs/PLUGIN_SPEC.md 与
  > docs/examples/plugins/（counter 最小示例、pomodoro / countdown 计时器示例），
  > 生成可直接压缩为 zip 的 plugin.json、入口 ESM 与可选
  > style.css；入口必须导出 setup(host)，且只使用 host.vue / host.toast / host.theme，
  > 颜色需跟随系统主题色。完成后用 `/api/plugins/inspect` 与导入接口验证 manifest。

生成后务必先在预检接口和设置页预览中验证，再插入真实笔记。

---

## 8. 对现有系统的影响

插件能力是增量扩展，主要影响面与回退策略见 [`docs/PLUGIN_IMPACT.md`](PLUGIN_IMPACT.md)，摘要：

- 新迁移只新增 `plugins.kind/entry/script/style` 列；旧模板记录保留在库中但不再展示，
  不执行破坏性数据迁移。
- 组件区块使用统一节点 `kiwiPluginBlock`，安装任意插件都不需要改编辑器 schema。
- 插件运行时按需加载；失败、停用、卸载均降级为静态卡片，正文不丢。
- 公开分享页不执行插件代码；`/media` 等既有边界不变。
- 停用内置组件与停用插件互不影响；编辑器菜单、主题与自动保存逻辑不变。

---

## 9. 本地开发流程

1. 复制 `docs/examples/plugins/counter/`，修改 manifest 与入口脚本；计时 / 持久化交互
   可参考 `pomodoro/` 与 `countdown/`。
2. 压缩为 zip；先调用 `POST /api/plugins/inspect` 预检。
3. 在 **设置 → 插件与区块 → 导入插件** 导入，确认风险提示后自动打开预览。
4. 打开任意文档，输入 `/`，在「插件区块」分组插入并验证交互 / 持久化。
5. 调整后重新打包并勾选覆盖导入；导出 zip 可验证往返。
6. 仓库内完整示例与规范：

   - `docs/examples/plugins/counter/`
   - `docs/examples/plugins/pomodoro/`
   - `docs/examples/plugins/countdown/`
   - `.claude/skills/kiwi-plugin/SKILL.md`
   - `GET /api/plugins/dev-kit`
