/** 触发浏览器下载笔记的 Word / PDF 导出（后端统一生成）。 */
async function downloadNoteFile(
  noteId: string,
  kbId: string | null,
  format: 'docx' | 'pdf',
  filename: string,
  headers: Record<string, string> = {},
): Promise<void> {
  const res = await fetch(
    `/api/notes/${noteId}/export/${format}?kb_id=${encodeURIComponent(kbId ?? '')}`,
    { headers },
  )
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error((detail as any)?.detail || res.statusText || '导出失败')
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function downloadTitle(title: string): string {
  return (title || '无标题文档').trim() || '无标题文档'
}

export async function downloadNoteDocx(
  noteId: string,
  kbId: string | null,
  title: string,
  headers: Record<string, string> = {},
): Promise<void> {
  await downloadNoteFile(
    noteId,
    kbId,
    'docx',
    `${downloadTitle(title)}.docx`,
    headers,
  )
}

export async function downloadNotePdf(
  noteId: string,
  kbId: string | null,
  title: string,
  headers: Record<string, string> = {},
): Promise<void> {
  await downloadNoteFile(
    noteId,
    kbId,
    'pdf',
    `${downloadTitle(title)}.pdf`,
    headers,
  )
}
