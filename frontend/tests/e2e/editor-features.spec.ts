import { test, expect, openWorkspace } from './fixtures'

test.describe('编辑器增强', () => {
  test('自定义字体颜色随 Markdown 持久化', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 字体颜色',
      body_md: '需要变色的文字',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()
    await editor.click()
    await page.keyboard.press('Control+A')

    const picker = page.locator('.kiwi-toolbar [data-color-trigger]')
    await expect(picker).toHaveCount(1)
    await picker.click()
    // 预设色板出现在浮层中，点击玫红即可应用
    const swatch = page.locator('[data-color-swatch="#E11D48"]')
    await expect(swatch).toBeVisible()
    await swatch.click()

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toMatch(/E11D48|e11d48/)

    const saved = (await notesApi.getNote(note.id)).body_md
    expect(saved).toContain('span')
    expect(saved).toMatch(/color/i)

    await page.reload()
    const colored = page.locator('.ProseMirror span[data-color="#E11D48"], .ProseMirror span[style*="color"]').first()
    await expect(colored).toBeVisible()
  })

  test('表格上下文菜单：增删行、表头与单元格底色', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 表格菜单',
      body_md: ['| 名称 | 数值 |', '| --- | --- |', '| A | 1 |', '| B | 2 |'].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()
    await editor.locator('td', { hasText: 'A' }).first().click()

    // 表格操作只在上下文菜单里出现一次，工具栏不再重复提供。
    await expect(page.getByTitle('在上方插入行')).toHaveCount(1)
    await expect(page.getByRole('button', { name: '首行表头' })).toBeVisible()

    const rows = editor.locator('table tr')
    await expect(rows).toHaveCount(3)
    await page.getByTitle('在下方插入行').click()
    await expect(rows).toHaveCount(4)

    await page.getByTitle('浅蓝').click()
    const cellBg = await editor
      .locator('td')
      .filter({ hasText: 'A' })
      .first()
      .evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(cellBg).toBe('rgb(219, 234, 254)')

    await page.getByRole('button', { name: '首行表头' }).click()
    await expect(editor.locator('table th')).toHaveCount(0)
    await page.getByRole('button', { name: '首行表头' }).click()
    await expect(editor.locator('table th').first()).toBeVisible()

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('data-bg')
    const saved = (await notesApi.getNote(note.id)).body_md
    expect(saved).toContain('<table')

    await page.reload()
    const reloadedCell = page.locator('.ProseMirror td').filter({ hasText: 'A' }).first()
    await expect(reloadedCell).toHaveAttribute('data-bg', '#DBEAFE')
  })

  test('Simple 与 Notion 合并为标准编辑：工具栏、斜杠命令和拖动手柄同时可用', async ({
    page,
    kb,
    notesApi,
  }) => {
    const note = await notesApi.createNote({ title: 'E2E 合并模式', body_md: '正文' })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    // 标题里也含“标准编辑”（顶部知识库按钮的可访问名包含笔记标题），锚定模式按钮的 title。
    const modeTrigger = page.getByTitle('切换编辑器模式')
    await expect(modeTrigger).toBeVisible()
    await expect(modeTrigger).toContainText('标准编辑')
    await expect(page.locator('#kiwi-drag-handle')).toHaveCount(1)

    const editor = page.locator('.ProseMirror').first()
    await editor.click()
    await page.keyboard.press('Control+End')
    await page.keyboard.press('Enter')
    await page.keyboard.type('/')
    await expect(page.locator('.slash-menu').getByText('标题 1', { exact: true })).toBeVisible({
      timeout: 10_000,
    })
    await page.keyboard.press('Escape')

    await modeTrigger.click()
    await expect(page.getByText('DOCX editor')).toBeVisible()
    await expect(page.getByText('Notion-like editor')).toHaveCount(0)
  })

  test('@笔记卡片独占一行但不产生额外空行', async ({ page, kb, notesApi }) => {
    const target = await notesApi.createNote({ title: '被提及笔记', body_md: '# 被提及' })
    const host = await notesApi.createNote({
      title: 'E2E 提及卡片',
      body_md: `第一段。\n\n[@被提及笔记](kiwi://note/${target.id}?display=card)\n\n第三段。`,
    })
    await openWorkspace(page, kb.id, `/notes/${host.id}`)

    const card = page.locator('.ProseMirror .kiwi-mention-node.is-card')
    await expect(card).toBeVisible()
    const metrics = await card.evaluate((el) => {
      const paragraph = el.closest('p')
      return {
        display: getComputedStyle(el).display,
        paragraphHeight: paragraph?.getBoundingClientRect().height ?? 0,
        cardHeight: el.getBoundingClientRect().height,
      }
    })
    // 节点仍是行内节点；用 inline-block 撑满宽度，避免块级子节点在段落上下
    // 各生成一个匿名行盒（表现为卡片前后多出空行）。
    expect(metrics.display).toBe('inline-block')
    expect(metrics.paragraphHeight - metrics.cardHeight).toBeLessThan(32)
  })

  test('附件嵌入支持卡片展示，可切换并持久化', async ({ page, kb, notesApi }) => {
    const embed = JSON.stringify({
      kind: 'file',
      url: '/media/e2e-card.pdf',
      title: '季度报告.pdf',
      filename: '季度报告.pdf',
      contentType: 'application/pdf',
      size: 2345678,
      display: 'card',
    })
    const note = await notesApi.createNote({
      title: 'E2E 附件卡片',
      body_md: ['# 附件卡片', '', '```kiwi-embed', embed, '```', '', '结尾段落。'].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const card = page.locator('.ProseMirror .embed-file-card')
    await expect(card).toBeVisible()
    await expect(card).toContainText('季度报告.pdf')
    await expect(card).toContainText('PDF')
    await expect(card).toContainText('2.2 MB')

    // 卡片 → 内容预览 → 标题超链接 → 卡片，三种展示方式可往返切换。
    await page.locator('.ProseMirror').getByTitle('展开为内容预览').first().click()
    await expect(page.locator('.ProseMirror .embed-file')).toBeVisible()
    await page.locator('.ProseMirror .embed-file-bar').getByTitle('以标题超链接展示').click()
    await expect(page.locator('.ProseMirror .embed-title-link')).toBeVisible()
    await page.locator('.ProseMirror').getByTitle('以卡片展示').first().click()
    await expect(page.locator('.ProseMirror .embed-file-card')).toBeVisible()

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('"display":"card"')
  })

  test('阅读模式工具栏可显示目录', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 阅读目录',
      body_md: '# 第一章\n\n正文第一段。\n\n## 第一节\n\n正文第二段。',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)
    await expect(page.locator('.ProseMirror').first()).toContainText('正文第一段')

    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    const reading = page.locator('.kiwi-editor.is-readonly').first()
    await expect(reading).toBeVisible()

    const tocButton = page.getByTitle('显示目录')
    await expect(tocButton).toBeVisible()
    await tocButton.click()
    await expect(page.getByTitle('隐藏目录')).toBeVisible()
    const outline = page.locator('.editor-outline')
    await expect(outline).toBeVisible()
    await expect(outline).toContainText('第一章')
    await expect(outline).toContainText('第一节')
    await page.getByTitle('隐藏目录').click()
    await expect(outline).toHaveCount(0)
  })
})
