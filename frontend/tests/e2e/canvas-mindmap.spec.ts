import { readFileSync } from 'node:fs'
import { test, expect, openWorkspace } from './fixtures'

test.describe('画布增强', () => {
  test('大纲生成思维导图并导出 PNG / PDF', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 大纲文档',
      body_md: '# 系统设计\n\n## 召回层\n\n### 向量召回\n\n## 评测\n\n### 离线指标\n',
    })
    const docUrl = `/notes/${note.id}`
    await openWorkspace(page, kb.id, docUrl)

    const row = page.locator(`[data-tree-row="note:${note.id}"]`)
    await expect(row).toBeVisible()
    await row.click({ button: 'right' })
    await page.getByRole('button', { name: '生成思维导图', exact: true }).click()

    // 生成后自动打开新画布；等待路由真正切走，避免旧文档地址立即满足正则。
    await expect.poll(() => page.url()).not.toContain(docUrl)
    // 画布有多个 .canvas-ui 浮层（标题、缩放、提示），取第一个即可确认已进入画布。
    await expect(page.locator('.canvas-ui').first()).toBeVisible()
    await expect(page.locator('input[placeholder="无标题画布"]')).toHaveValue(
      'E2E 大纲文档 · 思维导图',
    )
    const canvasId = page.url().split('/notes/')[1]

    const canvasRow = page.locator(`[data-tree-row="note:${canvasId}"]`)
    await canvasRow.click({ button: 'right' })
    const pngDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: 'PNG 图片' }).click()
    const png = await pngDownload
    expect(png.suggestedFilename()).toContain('.png')
    const pngPath = await png.path()
    if (!pngPath) throw new Error('PNG 下载文件不可读')
    const pngBytes = readFileSync(pngPath)
    expect(pngBytes.subarray(0, 4).toString('latin1')).toBe('\x89PNG')

    await canvasRow.click({ button: 'right' })
    const pdfDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: 'PDF 文档' }).click()
    const pdf = await pdfDownload
    expect(pdf.suggestedFilename()).toContain('.pdf')
    const pdfPath = await pdf.path()
    if (!pdfPath) throw new Error('PDF 下载文件不可读')
    const pdfBytes = readFileSync(pdfPath)
    expect(pdfBytes.subarray(0, 5).toString('latin1')).toBe('%PDF-')
  })
})
