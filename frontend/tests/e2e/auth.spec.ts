import { test, expect } from '@playwright/test'

/**
 * 访问令牌登录（M2）。
 *
 * 仅在设置 PW_TOKEN_BACKEND_URL（指向启用了 KIWI_ACCESS_TOKEN 的后端）时运行；
 * 该用例由独立的 `auth` 项目通过第二个 Vite 代理执行。
 */
const TOKEN = process.env.PW_ACCESS_TOKEN || 'smoke-token-123'

test('启用访问令牌时先登录再进入工作区', async ({ page }) => {
  await page.goto('/notes')

  await expect(page.getByText('该实例已开启访问控制，请输入访问令牌')).toBeVisible()
  const input = page.locator('#access-token')

  await input.fill('definitely-wrong-token')
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByText('访问令牌不正确')).toBeVisible()

  await input.fill(TOKEN)
  await page.getByRole('button', { name: '进入工作区' }).click()

  await expect(page.getByText('该实例已开启访问控制，请输入访问令牌')).toBeHidden({
    timeout: 15_000,
  })
  // 登录成功后进入笔记工作区。
  await expect(page.getByText('工作区', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('全文搜索全部笔记')).toBeVisible()
})
