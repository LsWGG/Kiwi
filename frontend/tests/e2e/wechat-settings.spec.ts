import { test, expect } from './fixtures'

/**
 * 微信 ClawBot 设置页：扫码登录、允许联系人、默认知识库与定时推送。
 * 不连接真实 iLink：登录接口返回本地二维码，设置 / 任务接口记录请求。
 */

const QR = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

function statusPayload(login: Record<string, unknown>) {
  return {
    system_enabled: true,
    enabled: true,
    connected: false,
    login_at: 0,
    remaining_seconds: 0,
    login,
    default_kb_id: '',
    allow_write: false,
    allowed_users: ['tester@im.wechat'],
    unknown_users: [],
    schedules: [],
    last_contact: { sender: 'tester@im.wechat', at: Date.now() / 1000 },
  }
}

test.describe('微信 ClawBot 设置', () => {
  test('扫码登录、保存权限与创建定时推送', async ({ page }) => {
    let login = { status: 'disconnected' }
    let settingsPayload: any = null
    let schedulePayload: any = null

    await page.route('**/api/kbs*', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          json: [
            { id: 'kb-wechat-1', name: '微信测试库', slug: 'wechat', stats: {} },
          ],
        })
        return
      }
      await route.continue()
    })
    await page.route('**/api/wechat/status', async (route) => {
      await route.fulfill({ json: statusPayload(login) })
    })
    await page.route('**/api/wechat/login', async (route) => {
      login = { status: 'pending', qr: QR, message: '请扫码' }
      await route.fulfill({ json: { system_enabled: true, login } })
    })
    await page.route('**/api/wechat/settings', async (route) => {
      settingsPayload = route.request().postDataJSON()
      await route.fulfill({
        json: { ...statusPayload(login), ...settingsPayload, enabled: true },
      })
    })
    await page.route('**/api/wechat/schedules', async (route) => {
      if (route.request().method() === 'POST') {
        schedulePayload = route.request().postDataJSON()
        await route.fulfill({ status: 201, json: { id: 's1', ...schedulePayload } })
        return
      }
      await route.fulfill({ json: { items: [] } })
    })

    await page.goto('/settings/wechat', { waitUntil: 'networkidle' })
    await expect(page.getByText('微信 ClawBot', { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByRole('button', { name: '扫码登录' })).toBeVisible()
    await expect(page.getByText('tester@im.wechat').first()).toBeVisible()

    await page.getByRole('button', { name: '扫码登录' }).click()
    await expect(page.locator('img[alt="微信登录二维码"]')).toBeVisible()
    await expect(page.getByText('用手机微信扫码并确认')).toBeVisible()

    await page.getByRole('switch').nth(1).click()
    await page.getByRole('button', { name: '保存设置' }).click()
    await expect.poll(() => settingsPayload?.allow_write).toBe(true)
    await expect.poll(() => settingsPayload?.allowed_users).toContain('tester@im.wechat')

    await page.getByLabel('推送内容').fill('总结今天的待办，按优先级列出')
    await page
      .locator('section')
      .filter({ hasText: '定时主动推送' })
      .getByRole('button', { name: '添加' })
      .click()
    await expect.poll(() => schedulePayload?.prompt).toBe('总结今天的待办，按优先级列出')
    await expect.poll(() => schedulePayload?.sender).toBe('tester@im.wechat')
    await expect.poll(() => schedulePayload?.time).toBe('09:00')
  })
})
