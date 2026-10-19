/** 目录树通用类型。 */
import type { NoteFolder, NoteSummary } from '@/stores/notes'

export interface TreeRow {
  type: 'folder' | 'note'
  id: string
  depth: number
  folder?: NoteFolder
  note?: NoteSummary
  /** 置顶的「收件箱」分组，使用独立配色。 */
  inbox?: boolean
  /** 置顶区中的副本；原目录仍保留同一项，用该标记避免高亮 / 选中落到副本上。 */
  hoisted?: boolean
  /** 在此行上方渲染一条分割线（用于隔开置顶收件箱与普通目录）。 */
  separatorBefore?: boolean
  /** 笔记下存在子笔记：显示展开箭头。 */
  hasChildren?: boolean
}

export type DropPos = 'before' | 'after' | 'into'
