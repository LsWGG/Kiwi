/**
 * 画布文本设置里的字体族。
 *
 * @font-face 在 main.ts 全局声明（draw-fonts.css）。画布用 canvas 绘制文字，
 * 字体在首次选择后才下载，绘制好的文字不会像 DOM 一样自动重排；打开画布时
 * 先把这批字体预热好，用户切换字体就能立刻看到效果。
 */
export const DRAW_FONT_FAMILIES = [
  'SourceHanSansCN',
  'Montserrat',
  'Anton',
  'ClimateCrisis',
  'Exo',
  'Goldman',
  'DouYinSans',
  'SaDigitalNumber',
  'ZenTokyoZoo',
  'ZhuqueFangsong',
] as const

let preloadPromise: Promise<void> | null = null

export function preloadDrawFonts(): Promise<void> {
  if (preloadPromise) return preloadPromise
  if (typeof document === 'undefined' || !document.fonts?.load) return Promise.resolve()

  const sample = 'Aa 中文 0123'
  const loads = DRAW_FONT_FAMILIES.map((family) =>
    document.fonts.load(`20px "${family}"`, sample).catch(() => undefined),
  )
  const timeout = new Promise<void>((resolve) => {
    window.setTimeout(resolve, 2500)
  })
  preloadPromise = Promise.race([Promise.all(loads).then(() => undefined), timeout])
  return preloadPromise
}
