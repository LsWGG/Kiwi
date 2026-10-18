import { onBeforeUnmount, watch, type Ref } from 'vue'

/**
 * 左右分屏按滚动比例联动：
 * - 以两边各自的 scrollTop / (scrollHeight - clientHeight) 作为唯一坐标，
 *   内容长度不同也能保持语义位置一致；
 * - 程序化滚动期间加锁，忽略目标容器回声，避免来回抖动。
 */
export function useSyncedScroll(
  left: Ref<HTMLElement | null>,
  right: Ref<HTMLElement | null>,
  enabled: Ref<boolean>,
) {
  let locked = false
  let releaseFrame = 0

  function mirror(source: HTMLElement, target: HTMLElement) {
    const sourceMax = source.scrollHeight - source.clientHeight
    const targetMax = target.scrollHeight - target.clientHeight
    if (sourceMax <= 0 || targetMax <= 0) return
    const next = (source.scrollTop / sourceMax) * targetMax
    if (Math.abs(target.scrollTop - next) < 1) return
    locked = true
    target.scrollTop = next
    // 程序化 scroll 事件会在下一帧前派发，双 rAF 后再解锁。
    cancelAnimationFrame(releaseFrame)
    releaseFrame = requestAnimationFrame(() => {
      releaseFrame = requestAnimationFrame(() => {
        locked = false
      })
    })
  }

  function onLeftScroll() {
    if (!enabled.value || locked) return
    const from = left.value
    const to = right.value
    if (from && to) mirror(from, to)
  }

  function onRightScroll() {
    if (!enabled.value || locked) return
    const from = right.value
    const to = left.value
    if (from && to) mirror(from, to)
  }

  let boundLeft: HTMLElement | null = null
  let boundRight: HTMLElement | null = null

  function detach() {
    if (boundLeft) boundLeft.removeEventListener('scroll', onLeftScroll)
    if (boundRight) boundRight.removeEventListener('scroll', onRightScroll)
    boundLeft = null
    boundRight = null
  }

  watch(
    [left, right, enabled],
    ([nextLeft, nextRight, active]) => {
      detach()
      if (!active) return
      if (nextLeft) {
        nextLeft.addEventListener('scroll', onLeftScroll, { passive: true })
        boundLeft = nextLeft
      }
      if (nextRight) {
        nextRight.addEventListener('scroll', onRightScroll, { passive: true })
        boundRight = nextRight
      }
    },
    { immediate: true, flush: 'post' },
  )

  onBeforeUnmount(() => {
    cancelAnimationFrame(releaseFrame)
    detach()
  })
}
