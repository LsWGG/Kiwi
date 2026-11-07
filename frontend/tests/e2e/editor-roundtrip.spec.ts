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

    // 阅读态使用只读编辑器，统计口径必须与编辑态一致；
    // bind=prev 不能被最后一个二级清单截断。
    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    const previewCards = page.locator('.ProseMirror .kiwi-task-progress-card')
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

    // 阅读态同样要把空待办识别为复选框。
    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    await expect(page.locator('.ProseMirror input[type="checkbox"]')).toHaveCount(4)
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

    // 阅读态同样要渲染表格与 emoji，且不能把 HTML 源码当文本显示。
    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    const preview = page.locator('.ProseMirror').first()
    await expect(preview.locator('table')).toHaveCount(1)
    await expect(preview).not.toContainText('<table')
    await expect(preview).toContainText('🖼')
  })

  test('标题作为有序列表项时保持标题格式', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 标题有序列表',
      body_md: ['## 二级标题', '', '正文', '', '#### 四级标题', '', '正文'].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await editor.getByText('二级标题').click()
    await page.locator('button[title="有序列表"]').first().click()

    const item = editor.locator('ol > li').first()
    await expect(item.locator('> h2')).toHaveCount(1)
    const styles = await item.evaluate((li) => {
      const heading = li.firstElementChild as HTMLElement
      const number = getComputedStyle(heading, '::before')
      const headingStyle = getComputedStyle(heading)
      const ol = li.closest('ol') as HTMLElement
      return {
        tag: heading.tagName,
        headingSize: headingStyle.fontSize,
        headingWeight: headingStyle.fontWeight,
        numberContent: number.content,
        numberSize: number.fontSize,
        numberWeight: number.fontWeight,
        firstCharOffset:
          heading.getBoundingClientRect().left - ol.getBoundingClientRect().left,
        listStyle: getComputedStyle(li).listStyleType,
      }
    })
    expect(styles.tag).toBe('H2')
    // 编号直接写在标题文字前（标题的 ::before），字号 / 字重与标题一致，
    // 避免「大标题 + 小号灰编号」的割裂。
    expect(styles.listStyle).toBe('none')
    expect(styles.numberContent).toContain('counter(')
    expect(styles.numberContent).toContain('". "')
    expect(styles.numberSize).toBe(styles.headingSize)
    expect(styles.numberWeight).toBe(styles.headingWeight)
    // 第一位数距离列表左侧装饰条固定 0.6rem（9.6px），
    // 「1 / 11 / 111」都从同一位置开始，不随位数漂移。
    expect(styles.firstCharOffset).toBeCloseTo(9.6, 1)

    // 二级标题的紫色竖条保留，并落到有序列表序号左侧（列表缩进的最外沿）。
    const bar = await item.locator('h2').evaluate((h2) => {
      const after = getComputedStyle(h2, '::after')
      const ol = h2.closest('ol') as HTMLElement
      return {
        content: after.content,
        position: after.position,
        left: parseFloat(after.left),
        olPadding: parseFloat(getComputedStyle(ol).paddingLeft),
      }
    })
    expect(bar.content).not.toBe('none')
    expect(bar.position).toBe('absolute')
    expect(Math.abs(bar.left)).toBeCloseTo(bar.olPadding, 1)

    // 四级标题也应有明确的标题层级，不再与正文字号一致。
    const h4 = await editor.locator('h4').first().evaluate((el) => {
      const cs = getComputedStyle(el)
      return { size: parseFloat(cs.fontSize), weight: parseFloat(cs.fontWeight) }
    })
    expect(h4.size).toBeGreaterThan(15)
    expect(h4.weight).toBeGreaterThanOrEqual(600)

    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('1. ## 二级标题')

    // 阅读态复用只读编辑器，结构与样式保持一致。
    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    await expect(page.locator('.ProseMirror ol > li > h2')).toHaveCount(1)
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
