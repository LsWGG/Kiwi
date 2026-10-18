import { onBeforeUnmount, onMounted } from 'vue'
import { toast } from '@/components/ui/toast'

/** Ctrl/Cmd + S 立即保存当前编辑器（拦截浏览器「保存网页」）。 */
export function useSaveShortcut(save: () => void | Promise<void>) {
  let running = false

  async function onKeydown(event: KeyboardEvent) {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
    event.preventDefault()
    if (running) return
    running = true
    try {
      await save()
      toast.success('已保存')
    } finally {
      running = false
    }
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
}
