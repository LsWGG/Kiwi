import type { Page } from '@playwright/test'
import { test, expect, openWorkspace } from './fixtures'

/**
 * 桌面构建离线断言。
 *
 * 桌面版承诺默认不发起任何外网请求。这里监听页面的全部请求（含子 iframe 与
 * 资源），任何非 loopback 的 http(s) 请求都判失败；远程字体、favicon、图片、
 * YouTube 与网页嵌入都会出现在请求事件中，因此不需要逐个资源类型枚举。
 *
 * 用例使用 `vite --mode desktop`（见 playwright.config.ts 的 desktop 项目），
 * 与 `npm run build:desktop` 同样加载 .env.desktop，并移除 Google Fonts。
 */

function isLoopbackHost(hostname: string): boolean {
  let host = hostname.toLowerCase()
  if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1)
  if (host === 'localhost' || host === '::1') return true
  if (host.endsWith('.localhost')) return true
  return /^127(?:\.\d{1,3}){3}$/.test(host)
}

interface ExternalRequest {
  url: string
  resourceType: string
}

/** 记录所有非 loopback 请求；返回的数组在断言时为空才通过。 */
function watchExternalRequests(page: Page): ExternalRequest[] {
  const requests: ExternalRequest[] = []
  page.on('request', (request) => {
    const url = request.url()
    if (!/^https?:/i.test(url)) return
    let parsed: URL
    try {
      parsed = new URL(url)
    } catch {
      return
    }
    if (isLoopbackHost(parsed.hostname)) return
    requests.push({ url, resourceType: request.resourceType() })
  })
  return requests
}

function describeRequests(requests: ExternalRequest[]): string {
  return requests.map((item) => `${item.resourceType} ${item.url}`).join('\n')
}

test.describe('桌面离线构建', () => {
  test('工作区与设置页不发起外网请求，远程内容显示占位', async ({
    page,
    kb,
    notesApi,
  }) => {
    const external = watchExternalRequests(page)

    const note = await notesApi.createNote({
      title: 'E2E 桌面离线内容',
      body_md: [
        '# 桌面离线',
        '',
        '普通正文段落。',
        '',
        '![远程图片](https://example.com/remote-image.png)',
        '',
        '![youtube](https://www.youtube.com/watch?v=dQw4w9WgXcQ)',
        '',
        '```kiwi-embed',
        JSON.stringify({
          kind: 'link',
          url: 'https://example.com/article',
          title: '外部网页',
          site: 'example.com',
          favicon: 'https://example.com/favicon.ico',
          display: 'web',
        }),
        '```',
        '',
        '```kiwi-gallery',
        JSON.stringify({
          images: [
            { url: 'https://example.com/gallery-1.png', caption: '远程图册' },
          ],
          columns: 3,
          layout: 'grid',
        }),
        '```',
        '',
      ].join('\n'),
    })

    await openWorkspace(page, kb.id, `/notes/${note.id}`)
    await expect(page.locator('html.kiwi-desktop')).toHaveCount(1)
    await expect(page.locator('.ProseMirror').first()).toContainText('普通正文段落')

    // 编辑态：远程图片与图册使用本地占位，不创建 <img>。
    await expect(page.locator('[data-external-blocked="image"]')).toBeVisible()
    await expect(page.locator('.kiwi-gallery-blocked')).toBeVisible()
    await expect(page.getByText('桌面版已禁用外部视频嵌入')).toBeVisible()
    await expect(page.getByText('外部网页嵌入已禁用')).toBeVisible()
    await expect(page.locator('img[src^="https://"]')).toHaveCount(0)
    await expect(page.locator('iframe[src^="http"]')).toHaveCount(0)

    // 阅读态复用只读编辑器，仍使用同一批桌面占位节点，不创建远程 iframe。
    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    const reading = page.locator('.kiwi-editor.is-readonly').first()
    await expect(reading).toBeVisible()
    await expect(reading.getByText('桌面版已禁用外部视频嵌入')).toBeVisible()
    await expect(reading.getByText('外部网页嵌入已禁用')).toBeVisible()
    await expect(reading.getByText('外部图片已禁用').first()).toBeVisible()
    await expect(page.locator('img[src^="https://"]')).toHaveCount(0)
    await expect(page.locator('iframe[src^="http"]')).toHaveCount(0)

    // 桌面设置与模型设置页：桌面路由与开关正常渲染，且仍不请求外部资源。
    await page.goto('/settings/desktop')
    await expect(page.getByRole('heading', { name: '桌面', exact: true })).toBeVisible()
    await page.goto('/settings/models?tab=embedding')
    await expect(page.getByRole('heading', { name: '模型配置' })).toBeVisible()
    await expect(page.getByText('桌面版未内置向量模型')).toBeVisible()

    // 页面中没有指向远程主机的字体、图标或 iframe 引用。
    await expect(page.locator('link[href*="fonts.googleapis.com"]')).toHaveCount(0)
    await expect(page.locator('link[href*="fonts.gstatic.com"]')).toHaveCount(0)
    await expect(page.locator('img[src^="https://"]')).toHaveCount(0)
    await expect(page.locator('iframe[src^="http"]')).toHaveCount(0)

    expect(
      external,
      `桌面构建不应发起外网请求：\n${describeRequests(external)}`,
    ).toEqual([])
  })
})
