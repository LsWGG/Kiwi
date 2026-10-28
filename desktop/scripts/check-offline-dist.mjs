#!/usr/bin/env node
/**
 * 桌面构建产物的离线检查。
 *
 * 扫描 dist 中的 HTML / CSS / JS / JSON / SVG，发现已知 CDN 或远程字体
 * 主机引用就失败。Kiwi 桌面版不随包携带任何远程资源，构建期漏掉的
 * URL 必须在打包 .exe 之前暴露出来。
 *
 * 用法：node desktop/scripts/check-offline-dist.mjs [distDir]
 */
import { readdir, readFile } from 'node:fs/promises'
import { extname, join, relative, resolve } from 'node:path'

const REMOTE_HOSTS = [
  'fonts.googleapis.com',
  'fonts.gstatic.com',
  'cdn.jsdelivr.net',
  'unpkg.com',
  'esm.sh',
  'cdnjs.cloudflare.com',
  'raw.githubusercontent.com',
]

const SCAN_EXTENSIONS = new Set(['.html', '.css', '.js', '.mjs', '.json', '.svg'])
const MAX_HITS_PER_FILE = 20

const root = resolve(process.argv[2] || 'dist')

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await walk(full)))
    } else if (entry.isFile() && SCAN_EXTENSIONS.has(extname(entry.name).toLowerCase())) {
      files.push(full)
    }
  }
  return files
}

function lineOf(text, index) {
  let line = 1
  for (let i = 0; i < index; i += 1) {
    if (text.charCodeAt(i) === 10) line += 1
  }
  return line
}

/** 每个文件只报告前若干处，避免打包产物里一处数据表刷屏。 */
function findHits(text) {
  const hits = []
  for (const host of new Set(REMOTE_HOSTS)) {
    let from = 0
    while (hits.length < MAX_HITS_PER_FILE) {
      const index = text.indexOf(host, from)
      if (index === -1) break
      hits.push({ host, index, line: lineOf(text, index) })
      from = index + host.length
    }
    if (hits.length >= MAX_HITS_PER_FILE) break
  }
  return hits
}

let files
try {
  files = await walk(root)
} catch (error) {
  console.error(`[offline-dist] 无法读取构建目录 ${root}：${error.message}`)
  process.exit(1)
}

let failures = 0
for (const file of files) {
  const text = await readFile(file, 'utf8')
  const hits = findHits(text)
  if (!hits.length) continue
  failures += hits.length
  const name = relative(root, file)
  for (const hit of hits) {
    console.error(`[offline-dist] ${name}:${hit.line} 引用了远程资源 ${hit.host}`)
  }
}

if (failures) {
  console.error(
    `\n[offline-dist] 发现 ${failures} 处远程资源引用，桌面版必须完全离线。` +
      '请把资源改为本地文件，或在桌面构建插件中移除该引用。',
  )
  process.exit(1)
}

console.log(`[offline-dist] 已检查 ${files.length} 个文件，未发现远程资源引用。`)
