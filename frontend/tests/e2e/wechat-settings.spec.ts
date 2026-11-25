import { test, expect } from './fixtures'

/**
 * ClawBot 设置页：扫码登录、多选知识库、系统时间选择器与自然语言转 cron。
 * 不连接真实 iLink / 模型：接口返回本地数据并记录请求。
 */

const QR =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

const KBS = [
  { id: 'kb-1', name: '知识库一', slug: 'kb-1', stats: {} },
  { id: 'kb-2', name: '知识库二', slug: 'kb-2', stats: {} },
]

function statusPayload(login: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    system_enabled: true,
    enabled: true,
    connected: false,
    login_at: 0,
    remaining_seconds: 0,
    login,
    default_kb_ids: ['kb-1'],
    allow_write: false,
    schedules: [],
    last_contact: { sender: 'tester@im.wechat', at: Date.now() / 1000 },
    ...extra,
  }
}

async function mockBase(page: any) {
  await page.route('**/api/kbs*', async (route: any) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: KBS })
      return
    }
    await route.continue()
  })
}

test.describe('ClawBot 设置', () => {
  test('扫码登录、多选知识库与写权限保存', async ({ page }) => {
    let login = { status: 'disconnected' }
    let settingsPayload: any = null

    await mockBase(page)
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

    await page.goto('/settings/wechat', { waitUntil: 'networkidle' })
    await expect(page.getByText('ClawBot', { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByRole('button', { name: '扫码登录' })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('微信')

    await page.getByRole('button', { name: '扫码登录' }).click()
    await expect(page.locator('img[alt="扫码登录二维码"]')).toBeVisible()
    await expect(page.getByText('用手机扫码并确认')).toBeVisible()

    // 单选知识库时可以开启写操作。
    await page.getByRole('switch').nth(1).click()
    await page.getByRole('button', { name: '保存设置' }).click()
    await expect.poll(() => settingsPayload?.allow_write).toBe(true)
    await expect.poll(() => settingsPayload?.default_kb_ids).toEqual(['kb-1'])

    // 多选后写操作自动关闭，并以多库保存。
    await page.getByLabel('默认知识库').click()
    await page.getByRole('option', { name: /知识库二/ }).click()
    await page.getByRole('button', { name: '完成', exact: true }).click()
    await page.getByRole('button', { name: '保存设置' }).click()
    await expect.poll(() => settingsPayload?.default_kb_ids?.length).toBe(2)
    await expect.poll(() => settingsPayload?.allow_write).toBe(false)
    await expect(page.getByText('已选择多个知识库，写操作自动关闭')).toBeVisible()
  })

  test('常用模式使用系统时间选择器创建任务', async ({ page }) => {
    let schedulePayload: any = null

    await mockBase(page)
    await page.route('**/api/wechat/status', async (route) => {
      await route.fulfill({ json: statusPayload({ status: 'disconnected' }) })
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
    await expect(page.getByText('ClawBot', { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    })

    await page.getByLabel('推送时间').click()
    await page.getByRole('button', { name: '10 时' }).click()
    await page.getByRole('button', { name: '30 分' }).click()
    await expect(page.getByRole('button', { name: '推送时间' })).toContainText('10:30')

    await page.getByLabel('推送内容').fill('总结今天的待办，按优先级列出')
    await page
      .locator('section')
      .filter({ hasText: '定时主动推送' })
      .getByRole('button', { name: '添加' })
      .click()
    await expect.poll(() => schedulePayload?.cron).toBe('30 10 * * *')
    await expect.poll(() => schedulePayload?.kb_ids).toEqual(['kb-1'])
    await expect.poll(() => schedulePayload?.prompt).toBe('总结今天的待办，按优先级列出')
  })

  test('自然语言解析为 cron 后创建任务', async ({ page }) => {
    let previewText = ''
    let schedulePayload: any = null

    await mockBase(page)
    await page.route('**/api/wechat/status', async (route) => {
      await route.fulfill({ json: statusPayload({ status: 'disconnected' }) })
    })
    await page.route('**/api/wechat/schedules/preview', async (route) => {
      previewText = route.request().postDataJSON()?.text || ''
      await route.fulfill({
        json: {
          cron: '0 9 * * *',
          description: '每天 09:00',
          next_runs: ['2026-11-26T09:00', '2026-11-27T09:00'],
        },
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
    await expect(page.getByText('ClawBot', { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    })

    await page.getByRole('button', { name: 'Cron / 自然语言' }).click()
    await page.getByLabel('自然语言计划').fill('每天早上九点')
    await page.getByRole('button', { name: '解析' }).click()
    await expect.poll(() => previewText).toBe('每天早上九点')
    await expect(page.getByText('每天 09:00').first()).toBeVisible()
    await expect(page.getByLabel('Cron 表达式')).toHaveValue('0 9 * * *')

    await page.getByLabel('推送内容').fill('总结今天的待办')
    await page
      .locator('section')
      .filter({ hasText: '定时主动推送' })
      .getByRole('button', { name: '添加' })
      .click()
    await expect.poll(() => schedulePayload?.cron).toBe('0 9 * * *')
  })
})

test('登录链接在前端生成可扫描二维码', async ({ page }) => {
  await page.route('**/api/wechat/status', async (route) => {
    await route.fulfill({
      json: statusPayload({
        status: 'pending',
        qr: 'https://example.test/clawbot-login',
        message: '请扫码',
      }),
    })
  })
  await page.goto('/settings/wechat', { waitUntil: 'networkidle' })
  await expect(page.getByText('ClawBot', { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  })
  const qr = page.locator('img[alt="扫码登录二维码"]')
  await expect(qr).toBeVisible()
  const src = await qr.getAttribute('src')
  expect(src?.startsWith('data:image/')).toBeTruthy()
  await expect(page.locator('body')).not.toContainText('微信')
})
