import { test, expect, openWorkspace } from './fixtures'

/** 1×1 透明 PNG，用于验证图片节点在 Markdown 往返中的序列化。 */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

async function uploadImage(api: any, kbId: string): Promise<string> {
  const res = await api.post(`/api/attachments?kb_id=${kbId}`, {
    multipart: {
      file: { name: 'e2e.png', mimeType: 'image/png', buffer: PNG },
    },
  })
  const body = await res.text()
  expect(res.status(), body).toBe(201)
  return (JSON.parse(body) as { url: string }).url
}

test.describe('编辑器 Markdown 往返', () => {
  test('待办进度统计多层级清单', async ({ page, kb, notesApi }) => {
    await notesApi.createNote({
      title: 'E2E 多级待办',
      body_md: [
        '```kiwi-task-progress',
        '{"label":"待办进度","showCount":true,"showPercent":true,"color":"indigo","bind":"auto"}',
        '```',
        '',
        '- [x] 一级已完成',
        '  - [ ] 二级未完成',
        '  - [x] 二级已完成',
        '- [ ] 一级未完成',
        '  - [ ] 二级未完成 B',
        '',
        '```kiwi-task-progress',
        '{"label":"完成度","showCount":true,"showPercent":true,"color":"green","bind":"prev"}',
        '```',
      ].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${(await notesApi.getTree()).notes[0].id}`)

    const cards = page.locator('.kiwi-task-progress-card')
    await expect(cards).toHaveCount(2)
    for (const card of [cards.first(), cards.nth(1)]) {
      await expect(card).toBeVisible()
      await expect(card).toHaveAttribute('data-task-done', '2')
      await expect(card).toHaveAttribute('data-task-percent', '40')
      await expect(card).toContainText('2 / 5')
    }

    // 阅读 / 分屏预览走 MarkdownView，统计口径必须与编辑器一致；
    // bind=prev 不能被最后一个二级清单截断。
    await page.getByRole('button', { name: '分屏', exact: true }).first().click()
    const previewCards = page.locator('.markdown-view [data-kiwi-task-progress]')
    await expect(previewCards).toHaveCount(2)
    for (const card of [previewCards.first(), previewCards.nth(1)]) {
      await expect(card).toHaveAttribute('data-task-done', '2')
      await expect(card).toHaveAttribute('data-task-total', '5')
      await expect(card).toHaveAttribute('data-task-percent', '40')
    }
  })

  test('空待办保存后仍是复选框', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 空待办',
      body_md: '- [ ] 正常待办\n- [ ]\n- [ ] 嵌套前\n  - [ ]',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()
    await expect(page.locator('input[type="checkbox"]')).toHaveCount(4)

    await editor.click()
    await page.keyboard.press('Control+End')
    await page.keyboard.type('!')
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('!')

    const saved = (await notesApi.getNote(note.id)).body_md
    expect(saved).not.toContain('\\[ \\]')
    expect(saved.match(/^- \[ \]/gm)?.length).toBe(3)

    await page.reload()
    await expect(page.locator('input[type="checkbox"]')).toHaveCount(4)

    // 阅读 / 分屏预览同样要把空待办识别为复选框。
    await page.getByRole('button', { name: '分屏', exact: true }).first().click()
    await expect(page.locator('.markdown-view input[type="checkbox"]')).toHaveCount(4)
  })

  test('原始 HTML 表格与 emoji 短代码正常渲染并保存', async ({ page, kb, notesApi }) => {
    const body = [
      '# 旅游规划',
      '',
      '<table><colgroup><col></colgroup><tbody>',
      '<tr><td colspan="3"><p>海港区 <span data-name="sun_behind_small_cloud" class="kiwi-emoji" data-type="emoji">🌤</span> 11℃</p></td></tr>',
      '<tr><td><p><strong>时间</strong></p></td><td><p><strong>计划</strong></p></td><td><p><strong>备注</strong></p></td></tr>',
      '</tbody></table>',
      '',
      '## :frame_with_picture: 图册',
    ].join('\n')

    const note = await notesApi.createNote({ title: 'E2E 模板表格', body_md: body })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor.locator('table')).toHaveCount(1)
    await expect(editor).not.toContainText('<table')
    await expect(editor).not.toContainText(':frame_with_picture:')
    await expect(editor).toContainText('🖼')

    await editor.getByText('图册').click()
    await page.keyboard.press('End')
    await page.keyboard.type('!')
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('图册!')

    const saved = (await notesApi.getNote(note.id)).body_md
    // 带 colspan 的复杂表格无法用 GFM 管道表表达，序列化应回退为 HTML 而不是 [table]。
    expect(saved).toContain('<table')
    expect(saved).not.toContain('[table]')
    expect(saved).not.toContain(':frame_with_picture:')
    expect(saved).toContain('🖼')

    // 分屏预览走 MarkdownView：同样要渲染表格与 emoji，且经过 DOMPurify 清洗。
    await page.getByRole('button', { name: '分屏', exact: true }).first().click()
    const preview = page.locator('.markdown-view').first()
    await expect(preview.locator('table')).toHaveCount(1)
    await expect(preview).not.toContainText('<table')
    await expect(preview).toContainText('🖼')
  })

  test('引用块内分栏图片保存后不破坏 Markdown', async ({ page, kb, notesApi, api }) => {
    const url = await uploadImage(api, kb.id)
    const image = (width: number) =>
      ['```kiwi-image', JSON.stringify({ src: url, alt: 'e2e', title: '', width }), '```']
    const body = [
      '> - [ ] 图片分栏',
      '>',
      '>   > [!COLUMNS]',
      '>   >',
      '>   > [!COLUMN]',
      '>   >',
      ...image(120).map((line) => `>   > ${line}`),
      '>   >',
      '>   > [!COLUMN]',
      '>   >',
      ...image(160).map((line) => `>   > ${line}`),
      '> ',
      '> - [ ] 图片后的待办',
    ].join('\n')

    const note = await notesApi.createNote({ title: 'E2E 分栏图片', body_md: body })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    await expect(page.locator('.kiwi-columns')).toHaveCount(1)
    await expect(page.locator('.kiwi-columns img')).toHaveCount(2)

    const editor = page.locator('.ProseMirror').first()
    // 不要点画布中心：那里会命中可选中的图片节点，输入会把图片替换掉。
    const tail = editor.getByText('图片后的待办').last()
    await tail.click()
    await page.keyboard.press('End')
    await page.keyboard.type('!')
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('图片后的待办!')

    const saved = (await notesApi.getNote(note.id)).body_md
    // 每条围栏行都必须保留引用块前缀，否则重新打开会整段乱码。
    expect(saved).not.toContain('```plaintext')
    expect(saved.match(/^>   > ```kiwi-image$/gm)?.length).toBe(2)
    expect(saved.match(/^>   > \{"src":/gm)?.length).toBe(2)
    expect(saved).toContain('> - [ ] 图片后的待办!')

    await page.reload()
    await expect(page.locator('.kiwi-columns')).toHaveCount(1)
    await expect(page.locator('.kiwi-columns img')).toHaveCount(2)
    await expect(page.locator('.ProseMirror').first()).toContainText('图片后的待办!')
  })
})
