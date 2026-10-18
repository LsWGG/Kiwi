/** Notebook 文档结构：保存在 note.props_json.notebook_doc，与 `.ipynb` 可互转。 */

export type NotebookCellType = 'code' | 'markdown'

export interface NotebookImage {
  mime: string
  /** base64，不含 data: 前缀 */
  data: string
}

export interface NotebookOutput {
  type: 'stream' | 'error' | 'execute_result' | 'display_data'
  name?: 'stdout' | 'stderr'
  text?: string
  html?: string
  image?: NotebookImage
}

export interface NotebookCell {
  id: string
  type: NotebookCellType
  source: string
  execution_count?: number | null
  outputs?: NotebookOutput[]
}

export interface NotebookDoc {
  version: number
  language: string
  cells: NotebookCell[]
}

export function newCellId(): string {
  try {
    return `cell-${crypto.randomUUID().slice(0, 12)}`
  } catch {
    return `cell-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
  }
}

export function newCell(type: NotebookCellType, source = ''): NotebookCell {
  const cell: NotebookCell = { id: newCellId(), type, source }
  if (type === 'code') {
    cell.execution_count = null
    cell.outputs = []
  }
  return cell
}

export function emptyNotebook(): NotebookDoc {
  return {
    version: 1,
    language: 'python',
    cells: [
      newCell(
        'markdown',
        [
          '## 未命名 Notebook',
          '',
          '在这里记录分析思路，代码单元格中可以直接使用 `pandas`、`numpy`、`matplotlib` 等项目依赖。',
          '',
          '- 需要新依赖：`%pip install 包名` 或 `%uv pip install 包名`（沙箱已开启网络）',
          '- 执行 shell：`!ls`、`!pwd`；整段脚本可用 `%%bash`',
          '- 快捷键：`Shift+Enter` 运行并跳转，`Ctrl+Enter` 运行并停留，`Alt+Enter` 运行并插入',
        ].join('\n'),
      ),
      newCell('code', "print('Hello, Kiwi!')"),
    ],
  }
}

/** 容忍旧数据 / 手工编辑：过滤未知结构，保证单元格 id 唯一。 */
export function normalizeNotebook(raw: unknown): NotebookDoc {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, any>) : {}
  const seen = new Set<string>()
  const cells: NotebookCell[] = []
  if (Array.isArray(source.cells)) {
    for (const item of source.cells) {
      if (!item || typeof item !== 'object') continue
      const type: NotebookCellType = item.type === 'code' ? 'code' : 'markdown'
      let id = String(item.id || '').trim()
      if (!id || seen.has(id)) id = newCellId()
      seen.add(id)
      const cell: NotebookCell = {
        id,
        type,
        source: String(item.source ?? ''),
      }
      if (type === 'code') {
        cell.execution_count =
          typeof item.execution_count === 'number' ? item.execution_count : null
        cell.outputs = Array.isArray(item.outputs)
          ? item.outputs
              .filter((output: unknown) =>
                output && typeof output === 'object' && typeof (output as any).type === 'string',
              )
              .map((output: any) => ({ ...output }))
          : []
      }
      cells.push(cell)
    }
  }
  return {
    version: 1,
    language: typeof source.language === 'string' && source.language ? source.language : 'python',
    cells: cells.length ? cells : emptyNotebook().cells,
  }
}

export function countCodeCells(doc: NotebookDoc): number {
  return doc.cells.filter((cell) => cell.type === 'code').length
}
