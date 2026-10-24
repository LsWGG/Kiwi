---
name: kiwi-plugin
description: 为 Kiwi 编辑器开发、检查、打包或修复组件插件，包括 plugin.json、setup(host) ESM、主题色、样式、预览与导入验证。
---

# Kiwi 组件插件开发

Kiwi 只支持**组件插件**（`kind: "component"`），通过「设置 → 插件与区块」以 zip 导入。
组件插件注册真实 Vue 组件区块，效果与内置扩展组件一致。

完整规范以仓库 `docs/PLUGIN_SPEC.md` 为准；可运行样例在
`docs/examples/plugins/`：

- `counter/`：最小可运行计数器，适合首次上手；
- `pomodoro/`：番茄钟，演示时间戳持久化、阶段切换、`host.toast` 与定时器清理；
- `countdown/`：倒计时，演示预设、进度条与 `@container` 窄容器适配。

## 交付物

组件插件 zip（≤ 5MB）：

```
my-plugin/
  plugin.json     # manifest，必须
  index.js        # 入口 ESM（entry 默认 index.js），≤ 2MB
  style.css       # 可选（style 指向它），≤ 512KB
  README.md       # 可选
```

必须以 `.zip` 交付；单独上传 JSON manifest 会被拒绝。

## manifest 字段

```json
{
  "manifest_version": 1,
  "kind": "component",
  "key": "my-plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "description": "一句话说明",
  "author": "",
  "icon": "puzzle",
  "homepage": "",
  "entry": "index.js",
  "style": "style.css",
  "blocks": [
    {
      "type": "my-block",
      "label": "我的区块",
      "icon": "puzzle",
      "description": "斜杠菜单提示",
      "category": "插件区块",
      "default_props": {}
    }
  ],
  "settings": []
}
```

约束：

- `key`：`^[a-z0-9][a-z0-9-]{1,63}$`，全局唯一，发布后不可改。
- `blocks[].type`：`^[a-z0-9][a-z0-9_-]{0,63}$`，插件内唯一；正文标识为 `<key>:<type>`。
- 最多 50 个区块；单个 `default_props` 序列化后 ≤ 20,000 字符；manifest 序列化后 ≤ 300,000 字符。
- `entry` / `style` 必须是 zip 内的相对路径，不能是绝对路径或包含 `..`。
- 至少一个区块；`kind` 必须为 `component`。
- `icon` 使用 Kiwi 内置图标名（如 `puzzle`、`checkSquare`、`calendar`、`table`）。

规范示例可用 `GET /api/plugins/spec` 获取（`examples.component`）。

## 组件入口契约

入口必须是**单文件浏览器 ESM**，不能 import 裸模块（包括 `"vue"`）。Vue API 全部来自
`setup(host)` 的参数：

```js
export function setup(host) {
  const { defineComponent, h } = host.vue
  const toast = host.toast // toast.success / toast.error

  const Block = defineComponent({
    props: {
      blockProps: { type: Object, default: () => ({}) },
      readonly: { type: Boolean, default: false },
      selected: { type: Boolean, default: false },
      updateProps: { type: Function, default: null },
      deleteBlock: { type: Function, default: null },
    },
    setup(props) {
      return () => h('div', String(props.blockProps.count || 0))
    },
  })

  return {
    blocks: {
      'my-block': {
        component: Block,
        defaultProps: { count: 0 },
      },
    },
  }
}
```

`setup` 可以是 async，返回 `{ blocks }`；也可以直接返回以 type 为键的注册表。

### host API

| 字段 | 说明 |
|---|---|
| `vue` | Vue 运行时命名空间（`defineComponent` / `h` / `ref` / `computed` 等） |
| `toast` | 全局轻提示：`toast.success(text)` / `toast.error(text)` |
| `theme` | 主题色访问器：`version` / `accent` / `accentStrong` / `accentSoft` / `shade(step, alpha)` |
| `apiVersion` | 宿主 API 版本，当前为 `1` |

### 主题色（必须遵循）

插件涉及颜色展示时，颜色必须跟随「设置 → 外观」中的系统主题色，不要写死品牌色：

- CSS 优先使用 `--kiwi-*` 变量（RGB 三元组）：
  `color: rgb(var(--kiwi-600))`、`background: rgb(var(--kiwi-500) / 0.12)`。
  编辑模式、学习模式与自定义主题色都会自动生效，无需 JS。
- canvas / SVG / 动态内联样式使用 `host.theme`：
  `host.theme.accent.value`、`accentStrong`、`accentSoft`，
  或 `host.theme.shade(400, 0.3)`（50–900 档，alpha 可选）。
  这些值是 computed，主题变化会自动重渲染；在手动绘制循环里可
  `watch(host.theme.version, redraw)`。
- 危险 / 成功等语义色可保留固定色，其余强调色一律走主题变量；中性底色可用 `--kiwi-50` 等。
- 禁止在 manifest `default_props` 里保存十六进制主题色，避免主题切换后配色失真。

### 组件 props

| prop | 类型 | 说明 |
|---|---|---|
| `blockProps` | `Record<string, unknown>` | 区块数据：manifest 的 `default_props` 与运行时注册的 `defaultProps` 合并，之后由 `updateProps` 更新 |
| `readonly` | `boolean` | 阅读态 / 工作区阅读视图为 `true`，必须禁用交互 |
| `selected` | `boolean` | 编辑器中是否选中 |
| `updateProps` | `(patch) => void` | 浅合并写入 props，并随 Markdown 保存 |
| `deleteBlock` | `() => void` | 删除当前区块 |

注意：

- props 只能通过 `updateProps` 修改，不要直接改写 `blockProps`。
- 只读模式下不要调用 `updateProps` / `deleteBlock`，也不要绑定会触发写操作的快捷键。
- 组件必须能在 props 为空或类型不符时降级渲染，不能抛异常导致整篇笔记白屏。
- 组件样式使用带插件前缀的类名；`style.css` 会注入全局，避免覆盖编辑器通用样式。
- 不要依赖 `window` 上未约定的全局变量；不要渲染 `<script>` / `v-html` 注入的不可信内容。

## 数据与生命周期

- 正文中的组件保存为围栏：

  ````markdown
  ```kiwi-plugin
  {"plugin":"my-plugin","block":"my-block","props":{"count":3}}
  ```
  ````

- 插件停用、卸载或加载失败时，编辑器渲染静态降级卡片，props 仍保留在 Markdown 中；
  重新安装同 key 插件后自动恢复渲染。
- 公开只读分享页**不执行**第三方脚本，只显示静态占位；工作区阅读视图会执行已启用插件。
- 样式按插件注入；重新导入 / 更新版本时脚本和样式 URL 带缓存参数自动刷新。

## 开发流程

1. 复制 `docs/examples/plugins/counter/` 作为起点；需要计时、持久化交互时参考
   `pomodoro/` 与 `countdown/`。
2. 修改 `plugin.json`、`index.js`、`style.css`；保持类名前缀唯一。
3. 压缩为 zip（`plugin.json` 可在 zip 根目录或单一子目录内）：

   ```bash
   cd my-plugin && zip -r ../my-plugin.zip .
   ```

4. 预检 manifest 与包结构（不落库）：

   ```bash
   curl -F "file=@my-plugin.zip" http://127.0.0.1:8011/api/plugins/inspect
   ```

5. 在「设置 → 插件与区块 → 导入插件」确认风险提示后导入，导入成功会自动打开效果预览。
6. 在编辑器用 `/区块名` 或工具栏「+ → 插件区块」插入，验证：
   - 交互与 props 更新；刷新 / 重新打开笔记后状态保留；
   - 阅读视图只读行为；
   - 停用插件后降级卡片与数据保留；
   - 从设置页导出 zip，再次导入可往返。
7. 运行前端 `vue-tsc -b --noEmit` 与后端相关测试（若改动了仓库代码）。

## 参考

- 完整规范：`docs/PLUGIN_SPEC.md`
- 示例插件：`docs/examples/plugins/counter/`、`pomodoro/`、`countdown/`
- 内置组件导出包：设置页「内置扩展组件 → 导出」，或在 `GET /api/editor/extensions/{key}/export`
  下载参考 manifest / 预览数据 / 源码。
- 开发套件：`GET /api/plugins/dev-kit`（含本 skill、规范与示例）。
- 影响面与安全边界：`docs/PLUGIN_IMPACT.md`。
