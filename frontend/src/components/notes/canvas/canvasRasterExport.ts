/**
 * 画布位图 / PDF 导出。
 * 复用 canvasDocToSvg 的矢量结果：在浏览器里栅格化为 PNG，
 * 或把高分辨率 JPEG 封进单页 PDF，避免为一次导出引入 PDF 库。
 */

const MAX_RASTER_SIDE = 4096
const PAGE_LONG = 841.89
const PAGE_SHORT = 595.28
const PAGE_MARGIN = 28

export interface SvgSize {
  width: number
  height: number
}

export interface PdfImageOptions {
  jpeg: Uint8Array
  pixelWidth: number
  pixelHeight: number
  title?: string
  /** 页面底色，通常取画布主题背景；缺省为白。 */
  background?: string
}

export interface PdfPageImage {
  jpeg: Uint8Array
  pixelWidth: number
  pixelHeight: number
}

export interface PdfPagesOptions {
  title?: string
  /** 页面底色；缺省为白。 */
  background?: string
  /** 页面尺寸（pt），缺省为 A4 纵向。 */
  pageWidth?: number
  pageHeight?: number
}

/** 从 SVG 根节点读取宽高（导出器始终写入 width/height，viewBox 作为兜底）。 */
export function svgSize(svg: string): SvgSize {
  const parsed = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const root = parsed.documentElement
  const width = Number(root.getAttribute('width'))
  const height = Number(root.getAttribute('height'))
  if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
    return { width, height }
  }
  const viewBox = (root.getAttribute('viewBox') ?? '').split(/[\s,]+/).map(Number)
  if (viewBox.length === 4 && viewBox[2] > 0 && viewBox[3] > 0) {
    return { width: viewBox[2], height: viewBox[3] }
  }
  return { width: 640, height: 400 }
}

function loadSvgImage(svg: string): Promise<HTMLImageElement> {
  const image = new Image()
  image.decoding = 'async'
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return new Promise((resolve, reject) => {
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('画布渲染失败，无法生成图片'))
    image.src = url
  })
}

async function rasterize(
  svg: string,
  scale: number,
): Promise<{ canvas: HTMLCanvasElement; width: number; height: number }> {
  const size = svgSize(svg)
  const maxSide = Math.max(size.width, size.height)
  const ratio = Math.max(0.1, Math.min(scale, MAX_RASTER_SIDE / maxSide))
  const image = await loadSvgImage(svg)
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(size.width * ratio))
  canvas.height = Math.max(1, Math.round(size.height * ratio))
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('当前浏览器不支持 Canvas 导出')
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  return { canvas, width: canvas.width, height: canvas.height }
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality?: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('图片编码失败'))),
      type,
      quality,
    )
  })
}

/** SVG 字符串 → PNG Blob；scale 为像素倍率（默认 2x）。 */
export async function svgToPngBlob(svg: string, scale = 2): Promise<Blob> {
  const { canvas } = await rasterize(svg, scale)
  return canvasToBlob(canvas, 'image/png')
}

/** SVG 字符串 → 单页 PDF Blob，页面按 A4 横竖向自适应并居中。 */
export async function svgToPdfBlob(
  svg: string,
  options: { title?: string; background?: string; scale?: number } = {},
): Promise<Blob> {
  const { canvas, width, height } = await rasterize(svg, options.scale ?? 2)
  const jpegBlob = await canvasToBlob(canvas, 'image/jpeg', 0.92)
  const jpeg = new Uint8Array(await jpegBlob.arrayBuffer())
  return buildImagePdf({
    jpeg,
    pixelWidth: width,
    pixelHeight: height,
    title: options.title,
    background: options.background,
  })
}

function hexToRgb(hex: string): [number, number, number] {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!match) return [1, 1, 1]
  const value = Number.parseInt(match[1], 16)
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255]
}

/** PDF 文本串使用 UTF-16BE 十六进制，中文标题无需依赖字体。 */
export function pdfTextHex(text: string): string {
  let hex = 'FEFF'
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0
    if (code > 0xffff) {
      const value = code - 0x10000
      hex += (0xd800 + (value >> 10)).toString(16).padStart(4, '0')
      hex += (0xdc00 + (value & 0x3ff)).toString(16).padStart(4, '0')
    } else {
      hex += code.toString(16).padStart(4, '0')
    }
  }
  return hex.toUpperCase()
}

function fixed(value: number): string {
  return (Math.round(value * 100) / 100).toString()
}

interface PdfPageSpec {
  jpeg: Uint8Array
  pixelWidth: number
  pixelHeight: number
  pageWidth: number
  pageHeight: number
  drawWidth: number
  drawHeight: number
  drawX: number
  drawY: number
  background: string
}

/** 把若干页 JPEG 写成最小可用的 PDF（DCTDecode，不重新编码）。 */
function writeImagePdf(pages: PdfPageSpec[], title?: string): Blob {
  if (!pages.length) throw new Error('PDF 页面为空')

  const encoder = new TextEncoder()
  const chunks: Uint8Array[] = []
  const offsets: number[] = []
  let cursor = 0

  const push = (part: string | Uint8Array) => {
    const bytes = typeof part === 'string' ? encoder.encode(part) : part
    chunks.push(bytes)
    cursor += bytes.length
  }
  const beginObject = (number: number) => {
    offsets[number] = cursor
    push(`${number} 0 obj\n`)
  }
  const endObject = () => push('endobj\n')

  const infoNumber = 3 + pages.length * 3
  const objectCount = infoNumber + 1
  const kids = pages.map((_, index) => `${3 + index * 3} 0 R`).join(' ')

  push('%PDF-1.4\n%âãÏÓ\n')

  beginObject(1)
  push('<< /Type /Catalog /Pages 2 0 R >>\n')
  endObject()

  beginObject(2)
  push(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>\n`)
  endObject()

  for (const [index, page] of pages.entries()) {
    const pageNumber = 3 + index * 3
    const imageNumber = pageNumber + 1
    const contentNumber = pageNumber + 2
    const [r, g, b] = hexToRgb(page.background)
    const content = [
      'q',
      `${fixed(r)} ${fixed(g)} ${fixed(b)} rg`,
      `0 0 ${fixed(page.pageWidth)} ${fixed(page.pageHeight)} re f`,
      'Q',
      'q',
      `${fixed(page.drawWidth)} 0 0 ${fixed(page.drawHeight)} ${fixed(page.drawX)} ${fixed(page.drawY)} cm`,
      '/Im0 Do',
      'Q',
    ].join('\n')

    beginObject(pageNumber)
    push(
      `<< /Type /Page /Parent 2 0 R ` +
        `/MediaBox [0 0 ${fixed(page.pageWidth)} ${fixed(page.pageHeight)}] ` +
        `/Resources << /XObject << /Im0 ${imageNumber} 0 R >> >> /Contents ${contentNumber} 0 R >>\n`,
    )
    endObject()

    beginObject(imageNumber)
    push(
      `<< /Type /XObject /Subtype /Image /Width ${page.pixelWidth} /Height ${page.pixelHeight} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.jpeg.length} >>\nstream\n`,
    )
    push(page.jpeg)
    push('\nendstream\n')
    endObject()

    beginObject(contentNumber)
    push(
      `<< /Length ${encoder.encode(content).length} >>\nstream\n${content}\nendstream\n`,
    )
    endObject()
  }

  beginObject(infoNumber)
  push(
    title
      ? `<< /Title <${pdfTextHex(title)}> /Producer (Kiwi) /Creator (Kiwi) >>\n`
      : '<< /Producer (Kiwi) /Creator (Kiwi) >>\n',
  )
  endObject()

  const xrefOffset = cursor
  push(`xref\n0 ${objectCount}\n`)
  push('0000000000 65535 f \n')
  for (let number = 1; number < objectCount; number += 1) {
    push(`${String(offsets[number]).padStart(10, '0')} 00000 n \n`)
  }
  push(
    `trailer\n<< /Size ${objectCount} /Root 1 0 R /Info ${infoNumber} 0 R >>\n` +
      `startxref\n${xrefOffset}\n%%EOF\n`,
  )

  return new Blob(chunks as BlobPart[], { type: 'application/pdf' })
}

/** 把一张 JPEG 封成单页 PDF（自动横竖向并居中）。 */
export function buildImagePdf(options: PdfImageOptions): Blob {
  const { jpeg, pixelWidth, pixelHeight } = options
  if (!jpeg.length || pixelWidth <= 0 || pixelHeight <= 0) {
    throw new Error('PDF 图像数据为空')
  }
  const landscape = pixelWidth >= pixelHeight
  const pageWidth = landscape ? PAGE_LONG : PAGE_SHORT
  const pageHeight = landscape ? PAGE_SHORT : PAGE_LONG
  const boxWidth = pageWidth - PAGE_MARGIN * 2
  const boxHeight = pageHeight - PAGE_MARGIN * 2
  const scale = Math.min(boxWidth / pixelWidth, boxHeight / pixelHeight)
  const drawWidth = pixelWidth * scale
  const drawHeight = pixelHeight * scale

  return writeImagePdf(
    [
      {
        jpeg,
        pixelWidth,
        pixelHeight,
        pageWidth,
        pageHeight,
        drawWidth,
        drawHeight,
        drawX: (pageWidth - drawWidth) / 2,
        drawY: (pageHeight - drawHeight) / 2,
        background: options.background ?? '#ffffff',
      },
    ],
    options.title,
  )
}

/**
 * 把多张与页面等比例的 JPEG 封成多页 PDF。
 * 文本笔记的 UI 截图按 A4（或 DOCX 纸张）切页后走这里，页面不额外留白。
 */
export function buildImagePdfPages(
  images: PdfPageImage[],
  options: PdfPagesOptions = {},
): Blob {
  const pageWidth = options.pageWidth ?? PAGE_SHORT
  const pageHeight = options.pageHeight ?? PAGE_LONG
  const background = options.background ?? '#ffffff'
  const pages = images.map((image) => {
    if (!image.jpeg.length || image.pixelWidth <= 0 || image.pixelHeight <= 0) {
      throw new Error('PDF 图像数据为空')
    }
    const scale = Math.min(
      pageWidth / image.pixelWidth,
      pageHeight / image.pixelHeight,
    )
    const drawWidth = image.pixelWidth * scale
    const drawHeight = image.pixelHeight * scale
    return {
      ...image,
      pageWidth,
      pageHeight,
      drawWidth,
      drawHeight,
      drawX: (pageWidth - drawWidth) / 2,
      drawY: (pageHeight - drawHeight) / 2,
      background,
    }
  })
  return writeImagePdf(pages, options.title)
}
