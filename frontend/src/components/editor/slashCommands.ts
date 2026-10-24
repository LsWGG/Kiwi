/** Slash 命令：输入 / 唤起的块插入菜单（自绘浮层，无额外依赖）。 */
import { Extension, type Editor } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import Suggestion from '@tiptap/suggestion'
import { iconSVG } from '@/components/ui/icons'
import type { PluginBlock } from '@/stores/plugins'

/** @tiptap/suggestion 默认共用一个 PluginKey，多个 Suggestion 同时启用会冲突。 */
const slashCommandKey = new PluginKey('slashCommand')

export interface SlashItem {
  title: string
  hint: string
  icon: string
  keywords: string
  /** 菜单分组标题 */
  group: string
  /** 内置扩展组件 key；在「插件与区块」停用后隐藏 */
  extension?: string
  run: (editor: Editor) => void
}

export interface SlashActions {
  onImage: () => void
  onAttachment: () => void
  onLink: (editor: Editor) => void
  onVideo: (editor: Editor) => void
  onYoutube: (editor: Editor) => void
  /** 打开行/列设置弹窗，确认后插入表格 */
  onTable: (editor: Editor) => void
  /** 打开来源选择弹窗，插入带指纹与跳转的引用块 */
  onSourceQuote: (editor: Editor) => void
  /** 打开知识点选择弹窗，插入学习笔记关联块 */
  onKnowledgePoint: (editor: Editor) => void
  /** 在光标处插入今天的日期胶囊 */
  onDate: () => void
  /** 打开 AI 指令栏（续写 / 缩写 / 润色 / 知识库解释） */
  onAI: () => void
  /** 已启用插件提供的区块（在菜单构建时读取，插件启停无需重建编辑器） */
  pluginBlocks?: () => PluginBlock[]
  /** 插入插件区块的 Markdown 模板 */
  onPluginBlock?: (editor: Editor, block: PluginBlock) => void
  /** 内置扩展组件是否启用（设置 → 插件与区块） */
  extensionEnabled?: (key: string) => boolean
}

export function buildSlashItems(
  actions: SlashActions,
  options: { inTable?: boolean; inDetails?: boolean } = {},
): SlashItem[] {
  const c = (editor: Editor) => editor.chain().focus()
  const headings = [1, 2, 3, 4, 5, 6].map((level) => ({
    title: `标题 ${level}`,
    hint: `${'一二三四五六'[level - 1]}级标题`,
    icon: 'hash',
    keywords: `h${level} heading title 标题 ${level}`,
    group: '基础块',
    run: (e: Editor) =>
      c(e)
        .toggleHeading({ level: level as 1 | 2 | 3 | 4 | 5 | 6 })
        .run(),
  }))
  const alignments: SlashItem[] = [
    {
      title: '左对齐',
      hint: '段落左对齐',
      icon: 'arrowLeft',
      keywords: 'align left 对齐 左对齐',
      group: '对齐',
      run: (e) => c(e).setTextAlign('left').run(),
    },
    {
      title: '居中',
      hint: '段落居中',
      icon: 'target',
      keywords: 'align center 对齐 居中',
      group: '对齐',
      run: (e) => c(e).setTextAlign('center').run(),
    },
    {
      title: '右对齐',
      hint: '段落右对齐',
      icon: 'arrowRight',
      keywords: 'align right 对齐 右对齐',
      group: '对齐',
      run: (e) => c(e).setTextAlign('right').run(),
    },
    {
      title: '两端对齐',
      hint: '段落两端对齐',
      icon: 'columns',
      keywords: 'align justify 对齐 两端对齐',
      group: '对齐',
      run: (e) => c(e).setTextAlign('justify').run(),
    },
  ]
  // 光标位于表格内时才展示行列/单元格操作
  const tableOps: SlashItem[] = options.inTable
    ? [
        {
          title: '上方插入行',
          hint: '在当前行上方新增一行',
          icon: 'plus',
          keywords: 'row add above 行 插入',
          group: '表格操作',
          run: (e) => c(e).addRowBefore().run(),
        },
        {
          title: '下方插入行',
          hint: '在当前行下方新增一行',
          icon: 'plus',
          keywords: 'row add below 行 插入',
          group: '表格操作',
          run: (e) => c(e).addRowAfter().run(),
        },
        {
          title: '左侧插入列',
          hint: '在当前列左侧新增一列',
          icon: 'columns',
          keywords: 'column add left 列 插入',
          group: '表格操作',
          run: (e) => c(e).addColumnBefore().run(),
        },
        {
          title: '右侧插入列',
          hint: '在当前列右侧新增一列',
          icon: 'columns',
          keywords: 'column add right 列 插入',
          group: '表格操作',
          run: (e) => c(e).addColumnAfter().run(),
        },
        {
          title: '删除当前行',
          hint: '删除光标所在行',
          icon: 'minus',
          keywords: 'row delete remove 行 删除',
          group: '表格操作',
          run: (e) => c(e).deleteRow().run(),
        },
        {
          title: '删除当前列',
          hint: '删除光标所在列',
          icon: 'minus',
          keywords: 'column delete remove 列 删除',
          group: '表格操作',
          run: (e) => c(e).deleteColumn().run(),
        },
        {
          title: '合并单元格',
          hint: '合并选中的单元格',
          icon: 'table',
          keywords: 'merge cell 合并 单元格',
          group: '表格操作',
          run: (e) => c(e).mergeCells().run(),
        },
        {
          title: '拆分单元格',
          hint: '拆分当前合并单元格',
          icon: 'expand',
          keywords: 'split cell 拆分 单元格',
          group: '表格操作',
          run: (e) => c(e).splitCell().run(),
        },
        {
          title: '删除表格',
          hint: '移除整个表格',
          icon: 'trash',
          keywords: 'table delete remove 表格 删除',
          group: '表格操作',
          run: (e) => c(e).deleteTable().run(),
        },
      ]
    : []
  // 光标位于折叠块内时才展示折叠操作
  const detailsOps: SlashItem[] = options.inDetails
    ? [
        {
          title: '展开 / 收起',
          hint: '切换当前折叠块的显示状态',
          icon: 'chevron',
          keywords: 'toggle details collapse 折叠 展开 收起',
          group: '折叠操作',
          run: (e) => c(e).toggleDetailsOpen().run(),
        },
        {
          title: '解除折叠',
          hint: '保留内容并移除外框',
          icon: 'trash',
          keywords: 'unset details remove 解除 折叠',
          group: '折叠操作',
          run: (e) => c(e).unsetDetails().run(),
        },
      ]
    : []
  // 插件区块由后端注册表下发；停用插件后下一次打开菜单即消失。
  const pluginItems: SlashItem[] =
    actions.onPluginBlock && actions.pluginBlocks
      ? actions.pluginBlocks().map((block) => ({
          title: block.label,
          hint: block.description || `${block.plugin_name} · ${block.category}`,
          icon: block.icon || 'puzzle',
          keywords: `plugin block 插件 区块 ${block.plugin_name} ${block.category} ${block.type}`,
          group: '插件区块',
          run: (e: Editor) => actions.onPluginBlock?.(e, block),
        }))
      : []
  const items: SlashItem[] = [
    {
      title: '正文',
      hint: '普通段落',
      icon: 'file',
      keywords: 'text paragraph 正文 段落',
      group: '基础块',
      run: (e) => c(e).setParagraph().run(),
    },
    ...headings,
    {
      title: '无序列表',
      hint: '项目符号列表',
      icon: 'list',
      keywords: 'bullet list ul 列表',
      group: '基础块',
      run: (e) => c(e).toggleBulletList().run(),
    },
    {
      title: '有序列表',
      hint: '编号列表',
      icon: 'listOrdered',
      keywords: 'ordered list ol 列表 编号',
      group: '基础块',
      run: (e) => c(e).toggleOrderedList().run(),
    },
    {
      title: '任务列表',
      hint: '可勾选的待办项',
      icon: 'checkSquare',
      keywords: 'todo task checkbox 任务 待办',
      group: '基础块',
      run: (e) => c(e).toggleTaskList().run(),
    },
    {
      title: '引用',
      hint: '引用段落',
      icon: 'quote',
      keywords: 'quote blockquote 引用',
      group: '基础块',
      run: (e) => c(e).toggleBlockquote().run(),
    },
    {
      title: '提示块',
      hint: '带图标的强调卡片',
      icon: 'alert',
      keywords: 'callout tip info notice 提示 高亮块 强调',
      group: '高级块',
      run: (e) => c(e).toggleCallout().run(),
    },
    {
      title: '代码块',
      hint: '带语法高亮',
      icon: 'code',
      keywords: 'code block 代码',
      group: '程序员专区',
      run: (e) => c(e).toggleCodeBlock().run(),
    },
    {
      title: '公式',
      hint: 'KaTeX 数学公式，实时预览',
      icon: 'hash',
      keywords: 'formula math latex katex 公式 数学',
      group: '程序员专区',
      extension: 'formula',
      run: (e) => c(e).insertFormula().run(),
    },
    {
      title: '文本绘图',
      hint: 'Mermaid 流程图 / 时序图 / 类图',
      icon: 'graph',
      keywords: 'mermaid diagram flowchart uml 绘图 流程图 时序图 类图',
      group: '程序员专区',
      extension: 'mermaid',
      run: (e) => c(e).insertMermaid().run(),
    },
    {
      title: '折叠块',
      hint: '可展开 / 收起的标题与内容',
      icon: 'chevron',
      keywords: 'details toggle collapse 折叠 展开',
      group: '高级块',
      run: (e) => c(e).insertDetails().run(),
    },
    {
      title: '分栏卡片 · 2 栏',
      hint: '左右并排的富文本卡片',
      icon: 'columns',
      keywords: 'columns layout grid 分栏 卡片 布局 两栏',
      group: '布局与样式',
      extension: 'columns2',
      run: (e) => c(e).insertColumns({ count: 2 }).run(),
    },
    {
      title: '分栏卡片 · 3 栏',
      hint: '三栏并排的富文本卡片',
      icon: 'columns',
      keywords: 'columns layout grid 分栏 卡片 布局 三栏',
      group: '布局与样式',
      extension: 'columns3',
      run: (e) => c(e).insertColumns({ count: 3 }).run(),
    },
    {
      title: '表格',
      hint: '设置行列数后插入',
      icon: 'table',
      keywords: 'table grid rows cols 表格 行 列',
      group: '高级块',
      run: (e) => actions.onTable(e),
    },
    {
      title: '来源引用',
      hint: '引用素材原文，带指纹与原文跳转',
      icon: 'quote',
      keywords: 'source quote citation 来源 引用 素材 溯源',
      group: '高级块',
      run: (e) => actions.onSourceQuote(e),
    },
    {
      title: '关联知识点',
      hint: '把这段笔记关联到学习知识点',
      icon: 'target',
      keywords: 'knowledge topic study 知识点 学习 关联 复习',
      group: '高级块',
      run: (e) => actions.onKnowledgePoint(e),
    },
    {
      title: 'AI 助手',
      hint: '续写 / 缩写 / 润色 / 总结 / 基于知识库解释',
      icon: 'sparkle',
      keywords: 'ai assist continue shorten polish summarize translate explain 续写 缩写 润色 总结 翻译 解释',
      group: '高级块',
      run: () => actions.onAI(),
    },
    {
      title: '分割线',
      hint: '水平分隔',
      icon: 'columns',
      keywords: 'divider hr 分割线',
      group: '高级块',
      run: (e) => c(e).setHorizontalRule().run(),
    },
    {
      title: '图片',
      hint: '上传并插入图片',
      icon: 'image',
      keywords: 'image picture upload 图片 上传',
      group: '媒体与嵌入',
      run: () => actions.onImage(),
    },
    {
      title: '图册',
      hint: '多图上传，网格 / 滑动展示与大图预览',
      icon: 'gallery',
      keywords: 'gallery album images photo 图册 相册 多图 图片',
      group: '媒体与嵌入',
      extension: 'gallery',
      run: (e) => c(e).insertGallery().run(),
    },
    {
      title: '视频',
      hint: '嵌入 mp4 / webm 视频',
      icon: 'video',
      keywords: 'video movie media 视频 影片',
      group: '媒体与嵌入',
      run: (e) => actions.onVideo(e),
    },
    {
      title: 'YouTube',
      hint: '嵌入 YouTube 视频',
      icon: 'video',
      keywords: 'youtube video embed 油管 视频',
      group: '媒体与嵌入',
      run: (e) => actions.onYoutube(e),
    },
    {
      title: '附件',
      hint: '上传文件并插入链接',
      icon: 'paperclip',
      keywords: 'file attachment upload 附件 文件',
      group: '媒体与嵌入',
      run: () => actions.onAttachment(),
    },
    {
      title: '链接',
      hint: '插入外部链接',
      icon: 'link2',
      keywords: 'link url 链接',
      group: '媒体与嵌入',
      run: (e) => actions.onLink(e),
    },
    {
      title: '日期',
      hint: '插入可点击修改的日期胶囊',
      icon: 'calendar',
      keywords: 'date calendar today 日期 日历 今天',
      group: '小工具',
      extension: 'date',
      run: () => actions.onDate(),
    },
    {
      title: '日历',
      hint: '月视图，可为日期添加安排',
      icon: 'calendar',
      keywords: 'calendar month schedule 日历 月历 日程 安排',
      group: '小工具',
      extension: 'calendar',
      run: (e) => c(e).insertCalendar().run(),
    },
    {
      title: '待办进度',
      hint: '绑定附近任务清单，实时统计完成度',
      icon: 'checkSquare',
      keywords: 'progress task todo checklist 进度 待办 任务 完成度',
      group: '小工具',
      extension: 'taskProgress',
      run: (e) => c(e).insertTaskProgress().run(),
    },
    {
      title: '数据表',
      hint: '可增删行列、批量粘贴的表格',
      icon: 'table',
      keywords: 'datatable grid spreadsheet 数据表 表格 行列',
      group: '高级块',
      extension: 'datatable',
      run: (e) => c(e).insertDataTable().run(),
    },
    {
      title: '提及',
      hint: '输入 @ 引用笔记或 Wiki 页面',
      icon: 'at',
      keywords: 'mention at note wiki 提及 引用 笔记 知识页',
      group: '行内组件',
      run: (e) => c(e).insertContent('@').run(),
    },
    {
      title: '表情',
      hint: '输入 : 选择表情，或用 :smile: 转换',
      icon: 'smile',
      keywords: 'emoji smile 表情 颜文字',
      group: '行内组件',
      run: (e) => c(e).insertContent(':').run(),
    },
    ...alignments,
    ...detailsOps,
    ...tableOps,
    ...pluginItems,
  ]
  // 内置扩展组件被停用后，斜杠菜单与工具栏「扩展组件」同步隐藏。
  const extensionEnabled = actions.extensionEnabled
  return extensionEnabled
    ? items.filter((item) => !item.extension || extensionEnabled(item.extension))
    : items
}

function escapeHtml(text: string) {
  return text.replace(/[&<>"']/g, (ch) => {
    const map: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }
    return map[ch]
  })
}

function makeSvg(name: string) {
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${iconSVG(name)}</svg>`
}

function renderer() {
  // el 是 fixed 定位的外层，挂到 <html> 下，避开 body 的 4K zoom；
  // box 承担视觉样式并随 --ui-scale 缩放。
  let el: HTMLDivElement | null = null
  let box: HTMLDivElement | null = null
  let items: SlashItem[] = []
  let index = 0
  let pick: ((item: SlashItem) => void) | null = null
  let getRect: (() => DOMRect | null) | null = null

  const caretRect = (): DOMRect | null => {
    const sel = window.getSelection()
    if (!sel || !sel.rangeCount) return null
    const rect = sel.getRangeAt(0).getBoundingClientRect()
    return rect.width || rect.height ? rect : null
  }

  const paint = () => {
    if (!box) return
    const groups: { name: string; entries: { item: SlashItem; i: number }[] }[] = []
    items.forEach((item, i) => {
      let group = groups.find((g) => g.name === item.group)
      if (!group) {
        group = { name: item.group || '其他', entries: [] }
        groups.push(group)
      }
      group.entries.push({ item, i })
    })
    box.innerHTML = groups
      .map(
        (group) =>
          `<div class="slash-group">` +
          `<div class="slash-group-title">${escapeHtml(group.name)}</div>` +
          group.entries
            .map(
              ({ item, i }) =>
                `<button type="button" data-i="${i}" class="slash-item${i === index ? ' is-active' : ''}">` +
                `<span class="slash-icon">${makeSvg(item.icon)}</span>` +
                `<span class="slash-text"><span class="slash-title">${escapeHtml(item.title)}</span>` +
                `<span class="slash-hint">${escapeHtml(item.hint)}</span></span></button>`,
            )
            .join('') +
          `</div>`,
      )
      .join('')
    box.querySelector<HTMLElement>('.slash-item.is-active')?.scrollIntoView({ block: 'nearest' })
  }

  const position = (rect?: DOMRect | null) => {
    if (!el || !box) return
    const anchor = rect ?? getRect?.() ?? caretRect()
    if (!anchor) return
    // 读取实际渲染尺寸（含 --ui-scale 缩放），避免写死 270 / 360 导致边缘溢出
    const boxRect = box.getBoundingClientRect()
    const width = boxRect.width || 270
    const height = Math.min(boxRect.height || 300, window.innerHeight - 16)
    let top = anchor.bottom + 6
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, anchor.top - height - 6)
    }
    const left = Math.min(
      Math.max(8, anchor.left),
      Math.max(8, window.innerWidth - width - 8),
    )
    el.style.top = `${top}px`
    el.style.left = `${left}px`
  }

  /** 滚动 / 缩放窗口时菜单跟随光标 */
  const reflow = () => position()

  return {
    onStart: (props: any) => {
      items = props.items ?? []
      index = 0
      pick = props.command
      getRect = typeof props.clientRect === 'function' ? props.clientRect : null
      el = document.createElement('div')
      el.className = 'slash-menu'
      el.addEventListener('mousedown', (e) => e.preventDefault())
      el.addEventListener('click', (e) => {
        const btn = (e.target as HTMLElement).closest('[data-i]') as HTMLElement | null
        if (!btn) return
        const i = Number(btn.dataset.i)
        if (Number.isInteger(i)) pick?.(items[i])
      })
      box = document.createElement('div')
      box.className = 'slash-menu-box'
      el.appendChild(box)
      document.documentElement.appendChild(el)
      window.addEventListener('scroll', reflow, true)
      window.addEventListener('resize', reflow)
      paint()
      position(props.clientRect?.() ?? null)
    },
    onUpdate: (props: any) => {
      items = props.items ?? []
      index = 0
      pick = props.command
      getRect = typeof props.clientRect === 'function' ? props.clientRect : null
      paint()
      position(props.clientRect?.() ?? null)
    },
    onKeyDown: (props: any) => {
      if (!items.length) return false
      if (props.event.key === 'ArrowDown') {
        index = (index + 1) % items.length
        paint()
        return true
      }
      if (props.event.key === 'ArrowUp') {
        index = (index - 1 + items.length) % items.length
        paint()
        return true
      }
      if (props.event.key === 'Enter' || props.event.key === 'Tab') {
        pick?.(items[index])
        return true
      }
      return false
    },
    onExit: () => {
      window.removeEventListener('scroll', reflow, true)
      window.removeEventListener('resize', reflow)
      el?.remove()
      el = null
      box = null
      getRect = null
    },
  }
}

export function createSlashCommand(actions: SlashActions) {
  return Extension.create({
    name: 'slashCommand',
    addProseMirrorPlugins() {
      return [
        Suggestion({
          editor: this.editor,
          pluginKey: slashCommandKey,
          char: '/',
          allowSpaces: false,
          startOfLine: false,
          items: ({ query, editor }: any) =>
            buildSlashItems(actions, {
              inTable: !!editor?.isActive('table'),
              inDetails: !!editor?.isActive('details'),
            }).filter((item) =>
              `${item.title} ${item.keywords} ${item.group}`
                .toLowerCase()
                .includes(String(query).toLowerCase()),
            ),
          command: ({ editor, range, props }: any) => {
            editor.chain().focus().deleteRange(range).run()
            props.run(editor)
          },
          render: renderer,
        }) as any,
      ]
    },
  })
}
