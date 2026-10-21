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
    await expect(jobRow).toContainText('等待中')
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
})
