/**
 * 「贴一贴 → 主窗口」的空间过渡。
 *
 * 把便签卡片本体克隆一份，沿卡片 → 主内容区的矩形连续放大。卡片内容只在
 * 放大初期短暂出现并迅速溶进纸面，避免被拉成巨幅文字；新页面开始进场后
 * 表面再淡出，把画面交还给真实页面。展开期间临时加速路由过渡，让页面
 * 尽早出现在表面之下，而不是“卡片消失 → 空白纸板 → 页面突然出现”。
 *
 * 表面挂在 <html> 下：body 有 --ui-scale 的 zoom，只有这里能直接使用
 * getBoundingClientRect() 得到的视口像素坐标。
 */

export interface WorkspaceExpandOptions {
  /** 正在打开的便签卡片；克隆它作为展开中的主窗口表面。 */
  card: HTMLElement
  /** 主内容区的视口矩形。 */
  to: DOMRect
  /** 层级：置于卡片之上，克隆接管后原卡片立即隐藏。 */
  zIndex: number
}

export interface WorkspaceExpandHandle {
  /** 新页面开始进场后调用：表面淡出。重复调用无效。 */
  reveal: () => void
}

/** 矩形形变时长。 */
const MORPH_MS = 420
/** 形变曲线：起步不僵、后段缓慢收尾。 */
const MORPH_EASING = 'cubic-bezier(0.25, 0.1, 0.2, 1)'
/** 表面淡出时长。 */
const FADE_MS = 240
/** 卡片内容溶解时长：放大后的文字不会被看清。 */
const CONTENT_FADE_MS = 260
/** 路由迟迟没有给出进场信号时的兜底。 */
const REVEAL_TIMEOUT_MS = 1200
/** 展开期间挂在 <html> 上，用于加速路由过渡（见 styles/main.css）。 */
const OPENING_CLASS = 'kiwi-sticky-expanding'

let openingCount = 0

function beginOpening(): void {
  openingCount += 1
  document.documentElement.classList.add(OPENING_CLASS)
}

function endOpening(): void {
  openingCount = Math.max(0, openingCount - 1)
  if (openingCount === 0) document.documentElement.classList.remove(OPENING_CLASS)
}

function readUiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const scale = Number.parseFloat(raw)
  return Number.isFinite(scale) && scale > 0 ? scale : 1
}

/**
 * 播放过渡。返回 null 表示无法接管动画，调用方按普通关闭处理即可。
 */
export function playWorkspaceExpand({
  card,
  to,
  zIndex,
}: WorkspaceExpandOptions): WorkspaceExpandHandle | null {
  const from = card.getBoundingClientRect()
  if (!(to.width > 0 && to.height > 0 && from.width > 0 && from.height > 0)) return null

  const uiScale = readUiScale()
  const dx = to.left - from.left
  const dy = to.top - from.top
  const scaleX = to.width / from.width
  const scaleY = to.height / from.height
  // 形变后的圆角会随 scale 放大；按最大缩放折算，视觉上保持在 14px 左右。
  const endRadius = Math.max(2, Math.min(12, 14 / Math.max(scaleX, scaleY)))

  beginOpening()

  const surface = document.createElement('div')
  surface.className = 'kiwi-workspace-expand'
  surface.setAttribute('aria-hidden', 'true')
  const style = surface.style
  style.position = 'fixed'
  style.left = `${from.left}px`
  style.top = `${from.top}px`
  style.width = `${from.width}px`
  style.height = `${from.height}px`
  style.zIndex = String(zIndex)
  style.pointerEvents = 'none'
  style.overflow = 'hidden'
  style.background = '#fff'
  // 圆角直接用终值：第一帧圆角由覆盖在上面的克隆提供，之后随 scale 自然放大。
  style.borderRadius = `${endRadius}px`
  style.boxShadow = '0 16px 44px -20px rgb(15 23 42 / 0.24)'
  style.transformOrigin = 'top left'
  // 只动 transform / opacity，避免路由挂载阻塞主线程时形变丢帧。
  style.willChange = 'transform, opacity'

  // 克隆卡片本体。卡片自带的弹入动画 / 过渡不能带到克隆上，
  // 否则展开的第一帧会从缩小状态重新弹一次。
  const clone = card.cloneNode(true) as HTMLElement
  clone.style.animation = 'none'
  clone.style.transition = 'none'
  clone.style.transform = 'none'
  clone.style.opacity = '1'
  clone.style.margin = '0'
  // 阴影由表面统一承担，避免卡片的旧阴影跟着内容一起放大。
  clone.style.boxShadow = 'none'
  surface.appendChild(clone)

  // 保持便签当前的滚动位置 / 画布画面，展开的第一帧与卡片完全一致。
  const sourceNodes = card.querySelectorAll<HTMLElement>('*')
  const cloneNodes = clone.querySelectorAll<HTMLElement>('*')
  sourceNodes.forEach((node, index) => {
    const copy = cloneNodes[index]
    if (!copy) return
    if (node.scrollTop || node.scrollLeft) {
      copy.scrollTop = node.scrollTop
      copy.scrollLeft = node.scrollLeft
    }
    if (node instanceof HTMLCanvasElement && copy instanceof HTMLCanvasElement) {
      copy.getContext('2d')?.drawImage(node, 0, 0)
    }
  })

  document.documentElement.appendChild(surface)

  // 形变只包含 transform，淡出只包含 opacity：两条动画都能在合成器上运行。
  const morph = surface.animate(
    [
      { transform: 'translate3d(0, 0, 0) scale(1, 1)' },
      {
        transform: `translate3d(${dx}px, ${dy}px, 0) scale(${scaleX}, ${scaleY})`,
      },
    ],
    { duration: MORPH_MS, easing: MORPH_EASING, fill: 'forwards' },
  )

  // 卡片内容在放大早期就溶解进纸面：文字不会被拉成巨幅，
  // 表面随后以干净的白纸继续展开，等待真实页面进场。
  clone.animate(
    [
      { opacity: 1, offset: 0, easing: 'linear' },
      { opacity: 1, offset: 0.09, easing: 'cubic-bezier(0.4, 0, 1, 1)' },
      // 必须显式写到 1，否则 WAAPI 会补一个“回到原值”的隐式关键帧，
      // 内容在淡出后又会慢慢浮现。
      { opacity: 0, offset: 1 },
    ],
    { duration: CONTENT_FADE_MS, fill: 'forwards' },
  )

  let cleaned = false
  let revealed = false
  let fade: Animation | null = null
  let revealTimer = 0
  let fallbackTimer = 0

  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    window.clearTimeout(revealTimer)
    window.clearTimeout(fallbackTimer)
    if (fade) {
      fade.removeEventListener('finish', cleanup)
      fade.removeEventListener('cancel', cleanup)
    }
    morph.cancel()
    surface.remove()
    endOpening()
  }

  const reveal = () => {
    if (revealed || cleaned) return
    revealed = true
    window.clearTimeout(revealTimer)
    fade = surface.animate(
      [
        { opacity: 1, offset: 0, easing: 'ease-out' },
        { opacity: 0, offset: 1 },
      ],
      { duration: FADE_MS, fill: 'forwards' },
    )
    fade.addEventListener('finish', cleanup)
    fade.addEventListener('cancel', cleanup)
    // 后台标签页里动画可能被节流，兜底保证表面不会永久留在 DOM 里。
    fallbackTimer = window.setTimeout(cleanup, FADE_MS + 400)
  }

  // 路由迟迟没有进场（例如资源加载失败）时也要把画面交还。
  revealTimer = window.setTimeout(reveal, REVEAL_TIMEOUT_MS)

  return { reveal }
}

/**
 * 等待主内容区挂载出新的路由页面，再交还画面。新页面插入 DOM 的那一刻
 * 已经渲染完毕（展开期间路由过渡被关闭，见 styles/main.css），由表面的
 * 淡出完成交接即可。同一路由不会重挂页面，调用方应直接 reveal。
 */
export function revealWhenPageEnters(handle: WorkspaceExpandHandle): void {
  const main = document.querySelector<HTMLElement>('[data-kiwi-main-content]')
  if (!main) {
    handle.reveal()
    return
  }

  let finished = false
  let fallback = 0
  let observer: MutationObserver | null = null
  const finish = () => {
    if (finished) return
    finished = true
    observer?.disconnect()
    window.clearTimeout(fallback)
    handle.reveal()
  }

  // 只认元素节点：路由离场开始时 Vue 会先插入注释占位符，
  // 那不是新页面，提前淡出会露出还在离场的旧页面。
  observer = new MutationObserver((records) => {
    const pageMounted = records.some((record) =>
      [...record.addedNodes].some((node) => node.nodeType === Node.ELEMENT_NODE),
    )
    if (pageMounted) finish()
  })
  observer.observe(main, { childList: true })
  fallback = window.setTimeout(finish, REVEAL_TIMEOUT_MS)
}

/** 调用方用它决定何时移除原便签；表面可能因路由较慢而更晚淡出。 */
export const WORKSPACE_EXPAND_DURATION = MORPH_MS + FADE_MS
