import { fileURLToPath, URL } from 'node:url'
import { existsSync } from 'node:fs'
import { resolve as pathResolve } from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 后端地址可配：VITE_BACKEND_PROXY=http://localhost:8001 npm run dev
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_BACKEND_PROXY || 'http://localhost:8000'

  // G6 未安装时 alias 到本地 stub，保证 build/dev 不因缺包而失败。
  // 安装 @antv/g6 后此 alias 自动失效（node_modules 存在即走真包）。
  const g6Installed = existsSync(pathResolve(__dirname, 'node_modules/@antv/g6'))
  const g6Alias: Record<string, string> = g6Installed
    ? {}
    : { '@antv/g6': pathResolve(__dirname, 'src/graph/g6-stub.ts') }

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        ...g6Alias,
      },
    },
    server: {
      port: 5173,
      proxy: {
        // 开发期把 /api 代理到后端，规避跨域
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
        // 附件 / 内嵌媒体
        '/media': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
  }
})