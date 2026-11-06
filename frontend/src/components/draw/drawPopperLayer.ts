/**
 * 画布弹层定位修复。
 *
 * Kiwi 在大屏上给 body 加了 `zoom: var(--ui-scale)`。Element Plus 默认把
 * `#el-popper-container-*` 挂在 body 下，floating-ui 算出的视口坐标会再被
 * body 的 zoom 放大一次，于是画布工具条上的形状面板 / 取色器 / 下拉菜单
 * 在 2K / 4K 屏上整体向右下漂移。
 *
 * 把容器移到 <html> 下（与 Kiwi 自己的浮层同一套做法）后，坐标按视口像素
 * 计算不再受 body zoom 影响；弹层主题变量挂在 html 上，见 drawTheme.ts。
 *
 * 容器由 Element Plus 在组件挂载时创建，所以用 MutationObserver 兜住后续
 * 新建的容器，避免第二次进入画布时又落回 body。
 */
const SELECTOR = '[id^="el-popper-container-"]'

let holders = 0
let observer: MutationObserver | null = null

function relocate(element: Element) {
  if (element.parentElement === document.documentElement) return
  document.documentElement.appendChild(element)
}

function sweep() {
  for (const element of document.querySelectorAll(SELECTOR)) relocate(element)
}

export function acquireDrawPopperLayer() {
  holders += 1
  if (holders > 1) return
  sweep()
  observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue
        if (node.matches(SELECTOR)) {
          relocate(node)
          continue
        }
        for (const element of node.querySelectorAll(SELECTOR)) relocate(element)
      }
    }
  })
  observer.observe(document.body, { childList: true })
}

export function releaseDrawPopperLayer() {
  holders = Math.max(0, holders - 1)
  if (holders > 0) return
  observer?.disconnect()
  observer = null
}
