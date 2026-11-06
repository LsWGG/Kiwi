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
    // 画布编辑宿主与 jvs-draw 画布就绪后再继续导出。
    await expect(page.locator('.kiwi-draw-editor')).toBeVisible()
    await expect(page.locator('.kiwi-draw-editor canvas').first()).toBeVisible({
      timeout: 60_000,
    })
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

  test('内嵌画布预览支持缩放、拖拽且不出现滚动条', async ({ page, kb, notesApi }) => {
    const shape = {
      angle: 0,
      strokeColor: '#475569',
      backgroundColor: '#dbeafe',
      fillStyle: 'solid',
      strokeWidth: 2,
      strokeStyle: 'solid',
      strokeOpacity: 100,
      roughness: 1,
      roundness: 10,
      isDeleted: false,
    }
    const drawDoc = {
      type: 'jvs-draw',
      version: 1,
      elements: [
        { ...shape, id: 'start', type: 'rectangle', x: 40, y: 40, width: 180, height: 60 },
        { ...shape, id: 'end', type: 'rectangle', x: 330, y: 330, width: 180, height: 60 },
        {
          ...shape,
          id: 'arrow',
          type: 'arrow',
          x: 130,
          y: 100,
          width: 200,
          height: 260,
          points: [
            [0, 0],
            [200, 260],
          ],
          arrowType: 'elbow',
          startArrowhead: null,
          endArrowhead: 'arrow',
          startBinding: { elementId: 'start' },
          endBinding: { elementId: 'end' },
        },
        // 撑高内容，确保预览区需要缩放 / 拖拽查看。
        { ...shape, id: 'tall', type: 'rectangle', x: 40, y: 420, width: 500, height: 400 },
      ],
      appState: { viewBackgroundColor: '#ffffff' },
      files: {},
      updatedAt: Date.now(),
    }
    const note = await notesApi.createNote({
      title: 'E2E 内嵌画布预览',
      body_md: ['```kiwi-draw', JSON.stringify(drawDoc), '```'].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const block = page.locator('.kiwi-draw-block').first()
    const view = block.locator('.kiwi-draw-view')
    // 预览与画布 / 导出图片使用同一套 jvs-draw 渲染器，先等它替换静态 SVG。
    const image = block.locator('.kiwi-draw-image')
    await expect(image).toBeVisible({ timeout: 120_000 })

    // 100% 时整张画布完整放进预览框，底部和右侧都不截断。
    await expect(view).not.toHaveClass(/is-pannable/)
    const fit = await view.evaluate((el) => {
      const media = el.querySelector('.kiwi-draw-image, .kiwi-draw-svg svg')
      const viewRect = el.getBoundingClientRect()
      const mediaRect = media?.getBoundingClientRect()
      return {
        overflowX: getComputedStyle(el).overflowX,
        overflowY: getComputedStyle(el).overflowY,
        scrollbar: el.offsetWidth - el.clientWidth,
        overflowing: el.scrollHeight > el.clientHeight + 1,
        inside:
          !!mediaRect &&
          mediaRect.top >= viewRect.top - 1 &&
          mediaRect.left >= viewRect.left - 1 &&
          mediaRect.bottom <= viewRect.bottom + 1 &&
          mediaRect.right <= viewRect.right + 1,
      }
    })
    expect(fit).toMatchObject({
      overflowX: 'hidden',
      overflowY: 'hidden',
      scrollbar: 0,
      overflowing: false,
      inside: true,
    })

    // 放大后内容超出预览框，不出现滚动条，改用拖拽平移。
    const zoomLabel = block.locator('.kiwi-draw-zoom')
    await expect(zoomLabel).toHaveText('100%')
    await block.locator('.kiwi-draw-action[title="放大预览"]').click()
    await expect(zoomLabel).toHaveText('110%')
    await expect(view).toHaveClass(/is-pannable/)
    const scaled = await view.evaluate((el) => ({
      overflowing: el.scrollHeight > el.clientHeight + 1,
      scrollbar: el.offsetWidth - el.clientWidth,
    }))
    expect(scaled).toMatchObject({ overflowing: true, scrollbar: 0 })

    // 拖拽平移内容，且不会误进入编辑态。
    const box = await view.boundingBox()
    if (!box) throw new Error('预览区不可见')
    const cx = box.x + box.width / 2
    const cy = box.y + Math.min(box.height - 24, 240)
    await page.mouse.move(cx, cy)
    await page.mouse.down()
    await page.mouse.move(cx, cy - 120, { steps: 10 })
    await page.mouse.up()
    await expect.poll(() => view.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
    await expect(block).not.toHaveClass(/is-editing/)

    // 点击百分比恢复完整显示。
    await zoomLabel.click()
    await expect(zoomLabel).toHaveText('100%')
    await expect(view).not.toHaveClass(/is-pannable/)
  })
})
