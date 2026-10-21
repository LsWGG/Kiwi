import { test, expect, openWorkspace } from './fixtures'

test.describe('运维设置', () => {
  test('展示构建版本、后台任务、审计与备份区块', async ({ page, kb }) => {
    await openWorkspace(page, kb.id, '/settings/operations')

    await expect(page.getByRole('heading', { name: '构建与版本' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '后台任务' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '自动备份' })).toBeVisible()

    // 前端构建信息由 dist/build-info.json（开发态由 Vite 插件）提供。
    await expect(page.getByText('前端静态资源')).toBeVisible()
    await expect(page.getByText('后端服务')).toBeVisible()
  })
})
