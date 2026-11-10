/** 附件上传：数据表附件字段使用 any_type 允许任意文件类型。 */
import { uploadWithProgress, type UploadProgressHandler } from './client'

export interface UploadedAttachment {
  id: string
  kb_id: string
  note_id: string | null
  filename: string
  content_type: string
  size: number
  url: string
  created_at: string
}

export function uploadAttachment(
  file: File,
  noteId: string | null,
  kbId: string | null,
  onProgress?: UploadProgressHandler,
  signal?: AbortSignal,
): Promise<UploadedAttachment> {
  const form = new FormData()
  form.append('file', file)
  const query = new URLSearchParams({ any_type: 'true' })
  if (noteId) query.set('note_id', noteId)
  return uploadWithProgress<UploadedAttachment>(
    `/attachments?${query.toString()}`,
    form,
    kbId,
    onProgress,
    signal,
  )
}

/** 压缩包版 Markdown 解析结果；found=false 表示包内没有 md，应按普通附件处理。 */
export interface MdBundleResult {
  found: boolean
  title: string
  markdown: string
  main_entry: string
  attachments: UploadedAttachment[]
  warnings: string[]
  rewritten_refs: number
}

/** 上传「md + 图片 / 附件目录」压缩包：资源落盘为附件并返回重写后的 Markdown。 */
export function importMdBundle(
  file: File,
  noteId: string | null,
  kbId: string | null,
): Promise<MdBundleResult> {
  const form = new FormData()
  form.append('file', file)
  const query = new URLSearchParams()
  if (noteId) query.set('note_id', noteId)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return uploadWithProgress<MdBundleResult>(
    `/attachments/md-bundle${suffix}`,
    form,
    kbId,
  )
}
