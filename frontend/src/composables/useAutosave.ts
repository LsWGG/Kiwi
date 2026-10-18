import { onBeforeUnmount, ref } from 'vue'

/**
 * 防抖 + 串行自动保存。
 * saveFn 内部自行处理错误提示；切换/离开页面前调用 flush() 或依赖卸载时兜底保存。
 */
export function useAutosave(saveFn: () => Promise<void>, delay = 800) {
  const saving = ref(false)
  const savedAt = ref('')
  /** 每次保存成功递增（同一分钟内的连续保存也能触发监听）。 */
  const revision = ref(0)
  let timer: number | null = null
  let dirty = false
  let running = false
  let queued = false

  function schedule() {
    dirty = true
    if (timer !== null) window.clearTimeout(timer)
    timer = window.setTimeout(() => void flush(), delay)
  }

  async function flush() {
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
    if (!dirty) return
    if (running) {
      queued = true
      return
    }
    running = true
    dirty = false
    saving.value = true
    try {
      await saveFn()
      savedAt.value = new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
      })
      revision.value += 1
    } catch {
      // 错误提示由 saveFn 负责；保留 dirty 以便下次输入重试
      dirty = true
    } finally {
      saving.value = false
      running = false
      if (queued) {
        queued = false
        dirty = true
        void flush()
      }
    }
  }

  function flushNow() {
    dirty = true
    return flush()
  }

  onBeforeUnmount(() => {
    if (timer !== null) window.clearTimeout(timer)
    if (dirty || queued) {
      // 卸载时尽力保存，不阻塞路由切换
      void saveFn()
    }
  })

  return { schedule, flush, flushNow, saving, savedAt, revision }
}
