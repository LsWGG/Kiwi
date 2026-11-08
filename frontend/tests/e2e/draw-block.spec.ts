import { test, expect, openWorkspace } from './fixtures'

const DRAW_DOC = {
  type: 'jvs-draw',
  version: 1,
  elements: [
    {
      id: 'rect-1',
      type: 'rectangle',
      x: 80,
      y: 80,
      width: 220,
      height: 110,
      angle: 0,
      strokeColor: '#475569',
      backgroundColor: '#e0f2fe',
      fillStyle: 'solid',
      strokeWidth: 2,
      strokeStyle: 'solid',
      roughness: 1,
      opacity: 100,
      roundness: { type: 3 },
      isDeleted: false,
      boundElements: [{ type: 'text', id: 'rect-1-text' }],
    },
    {
      id: 'rect-1-text',
      type: 'text',
      x: 92,
      y: 122,
      width: 196,
      height: 26,
      text: '静态渲染节点',
      originalText: '静态渲染节点',
      containerId: 'rect-1',
      angle: 0,
      fontSize: 16,
      fontColor: '#0c4a6e',
      textAlign: 'center',
      verticalAlign: 'middle',
      backgroundColor: 'transparent',
      isDeleted: false,
    },
    {
      id: 'arrow-1',
      type: 'arrow',
      x: 300,
      y: 135,
      width: 140,
      height: 1,
      points: [
        [0, 0],
        [140, 0],
      ],
      startArrowhead: null,
      endArrowhead: 'arrow',
      arrowType: 'sharp',
      strokeColor: '#64748b',
      backgroundColor: 'transparent',
      isDeleted: false,
    },
  ],
  appState: { viewBackgroundColor: '#ffffff' },
  files: {},
  updatedAt: Date.now(),
}

test.describe('画布块', () => {
  test('斜杠插入画布，绘制文字后保存并回显', async ({ page, kb, notesApi }) => {
    // 其他用例可能关闭过扩展，先恢复默认。
    await page.request.put('/api/editor/extensions', { data: { disabled: [] } })
    const note = await notesApi.createNote({ title: 'E2E 画布块', body_md: '画布上一段正文' })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()
    await editor.click()
    await page.keyboard.press('Control+End')
    await page.keyboard.press('Enter')
    await page.keyboard.type('/')
    const slashItem = page.locator('.slash-menu').getByText('画布', { exact: true })
    await expect(slashItem).toBeVisible({ timeout: 10_000 })
    await slashItem.click()

    const block = page.locator('.kiwi-draw-block').first()
    await expect(block).toBeVisible()
    await expect(block).toContainText('点击开始绘制')

    // 空画布点开后加载 jvs-draw 白板（懒加载，首次较慢）。
    await block.locator('.kiwi-draw-view').click()
    await expect(block.locator('.kiwi-draw-editor canvas').first()).toBeVisible({
      timeout: 60_000,
    })

    // 用「文本」工具在画布上写一段字，Esc 提交后应回写文档。
    const canvas = block.locator('.kiwi-draw-editor canvas').first()
    const box = await canvas.boundingBox()
    if (!box) throw new Error('画布不可见')
    await block.locator('.toolbar .tool-item[title="文本"]').click()
    await page.mouse.click(box.x + box.width * 0.35, box.y + box.height * 0.65)
    await page.keyboard.type('E2E 画布文本')
    await page.keyboard.press('Escape')

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
      .toContain('E2E 画布文本')
    const saved = (await notesApi.getNote(note.id)).body_md
    expect(saved).toContain('```kiwi-draw')
    expect(saved).toContain('画布上一段正文')

    // 完成编辑后回到预览：编辑态会异步升级为高保真 PNG，
    // 因此断言画布容器内有渲染结果（静态 SVG 或 PNG 均可）。
    await block.getByRole('button', { name: '完成' }).click()
    await expect(block.locator('.kiwi-draw-canvas svg, .kiwi-draw-canvas img').first()).toBeVisible()
    await expect(page.locator('.kiwi-draw-block')).toHaveCount(1)

    await page.reload()
    const reloaded = page.locator('.kiwi-draw-block').first()
    await expect(
      reloaded.locator('.kiwi-draw-canvas svg, .kiwi-draw-canvas img').first(),
    ).toBeVisible()
  })

  test('阅读态与分享页用静态 SVG 渲染画布围栏', async ({ page, kb, notesApi }) => {
    const fence = ['```kiwi-draw', JSON.stringify(DRAW_DOC), '```'].join('\n')
    const note = await notesApi.createNote({
      title: 'E2E 画布阅读',
      body_md: `# 画布预览\n\n${fence}\n\n画布下方正文`,
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    // 阅读态是只读编辑器：画布块直接回放静态 SVG。
    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    const readonlySvg = page.locator('.ProseMirror .kiwi-draw-block.is-readonly .kiwi-draw-svg svg').first()
    await expect(readonlySvg).toBeVisible()
    await expect(readonlySvg).toContainText('静态渲染节点')
    await expect(readonlySvg.locator('.kiwi-draw-arrowhead')).toHaveCount(1)
    await expect(page.locator('.ProseMirror')).toContainText('画布下方正文')

    // 分享页走 MarkdownView 的 markdown-it 分支，验证 DOMPurify 不清除 SVG 结构。
    const res = await page.request.post(`/api/notes/${note.id}/shares?kb_id=${kb.id}`, {
      data: { expires_in_hours: 1 },
    })
    expect(res.status(), await res.text()).toBe(201)
    const { path } = (await res.json()) as { path: string }
    await page.goto(path)
    const sharedSvg = page.locator('.markdown-view .md-draw svg').first()
    await expect(sharedSvg).toBeVisible()
    await expect(sharedSvg).toContainText('静态渲染节点')
    await expect(sharedSvg.locator('.kiwi-draw-arrowhead')).toHaveCount(1)
    await expect(page.locator('.markdown-view')).toContainText('画布下方正文')
  })
})
