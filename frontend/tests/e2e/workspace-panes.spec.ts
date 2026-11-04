import { createServer } from 'node:http'
import { test, expect, openWorkspace } from './fixtures'

/**
 * 分栏工作区：并列打开、聚焦去重、布局预设、拖动分隔条 / 停靠、
 * 关闭与退出、持久化、嵌入内容入口以及窄屏降级。
 */

const paneEls = '[data-pane-id]'

async function createNotes(
  notesApi: any,
  titles: string[],
): Promise<{ id: string; title: string }[]> {
  const notes: { id: string; title: string }[] = []
  for (const title of titles) {
    const note = await notesApi.createNote({ title, body_md: `# ${title}\n\n正文内容。` })
    notes.push({ id: note.id, title })
  }
  return notes
}

async function enterPanes(page: any) {
  await page.getByRole('button', { name: '分栏', exact: true }).first().click()
  await expect(page.locator(paneEls)).toHaveCount(1)
}

test('并列打开多篇笔记，重复打开只聚焦', async ({ page, kb, notesApi }) => {
  const [a, b] = await createNotes(notesApi, ['分栏 A', '分栏 B'])
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)

  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect(page).toHaveURL(new RegExp(b.id))
  await expect(page.locator(paneEls).nth(1)).toContainText('分栏 B')

  // 已打开的笔记再次点击：聚焦原栏，不新增窗口。
  await page.locator(`[data-tree-row="note:${a.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect(page).toHaveURL(new RegExp(a.id))
  await expect(page.locator(paneEls).first()).toHaveClass(/ring-kiwi-400/)
})

test('布局预设按方向平铺窗口', async ({ page, kb, notesApi }) => {
  const [a, b, c] = await createNotes(notesApi, ['布局 A', '布局 B', '布局 C'])
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)
  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await page.locator(`[data-tree-row="note:${c.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(3)

  await page.getByRole('button', { name: '上下排列' }).click()
  const boxes = await page.locator(paneEls).evaluateAll((els) =>
    els.map((el) => el.getBoundingClientRect().toJSON()),
  )
  expect(boxes).toHaveLength(3)
  // 上下排列：三栏 x 基本一致，y 递增。
  expect(Math.abs(boxes[1].x - boxes[0].x)).toBeLessThan(2)
  expect(boxes[1].y).toBeGreaterThan(boxes[0].y)
  expect(boxes[2].y).toBeGreaterThan(boxes[1].y)

  await page.getByRole('button', { name: '左右排列' }).click()
  const rowBoxes = await page.locator(paneEls).evaluateAll((els) =>
    els.map((el) => el.getBoundingClientRect().toJSON()),
  )
  expect(Math.abs(rowBoxes[1].y - rowBoxes[0].y)).toBeLessThan(2)
  expect(rowBoxes[1].x).toBeGreaterThan(rowBoxes[0].x)

  await page.getByRole('button', { name: '网格' }).click()
  await expect(page.locator(paneEls)).toHaveCount(3)
})

test('拖动分隔条改宽度，双击恢复均分', async ({ page, kb, notesApi }) => {
  const [a, b] = await createNotes(notesApi, ['拖拽 A', '拖拽 B'])
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)
  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)

  const first = page.locator(paneEls).first()
  const before = await first.boundingBox()
  const divider = page.getByTitle('拖动调整栏宽，双击恢复均分').first()
  const bar = await divider.boundingBox()
  if (!before || !bar) throw new Error('分隔条不可见')
  await page.mouse.move(bar.x + bar.width / 2, bar.y + bar.height / 2)
  await page.mouse.down()
  await page.mouse.move(bar.x + bar.width / 2 + 120, bar.y + bar.height / 2, { steps: 8 })
  await page.mouse.up()
  const after = await first.boundingBox()
  expect(after!.width).toBeGreaterThan(before.width + 60)

  await divider.dblclick()
  await expect
    .poll(async () => (await first.boundingBox())!.width, { timeout: 3000 })
    .toBeLessThan(after!.width - 20)
})

test('拖动标题停靠到另一栏边缘', async ({ page, kb, notesApi }) => {
  const [a, b] = await createNotes(notesApi, ['停靠 A', '停靠 B'])
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)
  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect(page.locator(paneEls).first()).toContainText('停靠 A')

  const paneA = page.locator(paneEls).first()
  const paneB = page.locator(paneEls).nth(1)
  const grip = paneB.getByTitle('拖动到其他窗口边缘以重新排列')
  const from = await grip.boundingBox()
  const target = await paneA.boundingBox()
  if (!from || !target) throw new Error('拖动目标不可见')

  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(from.x + from.width / 2 + 12, from.y + from.height / 2 + 8, {
    steps: 4,
  })
  await page.mouse.move(target.x + 8, target.y + target.height / 2, { steps: 14 })
  await page.mouse.up()

  await expect(page.locator(paneEls)).toHaveCount(2)
  // 停靠到 A 的左边缘：B 移到最前，A 在其右侧。
  await expect(page.locator(paneEls).first()).toContainText('停靠 B')
  await expect(page.locator(paneEls).nth(1)).toContainText('停靠 A')
})

test('拖动标题时气泡跟随鼠标（大屏缩放下不漂移）', async ({ page, kb, notesApi }) => {
  const [a, b] = await createNotes(notesApi, ['气泡 A', '气泡 B'])
  // 2560 宽会启用 1.3 倍 UI 缩放，正是气泡坐标最容易漂移的场景。
  await page.setViewportSize({ width: 2560, height: 1200 })
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)
  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect
    .poll(() =>
      page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ui-scale').trim()),
    )
    .toBe('1.3')

  const grip = page.locator(paneEls).nth(1).getByTitle('拖动到其他窗口边缘以重新排列')
  const from = await grip.boundingBox()
  if (!from) throw new Error('拖动手柄不可见')
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  const dest = { x: from.x + 160, y: from.y + 120 }
  await page.mouse.move(dest.x, dest.y, { steps: 8 })

  // 气泡定位在外层固定元素（视口像素）上，内层单独缩放，因此 rect 应挨着鼠标。
  const ghost = page.locator('.pane-drag-ghost')
  await expect(ghost).toBeVisible()
  const rect = await ghost.boundingBox()
  if (!rect) throw new Error('拖动气泡不可见')
  expect(Math.abs(rect.x - (dest.x + 10))).toBeLessThanOrEqual(2)
  expect(Math.abs(rect.y - (dest.y + 10))).toBeLessThanOrEqual(2)
  await page.mouse.up()
})

test('关闭活动栏跟随相邻栏，关闭最后一栏退出分栏', async ({ page, kb, notesApi }) => {
  const [a, b] = await createNotes(notesApi, ['关闭 A', '关闭 B'])
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)
  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)

  const paneB = page.locator(paneEls).nth(1)
  await paneB.locator('header[data-pane-header]').click()
  await expect(page).toHaveURL(new RegExp(b.id))
  await paneB.getByTitle('关闭这一栏').click()
  await expect(page.locator(paneEls)).toHaveCount(1)
  await expect(page).toHaveURL(new RegExp(a.id))

  await page.locator(paneEls).first().getByTitle('关闭这一栏').click()
  await expect(page.locator(paneEls)).toHaveCount(0)
  await expect(page.getByText('开始记录')).toBeVisible()
})

test('布局持久化，刷新后恢复', async ({ page, kb, notesApi }) => {
  const [a, b] = await createNotes(notesApi, ['持久 A', '持久 B'])
  await openWorkspace(page, kb.id, `/notes/${a.id}`)
  await enterPanes(page)
  await page.locator(`[data-tree-row="note:${b.id}"]`).click()
  await expect(page.locator(paneEls)).toHaveCount(2)

  await expect
    .poll(() =>
      page.evaluate(() =>
        Object.keys(localStorage).some((key) => key.startsWith('kiwi.note.panes.v1.')),
      ),
    )
    .toBe(true)

  await page.reload()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect(page.locator(paneEls).first()).toContainText('持久 A')
  await expect(page.locator(paneEls).nth(1)).toContainText('持久 B')
})

test('超过 6 栏替换最久未使用的窗口', async ({ page, kb, notesApi }) => {
  const notes = await createNotes(
    notesApi,
    ['上限 1', '上限 2', '上限 3', '上限 4', '上限 5', '上限 6', '上限 7'],
  )
  await openWorkspace(page, kb.id, `/notes/${notes[0].id}`)
  await enterPanes(page)
  for (const note of notes.slice(1)) {
    await page.locator(`[data-tree-row="note:${note.id}"]`).click()
    await expect(page).toHaveURL(new RegExp(note.id))
  }
  await expect(page.locator(paneEls)).toHaveCount(6)
  await expect(page.locator('[data-pane-id]', { hasText: '上限 7' })).toHaveCount(1)
  await expect(page.locator('[data-pane-id]', { hasText: '上限 1' })).toHaveCount(0)
})

test('嵌入网页可从编辑态在分栏中打开', async ({ page, kb, notesApi }) => {
  const embed = JSON.stringify({
    kind: 'link',
    url: 'https://example.com/',
    title: '示例网页',
    site: 'example.com',
    display: 'content',
  })
  const note = await notesApi.createNote({
    title: '嵌入网页笔记',
    body_md: ['```kiwi-embed', embed, '```'].join('\n'),
  })
  await openWorkspace(page, kb.id, `/notes/${note.id}`)
  const wrap = page.locator('.embed-link-wrap')
  await expect(wrap).toBeVisible()
  await wrap.hover()
  await wrap.getByTitle('在分栏中打开').click()

  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect(page.locator(paneEls).nth(1)).toContainText('示例网页')
  await expect(page.locator(paneEls).nth(1)).toContainText('example.com')
})

test('阅读态嵌入文件可从分栏中打开', async ({ page, kb, notesApi }) => {
  const embed = JSON.stringify({
    kind: 'file',
    url: '/media/e2e-pane.txt',
    title: 'e2e.txt',
    filename: 'e2e.txt',
    contentType: 'text/plain',
    size: 12,
    display: 'content',
  })
  const note = await notesApi.createNote({
    title: '嵌入文件笔记',
    body_md: ['```kiwi-embed', embed, '```'].join('\n'),
  })
  await openWorkspace(page, kb.id, `/notes/${note.id}`)
  await page.getByRole('button', { name: '阅读', exact: true }).first().click()

  const card = page.locator('.embed-file')
  await expect(card).toBeVisible()
  await card.getByTitle('在分栏中打开').click()
  await expect(page.locator(paneEls)).toHaveCount(2)
  await expect(page.locator(paneEls).nth(1)).toContainText('e2e.txt')
})

test('网页在分栏内反复刷新时给出浏览器打开出口', async ({ page, kb, notesApi }) => {
  // 模拟跨站 Cookie 被拦截后的反爬校验循环：文档反复 reload。
  const server = createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end('<script>setTimeout(() => location.reload(), 80)</script>')
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as { port: number }).port
  try {
    const embed = JSON.stringify({
      kind: 'link',
      url: `http://127.0.0.1:${port}/loop`,
      title: '循环网页',
      site: '127.0.0.1',
      display: 'content',
    })
    const note = await notesApi.createNote({
      title: '校验循环网页',
      body_md: ['```kiwi-embed', embed, '```'].join('\n'),
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)
    const wrap = page.locator('.embed-link-wrap')
    await expect(wrap).toBeVisible()
    await wrap.hover()
    await wrap.getByTitle('在分栏中打开').click()

    await expect(page.locator(paneEls)).toHaveCount(2)
    await expect(page.locator(paneEls).nth(1)).toContainText('循环网页')
    await expect(page.locator(paneEls).nth(1)).toContainText('网页在分栏内反复刷新', {
      timeout: 15_000,
    })
    await expect(
      page.locator(paneEls).nth(1).getByRole('button', { name: '在浏览器打开' }),
    ).toBeVisible()
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()))
  }
})

test('窄屏不启用分栏', async ({ page, kb, notesApi }) => {
  const note = await notesApi.createNote({ title: '窄屏笔记', body_md: '正文' })
  await openWorkspace(page, kb.id, `/notes/${note.id}`)
  await page.setViewportSize({ width: 600, height: 900 })
  await page.reload()
  await expect(page.locator(paneEls)).toHaveCount(0)
  await expect(page.getByRole('button', { name: '分栏', exact: true })).toHaveCount(0)
})
