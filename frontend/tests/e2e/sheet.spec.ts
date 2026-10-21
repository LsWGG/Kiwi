import { test, expect, openWorkspace } from './fixtures'

test.describe('表格笔记', () => {
  test('编辑、公式、多工作表与自动保存', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({ title: 'E2E 表格', kind: 'sheet' })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const grid = page.locator('[data-sheet-grid]')
    await expect(grid).toBeVisible()

    const editCell = async (address: string, value: string) => {
      const cell = page.locator(`[data-sheet-cell="${address}"]`).first()
      await cell.dblclick()
      const input = page.locator('.cell-editor')
      await expect(input).toBeVisible()
      await input.fill(value)
      await input.press('Enter')
    }

    await editCell('A1', '10')
    await editCell('B1', '20')
    await editCell('A2', '=A1+B1')

    await expect(page.locator('[data-sheet-cell="A2"] .cell-text')).toHaveText('30')

    await page.getByTitle('新建工作表').click()
    const tabs = page.locator('[data-sheet-tab]')
    await expect(tabs).toHaveCount(2)

    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        return saved.props_json?.sheet?.sheets?.length
      }, { timeout: 15_000 })
      .toBe(2)

    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        return saved.props_json?.sheet?.sheets?.[0]?.cells?.A2?.f
      }, { timeout: 15_000 })
      .toBe('=A1+B1')

    await page.reload()
    // 新建工作表后 active 指向新表，回到第一张表检查公式与缓存结果。
    await page.locator('[data-sheet-tab]').first().click()
    await expect(page.locator('[data-sheet-cell="A2"] .cell-text')).toHaveText('30')
    await expect(page.locator('[data-sheet-tab]')).toHaveCount(2)
  })

  test('排序与列筛选（Excel 风格）', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({ title: 'E2E 排序筛选', kind: 'sheet' })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const grid = page.locator('[data-sheet-grid]')
    await expect(grid).toBeVisible()

    const editCell = async (address: string, value: string) => {
      const cell = page.locator(`[data-sheet-cell="${address}"]`).first()
      await cell.dblclick()
      const input = page.locator('.cell-editor')
      await expect(input).toBeVisible()
      await input.fill(value)
      await input.press('Enter')
    }

    await editCell('A1', '名称')
    await editCell('B1', '数量')
    await editCell('A2', '苹果')
    await editCell('B2', '30')
    await editCell('A3', '香蕉')
    await editCell('B3', '10')
    await editCell('A4', '橙子')
    await editCell('B4', '20')

    // 表头下拉与 Excel 一致：排序、筛选都在列头的下拉面板中完成。
    await page.locator('[data-col-filter="1"]').click()
    const panel = page.locator('[data-sheet-filter-panel]')
    await expect(panel).toBeVisible()
    await panel.getByRole('button', { name: '升序' }).click()
    await expect(page.locator('[data-sheet-cell="A2"] .cell-text')).toHaveText('香蕉')
    await expect(page.locator('[data-sheet-cell="B4"] .cell-text')).toHaveText('30')
    await expect(page.locator('[data-sheet-cell="A1"] .cell-text')).toHaveText('名称')

    // 重新打开 B 列表头下拉，只保留数值 20。
    await page.locator('[data-col-filter="1"]').click()
    await expect(panel).toBeVisible()
    await panel.locator('label.filter-check', { hasText: /^10/ }).click()
    await panel.locator('label.filter-check', { hasText: /^30/ }).click()
    await panel.getByRole('button', { name: '确定' }).click()

    // 表头始终显示，其余行按筛选值隐藏。
    await expect(panel).toHaveCount(0)
    await expect(page.locator('[data-sheet-cell="A1"] .cell-text')).toHaveText('名称')
    await expect(page.locator('[data-sheet-cell="A3"] .cell-text')).toHaveText('橙子')
    await expect(page.locator('[data-sheet-cell="A2"]')).toHaveCount(0)
    await expect(page.locator('[data-sheet-cell="A4"]')).toHaveCount(0)

    // 筛选条件随工作簿持久化。
    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        return saved.props_json?.sheet?.sheets?.[0]?.filters?.['1']
      }, { timeout: 15_000 })
      .toEqual(['20'])

    await page.locator('[data-sheet-clear-filters]').click()
    await expect(page.locator('[data-sheet-cell="A2"] .cell-text')).toHaveText('香蕉')
    await expect(page.locator('[data-sheet-cell="A4"] .cell-text')).toHaveText('苹果')
  })

  test('工具栏颜色选择器：预设与自绘取色', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({ title: 'E2E 表格颜色', kind: 'sheet' })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)
    await expect(page.locator('[data-sheet-grid]')).toBeVisible()

    const cell = page.locator('[data-sheet-cell="A1"]').first()
    await cell.dblclick()
    const input = page.locator('.cell-editor')
    await input.fill('颜色')
    await input.press('Enter')
    await page.locator('[data-sheet-cell="A1"]').click()

    // 与文本笔记同款选择器，且不再出现浏览器原生 color 控件。
    await expect(page.locator('[data-sheet-toolbar] input[type="color"]')).toHaveCount(0)
    const triggers = page.locator('[data-sheet-toolbar] [data-color-trigger]')
    await expect(triggers).toHaveCount(2)
    await triggers.first().click()
    await expect(page.locator('[data-color-swatch="#DC2626"]')).toBeVisible()
    await page.locator('[data-color-custom]').click()
    await expect(page.locator('[data-color-custom-panel]')).toBeVisible()
    await page.locator('[data-color-hex]').fill('#16A34A')
    await page.locator('[data-color-apply]').click()
    await expect(page.locator('[data-color-custom-panel]')).toHaveCount(0)

    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        return saved.props_json?.sheet?.sheets?.[0]?.cells?.A1?.s?.color
      }, { timeout: 15_000 })
      .toBe('#16A34A')

    // 填充色使用第二个选择器，清除后恢复无填充。
    await triggers.nth(1).click()
    await page.locator('[data-color-custom]').click()
    await page.locator('[data-color-hex]').fill('#FEF3C7')
    await page.locator('[data-color-apply]').click()
    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        return saved.props_json?.sheet?.sheets?.[0]?.cells?.A1?.s?.bg
      }, { timeout: 15_000 })
      .toBe('#FEF3C7')

    await triggers.nth(1).click()
    await page.locator('[data-color-clear]').click()
    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        return saved.props_json?.sheet?.sheets?.[0]?.cells?.A1?.s?.bg
      }, { timeout: 15_000 })
      .toBeUndefined()
  })

  test('全选后拖动列宽/行高对所有行列生效', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({ title: 'E2E 全选尺寸', kind: 'sheet' })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)
    await expect(page.locator('[data-sheet-grid]')).toBeVisible()

    // 空表也应在每一列显示筛选图标（与 Excel 一致）。
    await expect(page.locator('[data-col-filter="5"]')).toBeVisible()

    await page.locator('.corner-cell').click()
    const colHandle = page.locator('thead .col-resize').first()
    const colBox = await colHandle.boundingBox()
    expect(colBox).not.toBeNull()
    await page.mouse.move(colBox!.x + colBox!.width / 2, colBox!.y + colBox!.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      colBox!.x + colBox!.width / 2 + 40,
      colBox!.y + colBox!.height / 2,
      { steps: 4 },
    )
    await page.mouse.up()

    const rowHandle = page.locator('tbody .row-resize').first()
    const rowBox = await rowHandle.boundingBox()
    expect(rowBox).not.toBeNull()
    await page.mouse.move(rowBox!.x + rowBox!.width / 2, rowBox!.y + rowBox!.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      rowBox!.x + rowBox!.width / 2,
      rowBox!.y + rowBox!.height / 2 + 20,
      { steps: 4 },
    )
    await page.mouse.up()

    await expect
      .poll(async () => {
        const saved = await notesApi.getNote(note.id)
        const sheet = saved.props_json?.sheet?.sheets?.[0]
        return {
          col0: sheet?.colWidths?.['0'],
          col1: sheet?.colWidths?.['1'],
          row0: sheet?.rowHeights?.['0'],
          row1: sheet?.rowHeights?.['1'],
        }
      }, { timeout: 15_000 })
      .toEqual({ col0: 144, col1: 144, row0: 48, row1: 48 })
  })

  test('目录树创建表格并右键插入行列', async ({ page, kb, notesApi }) => {
    await openWorkspace(page, kb.id)
    await page.getByRole('button', { name: '新建', exact: true }).click()
    await page.getByRole('button', { name: /^表格/ }).click()

    await page.waitForURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 20_000 })
    const noteId = page.url().split('/notes/')[1]
    await expect
      .poll(async () => (await notesApi.getNote(noteId)).kind, { timeout: 15_000 })
      .toBe('sheet')

    const grid = page.locator('[data-sheet-grid]')
    await expect(grid).toBeVisible()
    await page.locator('[data-sheet-cell="B2"]').first().click({ button: 'right' })
    await expect(page.getByText('下方插入行')).toBeVisible()
    await page.getByText('下方插入行').click()
    // 插入后 B3 存在且仍可编辑（行号在左侧）
    await expect(page.locator('[data-sheet-cell="B3"]')).toHaveCount(1)
  })
})
