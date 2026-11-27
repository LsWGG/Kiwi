import { test, expect, openWorkspace } from './fixtures'

/** 1×1 透明 PNG：验证附件上传插入正文后，刷新页面仍然存在。 */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)
const PDF = Buffer.from(
  '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF\n',
)

async function uploadImage(api: any, kbId: string): Promise<string> {
  const res = await api.post(`/api/attachments?kb_id=${kbId}`, {
    multipart: {
      file: { name: 'e2e.png', mimeType: 'image/png', buffer: PNG },
    },
  })
  expect(res.status(), await res.text()).toBe(201)
  return ((await res.json()) as { url: string }).url
}

test.describe('编辑器附件持久化', () => {
  test('上传图片后保存并刷新，附件仍然存在且可读取', async ({
    page,
    kb,
    notesApi,
    api,
  }) => {
    const note = await notesApi.createNote({
      title: 'E2E 附件持久化',
      body_md: '# 附件\n\n正文占位。',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()

    const fileInput = page.locator('.kiwi-editor input[type="file"][accept*="image"]').first()
    await fileInput.setInputFiles({ name: 'e2e-attach.png', mimeType: 'image/png', buffer: PNG })

    // 图片节点先出现在编辑器里，再等待自动保存把 Markdown 落库。
    await expect(editor.locator('img')).toHaveCount(1)
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
      .toContain('/media/')

    const saved = (await notesApi.getNote(note.id)).body_md
    const src = saved.match(/!\[[^\]]*\]\(([^)\s]+)/)?.[1] || ''
    expect(src, `正文应保留附件地址：${saved}`).toContain('/media/')

    await page.reload()
    const reloaded = page.locator('.ProseMirror').first()
    await expect(reloaded.locator('img')).toHaveCount(1)
    await expect(reloaded.locator('img')).toHaveAttribute('src', src)

    const media = await api.get(src)
    expect(media.status(), await media.text()).toBe(200)
    expect((await media.body()).length).toBe(PNG.length)
  })

  test('附件卡片保存后刷新仍然存在', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 附件卡片',
      body_md: '# 附件卡片\n\n正文占位。',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()

    await page.getByTitle('上传附件').click()
    const dialog = page.locator('.kiwi-modal-panel').filter({ hasText: '点击选择文件' })
    await expect(dialog).toBeVisible()
    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'e2e-attach.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('attachment body'),
    })
    await dialog.getByRole('button', { name: '插入', exact: true }).click()

    await expect(editor.locator('.embed-node')).toHaveCount(1)
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
      .toContain('kiwi-embed')
    expect((await notesApi.getNote(note.id)).body_md).toContain('/media/')

    await page.reload()
    const reloaded = page.locator('.ProseMirror').first()
    await expect(reloaded.locator('.embed-node')).toHaveCount(1)
    await expect(reloaded.locator('.embed-node')).toContainText('e2e-attach.txt')
  })

  test('图片之后的段落插入 PDF 附件仍能保存', async ({ page, kb, notesApi, api }) => {
    const imageUrl = await uploadImage(api, kb.id)
    const note = await notesApi.createNote({
      title: 'E2E 图片旁插入附件',
      body_md: [
        '# 图片旁插入附件',
        '',
        '正文。',
        '',
        '```kiwi-image',
        JSON.stringify({ src: imageUrl, alt: 'e2e', title: '', width: 120 }),
        '```',
        '',
        '尾部文字。',
      ].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()
    // 光标放在文档末尾（图片之后的段落），模拟用户写完正文再插入附件。
    await editor.getByText('尾部文字。').click()
    await page.keyboard.press('End')

    await page.getByTitle('上传附件').click()
    const dialog = page.locator('.kiwi-modal-panel').filter({ hasText: '点击选择文件' })
    await expect(dialog).toBeVisible()
    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'e2e-attach.pdf',
      mimeType: 'application/pdf',
      buffer: PDF,
    })
    await dialog.getByRole('button', { name: '插入', exact: true }).click()

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
      .toContain('kiwi-embed')

    await page.reload()
    const reloaded = page.locator('.ProseMirror').first()
    await expect(reloaded.locator('.embed-node')).toHaveCount(1)
    await expect(reloaded.locator('.embed-node')).toContainText('e2e-attach.pdf')
  })

  test('光标在表格单元格内插入多个附件会写入单元格链接', async ({
    page,
    kb,
    notesApi,
  }) => {
    const note = await notesApi.createNote({
      title: 'E2E 表格内插入附件',
      body_md: [
        '# 表格内插入附件',
        '',
        '| 说明 | 附件 |',
        '| --- | --- |',
        '| 户口本 |  |',
        '| 身份证 |  |',
      ].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor.locator('table')).toHaveCount(1)
    await editor.locator('table tbody tr').last().locator('td').nth(1).click()

    await page.getByTitle('上传附件').click()
    const dialog = page.locator('.kiwi-modal-panel').filter({ hasText: '点击选择文件' })
    await expect(dialog).toBeVisible()
    await dialog.locator('input[type="file"]').setInputFiles([
      { name: 'e2e-table-1.pdf', mimeType: 'application/pdf', buffer: PDF },
      { name: 'e2e-table-2.pdf', mimeType: 'application/pdf', buffer: PDF },
    ])
    await dialog.getByRole('button', { name: '插入', exact: true }).click()

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
      .toContain('[e2e-table-1.pdf](/media/')
    const body = (await notesApi.getNote(note.id)).body_md
    expect(body).toContain('[e2e-table-2.pdf](/media/')
    expect(body).not.toContain('kiwi-embed')

    await page.reload()
    const reloaded = page.locator('.ProseMirror').first()
    await expect(reloaded.locator('table')).toHaveCount(1)
    await expect(reloaded.locator('.embed-node')).toHaveCount(0)
    const cell = reloaded.locator('table tbody tr').last().locator('td').nth(1)
    await expect(cell.locator('a', { hasText: 'e2e-table-1.pdf' })).toHaveCount(1)
    await expect(cell.locator('a', { hasText: 'e2e-table-2.pdf' })).toHaveCount(1)
  })

  test('表格单元格内直接上传图片会插入可点击链接', async ({
    page,
    kb,
    notesApi,
  }) => {
    const note = await notesApi.createNote({
      title: 'E2E 表格内上传图片',
      body_md: [
        '# 表格内上传图片',
        '',
        '| 说明 | 附件 |',
        '| --- | --- |',
        '| 证件照 |  |',
      ].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor.locator('table')).toHaveCount(1)
    await editor.locator('table tbody tr').last().locator('td').nth(1).click()

    const fileInput = page
      .locator('.kiwi-editor input[type="file"][accept*="image"]')
      .first()
    await fileInput.setInputFiles({
      name: 'e2e-cell.png',
      mimeType: 'image/png',
      buffer: PNG,
    })

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
      .toContain('[e2e-cell.png](/media/')
    expect((await notesApi.getNote(note.id)).body_md).not.toContain('![')

    await page.reload()
    const reloaded = page.locator('.ProseMirror').first()
    const cell = reloaded.locator('table tbody tr').last().locator('td').nth(1)
    await expect(cell.locator('a', { hasText: 'e2e-cell.png' })).toHaveCount(1)
  })
})

test('可复用本笔记已上传的附件插入表格单元格', async ({
  page,
  kb,
  notesApi,
  api,
}) => {
  const note = await notesApi.createNote({
    title: 'E2E 复用已上传附件',
    body_md: [
      '# 复用已上传附件',
      '',
      '| 说明 | 附件 |',
      '| --- | --- |',
      '| 证明材料 |  |',
    ].join('\n'),
  })
  const uploaded = await api.post(
    `/api/attachments?kb_id=${kb.id}&note_id=${note.id}&any_type=true`,
    {
      multipart: {
        file: {
          name: 'existing.pdf',
          mimeType: 'application/pdf',
          buffer: PDF,
        },
      },
    },
  )
  expect(uploaded.status(), await uploaded.text()).toBe(201)

  await openWorkspace(page, kb.id, `/notes/${note.id}`)
  const editor = page.locator('.ProseMirror').first()
  await expect(editor.locator('table')).toHaveCount(1)
  await editor.locator('table tbody tr').last().locator('td').nth(1).click()

  await page.getByRole('button', { name: '上传附件' }).click()
  const dialog = page.locator('.kiwi-modal-panel').filter({ hasText: '点击选择文件' })
  await expect(dialog.getByText('本笔记已上传')).toBeVisible()
  const row = dialog.locator('.embed-file-row').filter({ hasText: 'existing.pdf' })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '插入' }).click()

  await expect
    .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 20_000 })
    .toContain('[existing.pdf](/media/')
  const body = (await notesApi.getNote(note.id)).body_md
  expect(body).not.toContain('kiwi-embed')

  await page.reload()
  const reloaded = page.locator('.ProseMirror').first()
  const cell = reloaded.locator('table tbody tr').last().locator('td').nth(1)
  await expect(cell.locator('a', { hasText: 'existing.pdf' })).toHaveCount(1)
})
