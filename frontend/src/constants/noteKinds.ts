/**
 * 可创建笔记类型的统一元数据：目录树、空态按钮与命令面板共用，
 * 避免新建菜单与 Ctrl/⌘+K 的标题 / 图标出现两套口径。
 */
export type CreatableNoteKind = 'doc' | 'database' | 'sheet' | 'canvas' | 'notebook'

export interface NoteCreateOption {
  kind: CreatableNoteKind
  /** 无需「新建」前缀的短名称，例如「文档」 */
  label: string
  icon: string
  title: string
  keywords: string[]
}

export const NOTE_CREATE_OPTIONS: NoteCreateOption[] = [
  {
    kind: 'doc',
    label: '文档',
    icon: 'fileText',
    title: '无标题文档',
    keywords: ['doc', 'document', 'note', 'markdown', '文本'],
  },
  {
    kind: 'database',
    label: '数据表',
    icon: 'database',
    title: '无标题数据表',
    keywords: ['database', 'table', 'collection', '记录', '看板'],
  },
  {
    kind: 'sheet',
    label: '表格',
    icon: 'table',
    title: '无标题表格',
    keywords: ['sheet', 'excel', 'spreadsheet', '工作簿', '单元格'],
  },
  {
    kind: 'canvas',
    label: '画布',
    icon: 'pen',
    title: '无标题画布',
    keywords: ['canvas', 'diagram', 'mindmap', '思维导图', '白板'],
  },
  {
    kind: 'notebook',
    label: 'Notebook',
    icon: 'notebook',
    title: '无标题 Notebook',
    keywords: ['notebook', 'code', 'python', '代码', '笔记本'],
  },
]

export const NOTE_CREATE_TITLES = Object.fromEntries(
  NOTE_CREATE_OPTIONS.map((option) => [option.kind, option.title]),
) as Record<CreatableNoteKind, string>
