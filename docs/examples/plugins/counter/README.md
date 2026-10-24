# 计数器（组件插件示例）

一个最小但完整的 Kiwi 组件插件：插入后可增减、重置计数，props 随 Markdown 保存。

## 包结构

```
counter/
  plugin.json   # manifest：kind=component、entry、blocks[].default_props
  index.js      # 单文件 ESM，导出 setup(host)
  style.css     # 可选，加载插件时注入
  README.md
```

## 安装

1. 将本目录压缩为 zip（`plugin.json` 可直接位于 zip 根目录）：

   ```bash
   cd docs/examples/plugins/counter
   zip -r ../counter.zip .
   ```

2. 打开「设置 → 插件与区块 → 导入插件」，选择 zip。
3. 导入前会先预检并提示第三方代码执行风险，确认后插件默认启用。
4. 在编辑器中输入 `/计数器`，或从工具栏「+ → 插件区块」插入。

## 运行时约定

`index.js` 只与宿主暴露的 API 交互：

```js
export function setup(host) {
  const { defineComponent, h } = host.vue
  // host.toast.success(...) 可用于轻提示
  return {
    blocks: {
      counter: {
        component: CounterBlock,
        defaultProps: { label: '计数', count: 0 },
      },
    },
  }
}
```

组件收到的 props：

| prop | 说明 |
|---|---|
| `blockProps` | 当前区块数据，来自 `default_props` + 用户操作 |
| `readonly` | 阅读态 / 分享页为 `true`，应禁用交互 |
| `selected` | 区块在编辑器中是否被选中 |
| `updateProps(patch)` | 合并写入 props，内容随 Markdown 保存 |
| `deleteBlock()` | 删除当前区块 |

- 不能 `import "vue"`；所有 Vue API 从 `host.vue` 获取。
- 不要访问 DOM 之外的敏感数据，不要发起未声明的网络请求。
- 停用 / 卸载插件后，区块会降级为静态卡片，Markdown 中的 props 不丢失。

## 主题色

插件涉及颜色展示时必须跟随系统主题色，而不是写死品牌色：

- 纯 CSS 场景直接使用 `--kiwi-*` 变量（RGB 三元组），例如
  `color: rgb(var(--kiwi-600))`、`background: rgb(var(--kiwi-500) / 0.12)`。
  系统切换主题色或进入学习模式时会自动更新，无需额外监听。
- canvas / SVG 等需要在 JS 中取色的场景，使用 `host.theme`：
  `host.theme.accent.value`、`accentStrong`、`accentSoft`、`shade(600, 0.2)`；
  这些 computed 已依赖主题版本，主题变化会自动触发重渲染。若在 `watch` /
  手动绘制循环中使用，可监听 `host.theme.version`。
- `--kiwi-50` 至 `--kiwi-900` 均可用；语义色（危险 / 成功）可保留固定色。
- 示例 `style.css` 已全部改用主题变量，切换主题色即可看到效果。

## 开发与验证

```bash
# 仅做 manifest 预检，不落库
curl -F "file=@counter.zip" http://127.0.0.1:8011/api/plugins/inspect

# 导入
curl -F "file=@counter.zip" http://127.0.0.1:8011/api/plugins/import
```

也可以在「设置 → 插件与区块」中导出任意已安装插件，对照其 zip 结构。
更多规范见仓库根目录 `docs/PLUGIN_SPEC.md` 与 `.claude/skills/kiwi-plugin/SKILL.md`。
