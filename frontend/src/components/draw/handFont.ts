/**
 * 画布手绘字体：随前端构建内置「Aa祝你我明媚向春天」，
 * 不依赖部署机器是否安装手写 / 楷体字体。
 *
 * @font-face 在 main.ts 全局引入；字体来源与版权信息见
 * `src/assets/fonts/FONT-NOTICE.txt`。
 */
import handFontUrl from '@/assets/fonts/kiwi-hand.woff2?url'
import type { JvsDrawDoc } from './types'

export const HAND_FONT_FAMILY = 'Kiwi Hand'

/**
 * 画布元素里持久化的是完整字体栈：内置字体缺失时仍能回退到系统手写体，
 * 但正常构建下第一项就会命中，避免不同机器渲染不一致。
 */
export const HAND_FONT_STACK =
  "'Kiwi Hand', 'Segoe Print', 'Comic Sans MS', 'KaiTi', 'STKaiti', 'Kaiti SC', cursive"

const HAND_FONT_RE =
  /Kiwi Hand|Segoe Print|Comic Sans|KaiTi|STKaiti|Kaiti SC|UKai|cursive/i

export function isHandFont(value: unknown): boolean {
  return typeof value === 'string' && HAND_FONT_RE.test(value)
}

let loadPromise: Promise<boolean> | null = null

/**
 * 加载内置手写体。画布用 canvas 绘制文字，字体未就绪时不会像 DOM 一样
 * 自动回流，因此切换到手绘主题 / 打开手绘画布前必须显式等待。
 */
export function loadHandFont(): Promise<boolean> {
  if (loadPromise) return loadPromise
  if (typeof document === 'undefined' || !document.fonts?.load) {
    return Promise.resolve(false)
  }

  const sample = '中文手绘字体 Kiwi 0123，。！？'
  const load = document.fonts.load(`20px "${HAND_FONT_FAMILY}"`, sample)
  const timeout = new Promise<boolean>((resolve) => {
    window.setTimeout(() => resolve(false), 8000)
  })

  loadPromise = Promise.race([
    load.then(() => document.fonts.check(`20px "${HAND_FONT_FAMILY}"`, sample)),
    timeout,
  ])
    .catch(() => false)
    .then((ok) => {
      // 失败 / 超时后清掉缓存，下次切换主题时还能重试。
      if (!ok) loadPromise = null
      return ok
    })

  return loadPromise
}

/** 当前文档是否已经使用手写字体（打开页面时据此预加载字体）。 */
export function drawDocUsesHandFont(doc: JvsDrawDoc | null | undefined): boolean {
  if (!doc) return false
  const appState = (doc.appState ?? {}) as Record<string, unknown>
  if (appState.activeTheme === 'classic' || isHandFont(appState.currentItemFontFamily)) {
    return true
  }
  return (doc.elements ?? []).some(
    (element) =>
      element?.type === 'text' && isHandFont((element as Record<string, unknown>).fontFamily),
  )
}

let fontDataUrlPromise: Promise<string | null> | null = null

/** 读取内置字体并转成 data URL；只读一次，后续导出直接复用。 */
function handFontDataUrl(): Promise<string | null> {
  if (fontDataUrlPromise) return fontDataUrlPromise
  fontDataUrlPromise = fetch(handFontUrl)
    .then((response) => {
      if (!response.ok) throw new Error(`字体加载失败：${response.status}`)
      return response.blob()
    })
    .then(
      (blob) =>
        new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result ?? ''))
          reader.onerror = () => reject(reader.error ?? new Error('字体读取失败'))
          reader.readAsDataURL(blob)
        }),
    )
    .then((dataUrl) => (dataUrl.startsWith('data:') ? dataUrl : null))
    .catch(() => {
      // 网络抖动时允许下次导出重试。
      fontDataUrlPromise = null
      return null
    })
  return fontDataUrlPromise
}

/**
 * 把内置手写体嵌入 SVG。
 *
 * SVG 通过 <img> 加载时是独立文档，拿不到应用的全局 @font-face；
 * 导出 PNG / PDF 或下载独立 SVG 前必须把字体数据一起写进去。
 */
export async function embedHandFontInSvg(svg: string): Promise<string> {
  const dataUrl = await handFontDataUrl()
  if (!dataUrl) return svg
  const style =
    `<style>@font-face{font-family:'${HAND_FONT_FAMILY}';font-style:normal;` +
    `font-weight:400;src:url(${dataUrl}) format('woff2');}</style>`
  return svg.replace(/(<svg\b[^>]*>)/, `$1${style}`)
}
