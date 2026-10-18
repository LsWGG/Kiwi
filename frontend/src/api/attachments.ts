/** 附件上传：数据表附件字段使用 any_type 允许任意文件类型。 */
import { upload } from './client'

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
): Promise<UploadedAttachment> {
  const form = new FormData()
  form.append('file', file)
  const query = new URLSearchParams({ any_type: 'true' })
  if (noteId) query.set('note_id', noteId)
  return upload<UploadedAttachment>(`/attachments?${query.toString()}`, form, kbId)
}
