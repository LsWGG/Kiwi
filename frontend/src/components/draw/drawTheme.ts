/**
 * 画布运行时主题。
 *
 * jvs-draw 基于 Element Plus，弹层（下拉、取色器、形状库）会 teleport 到
 * body，甚至被 drawPopperLayer 提到 <html> 下，只能把主题类挂在 <html> 上，
 * 让正文和弹层都能继承 Kiwi 的 --kiwi-* 变量。用引用计数避免同页多个画布
 * 实例卸载时互相抢主题。
 */
let holders = 0

export function acquireDrawTheme() {
  holders += 1
  document.documentElement.classList.add('kiwi-draw-theme')
}

export function releaseDrawTheme() {
  holders = Math.max(0, holders - 1)
  if (holders === 0) document.documentElement.classList.remove('kiwi-draw-theme')
}
