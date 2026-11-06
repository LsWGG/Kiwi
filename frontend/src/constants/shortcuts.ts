/** 全局快捷键面板的展示数据。新增交互时同步维护，避免文档与实际行为脱节。 */
export interface ShortcutItem {
  /** 按键组合，直接展示在 kbd 标签中 */
  keys: string
  label: string
  /** 补充说明，例如生效范围 */
  hint?: string
}

export interface ShortcutGroup {
  id: string
  title: string
  icon: string
  items: ShortcutItem[]
}

export const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    id: 'global',
    title: '全局',
    icon: 'keyboard',
    items: [
      { keys: 'Ctrl / Cmd + K', label: '打开命令面板（笔记搜索 / 新建 / 导航 / 置顶插件）', hint: '任意业务页面' },
      { keys: 'Ctrl / Cmd + Shift + P', label: '打开命令面板并只看命令', hint: '输入框自动预填 >' },
      { keys: 'Ctrl / Cmd + F', label: '在当前笔记中查找', hint: '文本笔记为页内查找，画布笔记为图形搜索' },
      { keys: 'Ctrl / Cmd + I', label: '显示 / 隐藏笔记信息', hint: '焦点不在正文编辑器时' },
      { keys: 'Ctrl / Cmd + Shift + Space', label: '快速捕获' },
      { keys: 'Ctrl / Cmd + S', label: '立即保存当前笔记' },
      { keys: '?', label: '打开 / 关闭本快捷键面板', hint: '输入框中不触发' },
      { keys: 'Esc', label: '关闭弹窗、菜单或浮层' },
    ],
  },
  {
    id: 'editor',
    title: '文档编辑器',
    icon: 'edit',
    items: [
      { keys: 'Ctrl / Cmd + B', label: '加粗' },
      { keys: 'Ctrl / Cmd + I', label: '斜体' },
      { keys: 'Ctrl / Cmd + U', label: '下划线' },
      { keys: 'Ctrl / Cmd + Shift + S', label: '删除线' },
      { keys: 'Ctrl / Cmd + E', label: '行内代码' },
      { keys: 'Ctrl / Cmd + Shift + H', label: '高亮' },
      { keys: 'Ctrl / Cmd + Alt + 1 … 6', label: '一级至六级标题' },
      { keys: 'Ctrl / Cmd + Alt + 0', label: '正文段落' },
      { keys: 'Ctrl / Cmd + Shift + 7', label: '有序列表' },
      { keys: 'Ctrl / Cmd + Shift + 8', label: '无序列表' },
      { keys: 'Ctrl / Cmd + Shift + 9', label: '任务列表' },
      { keys: 'Ctrl / Cmd + Shift + B', label: '引用块' },
      { keys: 'Ctrl / Cmd + Shift + L', label: '左对齐' },
      { keys: 'Ctrl / Cmd + Shift + E', label: '居中对齐' },
      { keys: 'Ctrl / Cmd + Shift + R', label: '右对齐' },
      { keys: 'Ctrl / Cmd + Shift + J', label: '两端对齐' },
      { keys: 'Ctrl / Cmd + Z', label: '撤销' },
      { keys: 'Ctrl / Cmd + Shift + Z', label: '重做', hint: '也可使用 Ctrl + Y' },
      { keys: 'Tab / Shift + Tab', label: '列表缩进 / 减少缩进', hint: '表格中切换下一 / 上一单元格' },
      { keys: 'Shift + Enter', label: '软换行（不分段）' },
      { keys: 'Ctrl / Cmd + Enter', label: '插入分页符' },
      { keys: 'Ctrl / Cmd + Shift + C', label: '复制当前格式（格式刷）' },
      { keys: 'Ctrl / Cmd + Shift + V', label: '应用已复制的格式', hint: '未复制格式时为无格式粘贴' },
      { keys: 'Esc', label: '取消格式刷、关闭弹出菜单' },
    ],
  },
  {
    id: 'canvas',
    title: '画布',
    icon: 'pen',
    items: [
      { keys: 'V / 1', label: '选择工具' },
      { keys: 'H', label: '抓手（平移画布）' },
      { keys: 'K / 2', label: '激光笔' },
      { keys: 'R / 3', label: '形状' },
      { keys: 'L / 4', label: '连线' },
      { keys: 'A / 5', label: '箭头' },
      { keys: 'N / 6', label: '便签' },
      { keys: 'P / 7', label: '画笔' },
      { keys: 'T / 8', label: '文本' },
      { keys: 'I / 9', label: '图片' },
      { keys: 'E / 0', label: '橡皮擦' },
      { keys: 'Space + 拖动', label: '平移画布' },
      { keys: 'Ctrl / Cmd + 滚轮', label: '缩放画布', hint: '可在画布偏好设置中改为滚轮直接缩放' },
      { keys: 'Ctrl / Cmd + +', label: '放大' },
      { keys: 'Ctrl / Cmd + -', label: '缩小' },
      { keys: 'Ctrl / Cmd + 0', label: '重置缩放' },
      { keys: 'Ctrl / Cmd + F', label: '搜索画布中的图形与文字', hint: '仅画布笔记；文本笔记仍为页内查找' },
      { keys: 'Ctrl / Cmd + A', label: '全选图形' },
      { keys: 'Delete', label: '删除选中内容' },
      { keys: 'Ctrl / Cmd + C / V / X', label: '复制 / 粘贴 / 剪切' },
      { keys: 'Ctrl / Cmd + Z', label: '撤销' },
      { keys: 'Ctrl / Cmd + Shift + Z', label: '重做' },
      { keys: 'Ctrl / Cmd + G', label: '成组' },
      { keys: 'Ctrl / Cmd + Shift + G', label: '取消成组' },
      { keys: '] / [', label: '置于顶层 / 置于底层' },
      { keys: 'Alt / Option + ] / [', label: '上移一层 / 下移一层' },
      { keys: 'Esc', label: '取消选择 / 退出当前工具' },
    ],
  },
  {
    id: 'notebook',
    title: 'Notebook',
    icon: 'notebook',
    items: [
      { keys: 'Shift + Enter', label: '运行并跳到下一格', hint: '最后一格会自动新建' },
      { keys: 'Ctrl / Cmd + Enter', label: '运行并停留在当前格' },
      { keys: 'Alt + Enter', label: '运行并在下方插入新格' },
      { keys: 'Esc', label: '离开编辑，进入命令模式' },
      { keys: '↑ / ↓', label: '命令模式：选择上一格 / 下一格' },
      { keys: 'Enter', label: '命令模式：编辑选中格' },
      { keys: 'A / B', label: '命令模式：在上方 / 下方插入代码格' },
      { keys: 'M / Y', label: '命令模式：切换为 Markdown / 代码' },
      { keys: 'D D', label: '命令模式：删除选中格', hint: '两次 D 需连续按下' },
      { keys: 'Tab / Shift + Tab', label: '代码格内增加 / 减少缩进' },
      { keys: 'Ctrl / Cmd + /', label: '代码格内注释 / 取消注释选中行' },
    ],
  },
  {
    id: 'reading',
    title: '阅读与预览',
    icon: 'bookOpen',
    items: [
      { keys: 'Esc', label: '退出沉浸阅读模式' },
      { keys: 'Esc', label: '取消正在进行的批注或激光笔' },
      { keys: 'Esc', label: '关闭反向链接、图片大图或预览层' },
      { keys: '← / →', label: '画册大图中切换上一张 / 下一张' },
      { keys: 'Ctrl / Cmd + S', label: '保存当前笔记', hint: '阅读模式下同样生效' },
    ],
  },
  {
    id: 'search',
    title: '命令面板与快速捕获',
    icon: 'search',
    items: [
      { keys: '↑ / ↓', label: '在命令与笔记结果中上下选择' },
      { keys: 'Enter', label: '执行命令 / 打开选中的笔记' },
      { keys: '>', label: '仅查看命令，不触发笔记检索', hint: '在输入框开头输入' },
      { keys: 'Esc', label: '关闭命令面板' },
      { keys: 'Enter / Shift + Enter', label: '页内查找：下一处 / 上一处' },
      { keys: 'F3 / Shift + F3', label: '页内查找：下一处 / 上一处', hint: '查找条打开时' },
      { keys: 'Esc', label: '关闭页内查找并清除高亮' },
      { keys: 'Enter', label: '快速捕获：在标题框保存' },
      { keys: 'Ctrl / Cmd + Enter', label: '快速捕获：在正文框保存' },
    ],
  },
  {
    id: 'database',
    title: '数据表',
    icon: 'table',
    items: [
      { keys: 'Enter', label: '提交单元格并结束编辑' },
      { keys: 'Ctrl / Cmd + Enter', label: '多行文本单元格保存' },
      { keys: 'Esc', label: '关闭行详情或弹窗' },
    ],
  },
]
