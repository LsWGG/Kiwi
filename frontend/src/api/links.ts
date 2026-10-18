/** 链接元信息：编辑器插入链接卡片时只抓标题 / 站点 / 摘要，不生成正文。 */
import { request } from './client'

export interface LinkMeta {
  url: string
  final_url: string
  title: string
  site: string
  excerpt: string
  favicon: string
  fetch_status: 'ok' | 'failed'
  error: string | null
}

export function fetchLinkMeta(url: string, kbId?: string | null): Promise<LinkMeta> {
  return request<LinkMeta>('/notes/link/meta', {
    method: 'POST',
    body: JSON.stringify({ url }),
    kbId,
  })
}
