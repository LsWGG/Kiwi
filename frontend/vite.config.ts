import { fileURLToPath, URL } from 'node:url'
import { createReadStream, existsSync } from 'node:fs'
import { stat } from 'node:fs/promises'
import { extname, join, normalize, resolve as pathResolve, sep } from 'node:path'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

const PORTAL_MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.xml': 'application/xml; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.woff2': 'font/woff2',
}

/**
 * 开发服务器把仓库根目录的 portal/ 挂到 /portal/：
 * - 访问 http://localhost:5173/ 默认跳转门户首页；
 * - 应用本身仍可通过 /kbs、/notes 等路径直接访问；
 * - 不复制静态文件，也不影响生产构建。
 */
function portalDevPlugin(): Plugin {
  const portalDir = pathResolve(__dirname, '../portal')

  return {
    name: 'kiwi-portal-dev',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url) return next()

        let pathname: string
        try {
          pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
        } catch {
          return next()
        }

        if (pathname === '/') {
          res.statusCode = 302
          res.setHeader('Location', '/portal/')
          res.setHeader('Cache-Control', 'no-store')
          res.end()
          return
        }

        if (pathname === '/portal') {
          res.statusCode = 301
          res.setHeader('Location', '/portal/')
          res.end()
          return
        }

        if (!pathname.startsWith('/portal/')) return next()

        const relative = normalize(pathname.slice('/portal/'.length)).replace(/^[/\\]+/, '')
        let filePath = join(portalDir, relative)
        if (filePath !== portalDir && !filePath.startsWith(portalDir + sep)) {
          res.statusCode = 403
          res.end('Forbidden')
          return
        }

        try {
          let info = await stat(filePath)
          if (info.isDirectory()) {
            filePath = join(filePath, 'index.html')
            info = await stat(filePath)
          }
          if (!info.isFile()) throw new Error('not a file')

          res.statusCode = 200
          res.setHeader(
            'Content-Type',
            PORTAL_MIME[extname(filePath).toLowerCase()] || 'application/octet-stream',
          )
          res.setHeader('Content-Length', info.size)
          res.setHeader('Cache-Control', 'no-cache')
          if (req.method === 'HEAD') {
            res.end()
            return
          }
          createReadStream(filePath).pipe(res)
        } catch {
          res.statusCode = 404
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end('Portal asset not found')
        }
      })
    },
  }
}

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
    plugins: [portalDevPlugin(), vue()],
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