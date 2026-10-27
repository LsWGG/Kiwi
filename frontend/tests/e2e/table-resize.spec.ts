import type { Locator } from '@playwright/test'
import { expect, openWorkspace, test } from './fixtures'

const TABLE_MD = `# 表格缩放回归

| 项目 | 说明 | 状态 |
| --- | --- | --- |
| 列宽 | 拖动列边框 | 待验证 |
| 行高 | 拖动行底边 | 待验证 |

拖动列边框调整列宽，拖动行底边的手柄调整行高。`

/** Tiptap 的 colwidth 属性会渲染成 HTML 的 colwidth="a,b" 属性。 */
async function readColwidth(cell: Locator): Promise<number> {
  const raw = (await cell.getAttribute('colwidth')) || '0'
  return Number(raw.split(',')[0]) || 0
}

test.describe('表格缩放', () => {
  test('拖动列宽与行高并持久化', async ({ page, kb, notesApi }) => {
    const note = await notesApi.createNote({ title: 'E2E 表格缩放', body_md: TABLE_MD })
    await openWorkspace(page, kb.id, `/notes/${note.id}`)

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible({ timeout: 30_000 })
    const table = editor.locator('table').first()
    await expect(table).toBeVisible()

    const firstHeader = table.locator('th').first()
    const firstRow = table.locator('tr').first()
    const beforeCol = await readColwidth(firstHeader)
    const beforeHeight = (await firstRow.boundingBox())!.height

    // 列宽：悬停第一列右边界后向右拖动。
    const cellBox = (await firstHeader.boundingBox())!
    await page.mouse.move(cellBox.x + cellBox.width - 2, cellBox.y + cellBox.height / 2)
    await expect(editor.locator('.column-resize-handle').first()).toBeVisible()
    await page.mouse.down()
    await page.mouse.move(cellBox.x + cellBox.width + 80, cellBox.y + cellBox.height / 2, {
      steps: 12,
    })
    await page.mouse.up()
    expect(await readColwidth(firstHeader)).toBeGreaterThan(beforeCol + 40)

    // 行高：悬停第一行后向下拖动行底边的手柄。
    await firstRow.hover()
    const handle = firstRow.locator('.kiwi-row-resize-handle')
    await expect(handle).toHaveCount(1)
    const handleBox = (await handle.boundingBox())!
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2)
    await page.mouse.down()
    await page.mouse.move(
      handleBox.x + handleBox.width / 2,
      handleBox.y + handleBox.height / 2 + 46,
      { steps: 12 },
    )
    await page.mouse.up()

    expect((await firstRow.boundingBox())!.height).toBeGreaterThan(beforeHeight + 20)
    await expect(firstRow).toHaveAttribute('data-row-height', /px/)

    // 自动保存后，Markdown 正文降级为 HTML 表格并保留列宽 / 行高。
    await expect
      .poll(async () => (await notesApi.getNote(note.id)).body_md, { timeout: 15_000 })
      .toContain('data-row-height=')

    await page.reload()
    await expect(editor.locator('table').first()).toBeVisible({ timeout: 30_000 })
    const reloadedHeader = editor.locator('table th').first()
    expect(await readColwidth(reloadedHeader)).toBeGreaterThan(beforeCol + 40)
    await expect(editor.locator('table tr').first()).toHaveAttribute('data-row-height', /px/)
  })
})
