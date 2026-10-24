import { readFileSync } from 'node:fs'
import { test, expect, dragRow, dragToRoot, openWorkspace } from './fixtures'

const PASSWORD = 'e2e-pass-123'

test.describe('笔记工作区', () => {
  test('编辑、自动保存、改名与阅读视图', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 文档',
      body_md: '# 概述\n\n初始正文内容。',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible()
    await expect(editor).toContainText('初始正文内容')

    await editor.click()
    await page.keyboard.press('Control+End')
    await page.keyboard.press('Enter')
    await page.keyboard.type('自动保存验证段落')
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('自动保存验证段落')

    // 顶部面包屑中的标题输入框；正文里还有一个同名 placeholder 的大标题。
    const titleInput = page.locator('input[placeholder="无标题文档"]').first()
    await titleInput.fill('E2E 文档已改名')
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).title, { timeout: 15_000 })
      .toBe('E2E 文档已改名')

    await page.reload()
    await expect(page.locator('.ProseMirror').first()).toContainText('自动保存验证段落')
    await expect(page.locator('input[placeholder="无标题文档"]').first()).toHaveValue(
      'E2E 文档已改名',
    )

    await page.getByRole('button', { name: '阅读', exact: true }).first().click()
    // 阅读态复用只读编辑器（.kiwi-editor.is-readonly），并显示阅读工具栏。
    const reading = page.locator('.kiwi-editor.is-readonly').first()
    await expect(reading).toBeVisible()
    await expect(reading).toContainText('自动保存验证段落')
    await expect(page.getByRole('button', { name: '全屏阅读' })).toBeVisible()
  })

  test('目录树：双击打开贴一贴浮窗，右键菜单只有一个「移动到分组」', async ({
    page,
    kb,
    notesApi,
  }) => {
    const note = await notesApi.createNote({ title: 'E2E 贴一贴' })
    await openWorkspace(page, kb.id)

    const row = page.locator(`[data-tree-row="note:${note.id}"]`)
    await expect(row).toBeVisible()

    // 用原生双击一次性派发两次点击：CI 负载高时，两次独立 click 的间隔会被
    // 主线程排队拉长到超过 500ms 判定窗口，导致第二下被当成单击。
    // 第二次 pointerdown 按位置命中的判定由下面「双击间隔内列表滚动」用例覆盖。
    await row.dblclick()

    const sticky = page.locator('.sticky-window')
    await expect(sticky).toHaveCount(1)
    await expect(sticky).toContainText('E2E 贴一贴')
    await sticky.getByTitle('关闭便签').click()
    await expect(sticky).toHaveCount(0)

    await row.click({ button: 'right' })
    await expect(page.getByText('移动到分组', { exact: true })).toHaveCount(1)
    await page.keyboard.press('Escape')
  })

  test('目录树：双击间隔内列表滚动，仍贴第一下命中的笔记', async ({ page, kb, notesApi }) => {
    // 长列表：单击打开会滚动定位，若按第二下所在行判定就会贴错或贴不上。
    const first = await notesApi.createNote({ title: 'E2E 滚动命中 0' })
    for (let i = 1; i < 36; i += 1) {
      await notesApi.createNote({ title: `E2E 滚动命中 ${i}` })
    }
    await openWorkspace(page, kb.id)

    const row = page.locator(`[data-tree-row="note:${first.id}"]`)
    await expect(row).toBeVisible()
    const box = (await row.boundingBox())!
    const x = box.x + 90
    const y = box.y + box.height / 2

    await page.mouse.click(x, y)
    // 模拟单击打开后的滚动 / 重排：第二下指针位置不变，但行已经换成了别的笔记。
    await page.evaluate(() => {
      const el = document.querySelector('.sidebar-glass .overflow-y-auto') as HTMLElement | null
      if (el) el.scrollTop += 96
    })
    await page.mouse.click(x, y)

    const sticky = page.locator('.sticky-window')
    await expect(sticky).toHaveCount(1)
    await expect(sticky).toContainText('E2E 滚动命中 0')
  })

  test('贴一贴：大屏放大与窗口缩小后浮窗都保持在可视区域', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({ title: 'E2E 浮窗回收' })
    // 2400px 宽会触发 --ui-scale: 1.3，body zoom 曾把浮窗整体推到屏幕外。
    await page.setViewportSize({ width: 2400, height: 1200 })
    await openWorkspace(page, kb.id)

    const row = page.locator(`[data-tree-row="note:${note.id}"]`)
    await expect(row).toBeVisible()
    await row.dblclick()

    const sticky = page.locator('.sticky-window')
    await expect(sticky).toHaveCount(1)
    const inside = async () =>
      sticky.evaluate((el) => {
        const box = el.getBoundingClientRect()
        return (
          box.left >= 0 && box.top >= 0 && box.right <= window.innerWidth && box.bottom <= window.innerHeight
        )
      })
    // 打开时默认停靠右侧，必须完整落在放大的视口内。
    await expect.poll(inside, { timeout: 5_000 }).toBe(true)

    // 缩小浏览器窗口（同时跨过缩放档位），旧坐标会整个落到视口外。
    await page.setViewportSize({ width: 900, height: 760 })
    await expect.poll(inside, { timeout: 5_000 }).toBe(true)

    // 重新打开同一篇笔记命中的是已有浮窗，也应保持可见。
    await row.click({ button: 'right' })
    await page.getByRole('button', { name: '贴一贴（浮窗）' }).click()
    await expect(sticky).toHaveCount(1)
    await expect.poll(inside, { timeout: 5_000 }).toBe(true)
  })

  test('目录树：拖入分组、拖回根目录并持久化', async ({ page, kb, notesApi }) => {
    const folder = await notesApi.createFolder('E2E 分组')
    const note = await notesApi.createNote({ title: 'E2E 拖动笔记' })
    await openWorkspace(page, kb.id)

    const noteRow = page.locator(`[data-tree-row="note:${note.id}"]`)
    const folderRow = page.locator(`[data-tree-row="folder:${folder.id}"]`)
    await expect(noteRow).toBeVisible()
    await expect(folderRow).toBeVisible()

    await dragRow(page, noteRow, folderRow, 0.5)
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).folder_id, { timeout: 15_000 })
      .toBe(folder.id)
    // 放入分组后组件会自动展开目标分组；若被折叠则手动展开。
    if (!(await noteRow.isVisible())) {
      await folderRow.click()
    }
    await expect(noteRow).toBeVisible()

    await dragToRoot(page, noteRow)
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).folder_id, { timeout: 15_000 })
      .toBeNull()
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).parent_note_id)
      .toBeNull()
  })

  test('模板：使用内置模板创建文档', async ({ page, kb, notesApi }) => {
    await openWorkspace(page, kb.id)

    await page.getByRole('button', { name: '新建', exact: true }).click()
    await page.getByRole('button', { name: /从模板新建/ }).click()
    await expect(page.getByText('内置模板')).toBeVisible({ timeout: 20_000 })

    const useButton = page.getByRole('button', { name: '使用模板' }).first()
    await expect(useButton).toBeEnabled()
    await useButton.click()

    await page.waitForURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 20_000 })
    const noteId = page.url().split('/notes/')[1]
    await expect
      .poll(async () => (await notesApi.getNote(noteId)).body_md.length, {
        timeout: 15_000,
      })
      .toBeGreaterThan(0)
    const created = await notesApi.getNote(noteId)
    expect(created.kind).toBe('doc')
    await expect(page.locator('.ProseMirror').first()).not.toBeEmpty()
  })

  test('密码锁：加密存储、刷新后解锁', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({
      title: 'E2E 加密笔记',
      body_md: '机密内容：项目代号猕猴桃。',
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)
    await expect(page.locator('.ProseMirror').first()).toContainText('项目代号猕猴桃')

    await page.locator('button[aria-label="密码锁"]').click()
    await page.locator('#lock-new-password').fill(PASSWORD)
    await page.locator('#lock-confirm-password').fill(PASSWORD)
    await page
      .locator('label', { hasText: '加密存储正文' })
      .locator('input[type="checkbox"]')
      .check()
    await page.getByRole('button', { name: '设置密码锁', exact: true }).click()
    await expect(page.getByText('已设置密码锁并加密正文')).toBeVisible()

    // 无解锁令牌时，后端不应返回正文，且明确标记为加密存储。
    const locked = await notesApi.getNote(note.id)
    expect(locked.is_locked).toBe(true)
    expect(locked.encrypted).toBe(true)
    expect(locked.body_md).toBe('')

    await page.reload()
    await expect(page.getByText('这篇笔记已上锁，输入密码后查看内容')).toBeVisible()
    await expect(page.getByText('正文已加密存储').first()).toBeVisible()
    await page.locator('#note-lock-password').fill(PASSWORD)
    await page.getByRole('button', { name: '解锁查看' }).click()
    await expect(page.locator('.ProseMirror').first()).toContainText('项目代号猕猴桃')
  })

  test('导入解析进度与后台任务可追踪', async ({ page, kb, notesApi }) => {
    await openWorkspace(page, kb.id)

    await page.getByRole('button', { name: '新建', exact: true }).click()
    await page.getByRole('button', { name: /导入文件/ }).click()
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'e2e-parse.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# 待解析\n\n这段正文将由后台任务解析。'),
    })
    await page.getByRole('button', { name: /开始导入/ }).click()
    await expect(page.getByText('已提交解析')).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: '关闭', exact: true }).click()

    // 后台 worker 在测试环境关闭，任务保持等待中；直接按 API 数据打开导入笔记。
    const tree = await notesApi.getTree()
    const imported = tree.notes.find((n) => n.title === 'e2e-parse')
    expect(imported, '导入后应出现同名笔记').toBeTruthy()
    await page.goto(`/notes/${imported!.id}`)
    await expect(page.getByText('正在解析文档…')).toBeVisible({ timeout: 20_000 })
    await expect(
      page.getByText('解析、切分与向量化在后台进行，完成后正文会自动填充'),
    ).toBeVisible()

    // 运维页可见同一条持久化任务，进度不再依赖单次请求生命周期。
    await page.goto('/settings/operations')
    const jobRow = page.locator('[data-job-kind="ingest"]').first()
    await expect(jobRow).toBeVisible({ timeout: 15_000 })
    await expect(jobRow).toContainText('排队中')
    await expect(jobRow).toContainText('素材摄入')
  })

  test('只读导入：保留原始文件并通过 /media 预览', async ({ page, kb, notesApi }) => {
    await openWorkspace(page, kb.id)

    await page.getByRole('button', { name: '新建', exact: true }).click()
    await page.getByRole('button', { name: /导入文件/ }).click()
    await expect(page.getByText('拖拽文件到这里，或点击选择')).toBeVisible()

    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'e2e-readonly.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# 只读导入\n\n原始文件内容 E2E-READONLY。'),
    })
    await page
      .locator('label', { hasText: '只读导入' })
      .locator('input[type="checkbox"]')
      .check()
    await page.getByRole('button', { name: /开始导入/ }).click()
    await expect(page.getByText('已创建只读笔记')).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: '关闭', exact: true }).click()

    const tree = await notesApi.getTree()
    const imported = tree.notes.find((n) => n.title === 'e2e-readonly')
    expect(imported, '导入后应出现同名笔记').toBeTruthy()
    expect(imported!.kind).toBe('import')

    const full = await notesApi.getNote(imported!.id)
    expect(full.props_json.readonly).toBe(true)
    expect(full.props_json.import?.status).toBe('ready')
    expect(full.props_json.import?.filename).toBe('e2e-readonly.md')

    await page.locator(`[data-tree-row="note:${imported!.id}"]`).click()
    await expect(page.getByText('原始文件内容 E2E-READONLY。')).toBeVisible({
      timeout: 15_000,
    })
  })

  test('智能建议：标签推荐与近似重复提示', async ({ page, kb, notesApi }) => {
    await notesApi.createTag('缓存设计')
    const body = (
      '缓存设计需要关注命中率、失效策略与一致性，本文记录一次完整的缓存改造复盘。'
    ).repeat(3)
    const source = await notesApi.createNote({
      title: 'E2E 建议源',
      body_md: `${body}\n\n本节再次讨论缓存设计。`,
    })
    await notesApi.createNote({ title: 'E2E 建议副本', body_md: body })
    await openWorkspace(page, kb.id, `/notes/${source.id}`)

    await page.getByTitle('笔记信息（Ctrl/⌘ + I）').click()
    await expect(page.getByText('推荐标签，点击添加')).toBeVisible({ timeout: 15_000 })

    // 正文命中已有标签：点击推荐后写入笔记标签。
    await page.getByRole('button', { name: /^缓存设计/ }).first().click()
    await expect
      .poll(async () => (await notesApi.getNote(source.id)).tags, { timeout: 15_000 })
      .toContain('缓存设计')

    // 正文高度重合的副本应被标记为「可能重复」。
    await expect(page.getByText('可能重复').first()).toBeVisible({ timeout: 15_000 })
  })

  test('文本笔记右键导出与阅读视图一致的 PDF', async ({ page, kb, notesApi }) => {
    // 内容足够长时应当分页；每页按阅读态排版截图，不能只导出 Markdown 近似文本。
    const longBody = Array.from(
      { length: 24 },
      (_, index) =>
        `## 第 ${index + 1} 节\n\n第 ${index + 1} 段中文正文，用于验证分页后内容连续、行尾不被截断。`,
    ).join('\n\n')
    const note = await notesApi.createNote({
      title: 'E2E 文本 PDF',
      body_md: `# 概览\n\n中文正文。\n\n| 名称 | 值 |\n| --- | --- |\n| 猕猴桃 | 42 |\n\n${longBody}`,
    })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const row = page.locator(`[data-tree-row="note:${note.id}"]`)
    await expect(row).toBeVisible()
    await row.click({ button: 'right' })

    const downloadEvent = page.waitForEvent('download')
    await page.getByRole('button', { name: /PDF 文档/ }).click()
    const download = await downloadEvent
    expect(download.suggestedFilename()).toContain('.pdf')
    const path = await download.path()
    if (!path) throw new Error('PDF 下载文件不可读')
    const bytes = readFileSync(path)
    expect(bytes.subarray(0, 5).toString('latin1')).toBe('%PDF-')

    const pdf = bytes.toString('latin1')
    const declared = Number(/\/Count (\d+)/.exec(pdf)?.[1] ?? 0)
    const pageObjects = pdf.match(/\/Type \/Page\s/g)?.length ?? 0
    expect(declared).toBeGreaterThan(1)
    expect(pageObjects).toBe(declared)
  })
})
