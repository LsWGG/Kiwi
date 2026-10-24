import { test, expect, openWorkspace } from './fixtures'

// 只复制 iPhone 13 的视口/触控参数，避免 devices 里的 defaultBrowserType
// 把用例切到未安装的 WebKit 内核。
test.use({
  viewport: { width: 390, height: 664 },
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
  userAgent:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1',
})

test.describe('移动端笔记工作区', () => {

  test('目录改为抽屉，信息面板覆盖正文且不溢出视口', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 移动笔记',
      body_md: '# 移动端\n\n窄屏正文。',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const row = page.locator(`[data-tree-row="note:${note.id}"]`)
    await expect(row).toBeHidden()

    await page.locator('button[title="打开目录"]').click()
    await expect(row).toBeVisible()
    await page.locator('button[title="关闭目录"]').click()
    await expect(row).toBeHidden()

    await page.locator('button[title="笔记信息（Ctrl/⌘ + I）"]').click()
    const panel = page.locator('.note-info-panel')
    await expect(panel).toBeVisible()
    const box = await panel.boundingBox()
    if (!box) throw new Error('信息面板不可见')
    expect(box.width).toBeLessThanOrEqual(320)
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  })
})
