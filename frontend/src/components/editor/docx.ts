/** 触发浏览器下载笔记的 Word 导出（后端 python-docx 生成）。 */
export async function downloadNoteDocx(
  noteId: string,
  kbId: string | null,
  title: string,
): Promise<void> {
  const res = await fetch(
    `/api/notes/${noteId}/export/docx?kb_id=${encodeURIComponent(kbId ?? '')}`,
  )
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error((detail as any)?.detail || res.statusText || '导出失败')
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(title || '无标题文档').trim() || '无标题文档'}.docx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
