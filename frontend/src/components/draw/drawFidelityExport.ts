/**
 * 画布高保真导出。
 *
 * drawSvgExport 的静态渲染器只覆盖常用图形，箭头样式、手绘描边、
 * 流程图符号、绑定文字等细节和编辑态仍有差距。导出时优先调用
 * jvs-draw 自带的 SVG 渲染器，再把字体一起嵌入；只有运行时加载
 * 失败时才回退到静态渲染器。
 */
import { drawDocToSvgForExport } from './drawSvgExport'
import { drawDocUsesHandFont, embedHandFontInSvg, loadHandFont } from './handFont'
import { svgToPngBlob } from './svgRasterExport'
import { drawDocBackground, type JvsDrawDoc } from './types'

interface ExportOptions {
  viewBackgroundColor?: string
  padding?: number
  images?: Record<string, string>
}

type ExportFn = (
  elements: readonly Record<string, unknown>[],
  options?: ExportOptions,
) => Promise<void>

let captureQueue: Promise<unknown> = Promise.resolve()

/**
 * jvs-draw 的导出函数直接创建 <a download> 触发浏览器下载，不返回 Blob。
 * 导出期间临时接管 createObjectURL / anchor.click，把同一份数据截下来，
 * 避免真的在用户浏览器里多下载一个文件；任务串行执行，避免相互覆盖。
 */
function captureDownload(
  run: () => Promise<void>,
  minPixelRatio = 0,
): Promise<Blob> {
  const task = captureQueue.then(() => doCapture(run, minPixelRatio))
  captureQueue = task.catch(() => undefined)
  return task
}

async function doCapture(run: () => Promise<void>, minPixelRatio: number): Promise<Blob> {
  const created: Array<{ url: string; blob: Blob }> = []
  const originalCreate = URL.createObjectURL
  const originalRevoke = URL.revokeObjectURL
  const originalClick = HTMLAnchorElement.prototype.click
  const originalDpr = Object.getOwnPropertyDescriptor(window, 'devicePixelRatio')

  URL.createObjectURL = function (object: Blob | MediaSource): string {
    const url = originalCreate.call(URL, object)
    if (object instanceof Blob) created.push({ url, blob: object })
    return url
  }
  URL.revokeObjectURL = function () {
    // 导出器同步 revoke，这里延后到捕获完成后再释放。
  }
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    // 只拦截导出器创建的下载链接，其它锚点保持原行为。
    if (this.download) return
    return originalClick.call(this)
  }
  if (minPixelRatio > (window.devicePixelRatio || 1)) {
    try {
      // jvs-draw 的位图导出按 devicePixelRatio 放大，低 DPI 屏幕导出会偏糊。
      Object.defineProperty(window, 'devicePixelRatio', {
        configurable: true,
        get: () => minPixelRatio,
      })
    } catch {
      // 不允许覆盖时按原分辨率导出。
    }
  }

  try {
    await run()
  } finally {
    URL.createObjectURL = originalCreate
    URL.revokeObjectURL = originalRevoke
    HTMLAnchorElement.prototype.click = originalClick
    if (originalDpr) Object.defineProperty(window, 'devicePixelRatio', originalDpr)
    else delete (window as unknown as Record<string, unknown>).devicePixelRatio
  }
  for (const item of created) originalRevoke.call(URL, item.url)

  const blob = created[created.length - 1]?.blob
  if (!blob) throw new Error('画布导出失败')
  return blob
}

async function exportElements(
  doc: JvsDrawDoc,
  flattenElbow = false,
): Promise<{
  elements: Record<string, unknown>[]
  options: ExportOptions
  runtime: any
}> {
  const [runtime] = await Promise.all([
    import('jvs-draw'),
    // canvas 渲染文字前字体必须就绪，否则导出仍会落到回退字体。
    drawDocUsesHandFont(doc) ? loadHandFont() : Promise.resolve(true),
  ])
  const elements = (doc.elements ?? []).filter((element) => !element.isDeleted)
  if (!elements.length) throw new Error('画布还没有内容')
  return {
    elements: elements.map((element) => {
      // jvs-draw 的 SVG 导出会给折线箭头加 8px 圆角，而画布本身是直角。
      // 导出 SVG 时把已展开的折线箭头按普通折线绘制，保持与画布一致。
      const points = (element as Record<string, unknown>).points
      if (
        flattenElbow &&
        element.type === 'arrow' &&
        (element as Record<string, unknown>).arrowType === 'elbow' &&
        Array.isArray(points) &&
        points.length > 2
      ) {
        return { ...(element as Record<string, unknown>), arrowType: 'sharp' }
      }
      return element as unknown as Record<string, unknown>
    }),
    options: {
      viewBackgroundColor: drawDocBackground(doc),
      padding: 32,
      images: doc.files ?? {},
    },
    runtime,
  }
}

/**
 * 用 jvs-draw 渲染器生成 SVG；手绘主题会把内置字体内嵌进文件。
 * 抛错时由调用方决定是否回退到 drawDocToSvgForExport。
 */
export async function drawDocToFidelitySvg(doc: JvsDrawDoc): Promise<string> {
  const { elements, options, runtime } = await exportElements(doc, true)
  const exportSvg: ExportFn | undefined =
    runtime.exportSVG ?? runtime.default?.exportSVG ?? runtime.default?.exportSvg
  if (typeof exportSvg !== 'function') throw new Error('画布导出能力不可用')

  const blob = await captureDownload(() => exportSvg(elements, options))
  const svg = await blob.text()
  if (!svg.trim()) throw new Error('画布导出结果为空')
  return drawDocUsesHandFont(doc) ? embedHandFontInSvg(svg) : svg
}

/**
 * 用 jvs-draw 的 canvas 渲染器生成 PNG。
 * 与编辑态共用 renderScene，图形、箭头、手绘描边和文字排版都所见即所得。
 */
export async function drawDocToFidelityPng(
  doc: JvsDrawDoc,
  minPixelRatio = 2,
): Promise<Blob> {
  const { elements, options, runtime } = await exportElements(doc)
  const exportImage: ExportFn | undefined =
    runtime.exportImage ?? runtime.default?.exportImage
  if (typeof exportImage !== 'function') throw new Error('画布导出能力不可用')
  return captureDownload(() => exportImage(elements, options), minPixelRatio)
}

/** 导出入口：优先高保真渲染，失败时回退静态渲染，保证导出可用。 */
export async function drawDocToBestSvg(doc: JvsDrawDoc): Promise<string> {
  try {
    return await drawDocToFidelitySvg(doc)
  } catch (error) {
    console.warn('画布高保真导出失败，回退静态渲染', error)
    return drawDocToSvgForExport(doc)
  }
}

/** PNG 导出入口：高保真 canvas 渲染失败时回退静态 SVG 栅格化。 */
export async function drawDocToBestPng(doc: JvsDrawDoc, scale = 2): Promise<Blob> {
  try {
    return await drawDocToFidelityPng(doc, scale)
  } catch (error) {
    console.warn('画布高保真导出失败，回退静态渲染', error)
    return svgToPngBlob(await drawDocToSvgForExport(doc), scale)
  }
}
