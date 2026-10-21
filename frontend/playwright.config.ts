import { defineConfig, devices } from '@playwright/test'

/**
 * 前端冒烟测试（M1）。
 *
 * 默认假定后端已在 http://127.0.0.1:8000 运行（建议使用隔离测试库并关闭
 * 后台 worker），Vite 开发服务器由 Playwright 启动并代理到该地址：
 *   PW_BACKEND_URL  后端地址（默认 http://127.0.0.1:8000）
 *   PW_BASE_URL     前端地址（默认 http://127.0.0.1:5173）
 *   PW_NO_WEBSERVER=1 跳过启动 Vite（复用已有服务）
 *
 * 访问控制用例需要额外启动一个设置了 KIWI_ACCESS_TOKEN 的后端，并指定：
 *   PW_TOKEN_BACKEND_URL=http://127.0.0.1:8012
 *   PW_ACCESS_TOKEN=smoke-token-123
 *   PW_AUTH_BASE_URL=http://127.0.0.1:5174（可选，第二个 Vite 代理地址）
 */
const baseURL = process.env.PW_BASE_URL || 'http://127.0.0.1:5173'
const backendURL = process.env.PW_BACKEND_URL || 'http://127.0.0.1:8000'
const tokenBackendURL = process.env.PW_TOKEN_BACKEND_URL || ''
const authBaseURL = process.env.PW_AUTH_BASE_URL || 'http://127.0.0.1:5174'
const isCI = !!process.env.CI

function devServer(url: string, backend: string) {
  const port = Number(new URL(url).port || 5173)
  return {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url,
    timeout: 180_000,
    reuseExistingServer: !isCI,
    env: { VITE_BACKEND_PROXY: backend },
  }
}

const webServer = process.env.PW_NO_WEBSERVER
  ? undefined
  : [
      devServer(baseURL, backendURL),
      ...(tokenBackendURL ? [devServer(authBaseURL, tokenBackendURL)] : []),
    ]

const projects = [
  {
    name: 'chromium',
    testIgnore: /auth\.spec\.ts/,
    use: { ...devices['Desktop Chrome'] },
  },
  ...(tokenBackendURL
    ? [
        {
          name: 'auth',
          testMatch: /auth\.spec\.ts/,
          use: { ...devices['Desktop Chrome'], baseURL: authBaseURL },
        },
      ]
    : []),
]

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: isCI ? 1 : 0,
  reporter: isCI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    launchOptions: {
      // CI / 容器内通常没有可用的 user namespace，关闭 Chromium 自带沙箱。
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    },
  },
  projects,
  webServer,
})
