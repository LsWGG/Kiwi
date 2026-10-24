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
      { keys: 'Ctrl / Cmd + F', label: '在当前笔记中查找', hint: '笔记工作区；Enter / Shift+Enter 切换命中' },
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
      { keys: 'V', label: '选择工具' },
      { keys: 'H', label: '平移工具' },
      { keys: 'R', label: '矩形' },
      { keys: 'O', label: '椭圆' },
      { keys: 'D', label: '菱形 / 判断' },
      { keys: 'T', label: '文本' },
      { keys: 'S', label: '便签' },
      { keys: 'C', label: 'UML 类图' },
      { keys: 'B', label: '库表' },
      { keys: 'A', label: '连线' },
      { keys: 'Space + 拖动', label: '平移画布' },
      { keys: 'Ctrl / Cmd + 滚轮', label: '以指针为中心缩放' },
      { keys: 'Ctrl / Cmd + +', label: '放大' },
      { keys: 'Ctrl / Cmd + -', label: '缩小' },
      { keys: 'Ctrl / Cmd + 0', label: '适应画布' },
      { keys: 'Ctrl / Cmd + Z', label: '撤销' },
      { keys: 'Ctrl / Cmd + Shift + Z', label: '重做', hint: '也可使用 Ctrl + Y' },
      { keys: 'Ctrl / Cmd + D', label: '复制选中节点' },
      { keys: 'Ctrl / Cmd + A', label: '全选节点' },
      { keys: 'Delete / Backspace', label: '删除选中内容' },
      { keys: 'Esc', label: '取消选择并回到选择工具' },
      { keys: 'Enter', label: '编辑选中节点的文字' },
      { keys: 'Tab', label: '为选中节点添加子节点' },
      { keys: '↑ / ↓ / ← / →', label: '移动节点 1px', hint: '按住 Shift 每次移动 10px' },
      { keys: '] / [', label: '上移 / 下移一层', hint: '加 Shift 置顶 / 置底' },
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
