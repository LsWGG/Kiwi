import { fileURLToPath, URL } from 'node:url'
import { createReadStream, existsSync } from 'node:fs'
import { cp, rm, stat } from 'node:fs/promises'
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

/**
 * PDF.js 运行期资源（CJK CMap、标准字体、wasm、ICC）不参与打包，
 * 开发期从 node_modules 直出，构建时复制到 dist/pdfjs。
 * 这样仓库里不提交这几 MB 的第三方资源，又保证离线部署可用。
 */
const PDFJS_ASSET_DIRS = ['cmaps', 'standard_fonts', 'wasm', 'iccs']
const PDFJS_DIR = pathResolve(__dirname, 'node_modules/pdfjs-dist')

const PDFJS_MIME: Record<string, string> = {
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
  '.bcmap': 'application/octet-stream',
  '.pfb': 'application/octet-stream',
  '.ttf': 'font/ttf',
  '.otf': 'font/otf',
  '.icc': 'application/octet-stream',
}

/** 解析 /pdfjs/<dir>/<file>，拒绝 `..` 越界。 */
function resolvePdfjsAsset(pathname: string): string | null {
  if (!pathname.startsWith('/pdfjs/')) return null
  const relative = pathname.slice('/pdfjs/'.length)
  const slash = relative.indexOf('/')
  if (slash <= 0) return null
  const dir = relative.slice(0, slash)
  if (!PDFJS_ASSET_DIRS.includes(dir)) return null
  const base = pathResolve(PDFJS_DIR, dir)
  const filePath = pathResolve(PDFJS_DIR, relative)
  if (filePath !== base && !filePath.startsWith(base + sep)) return null
  return filePath
}

function pdfjsAssetsDevPlugin(): Plugin {
  return {
    name: 'kiwi-pdfjs-assets-dev',
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
        const filePath = resolvePdfjsAsset(pathname)
        if (!filePath) return next()

        try {
          const info = await stat(filePath)
          if (!info.isFile()) throw new Error('not a file')
          res.statusCode = 200
          res.setHeader(
            'Content-Type',
            PDFJS_MIME[extname(filePath).toLowerCase()] || 'application/octet-stream',
          )
          res.setHeader('Content-Length', info.size)
          res.setHeader('Cache-Control', 'public, max-age=86400')
          if (req.method === 'HEAD') {
            res.end()
            return
          }
          createReadStream(filePath).pipe(res)
        } catch {
          res.statusCode = 404
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.end('PDF.js asset not found')
        }
      })
    },
  }
}

function pdfjsAssetsBuildPlugin(): Plugin {
  return {
    name: 'kiwi-pdfjs-assets-build',
    apply: 'build',
    async closeBundle() {
      const outDir = pathResolve(__dirname, 'dist/pdfjs')
      await rm(outDir, { recursive: true, force: true })
      for (const dir of PDFJS_ASSET_DIRS) {
        const source = pathResolve(PDFJS_DIR, dir)
        if (existsSync(source)) {
          await cp(source, pathResolve(outDir, dir), { recursive: true })
        }
      }
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
    plugins: [portalDevPlugin(), pdfjsAssetsDevPlugin(), pdfjsAssetsBuildPlugin(), vue()],
    build: {
      // 压缩体积统计对产物无影响，关闭后可降低 CI / 低内存主机上的构建内存。
      reportCompressedSize: false,
      rollupOptions: {
        output: {
          // PDF.js 的 worker 源文件是 .mjs；nginx 默认 mime.types 不一定把 .mjs
          // 识别为 JavaScript，改成 .js 可避免生产环境 module worker 因 MIME 被拒。
          assetFileNames: (asset) => {
            const name = asset.names?.[0] ?? ''
            if (name.includes('pdf.worker')) return 'assets/pdf.worker-[hash].js'
            return 'assets/[name]-[hash][extname]'
          },
        },
      },
    },
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