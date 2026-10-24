import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { download, request } from '@/api/client'

/** 编辑器内置扩展组件（日期 / 公式 / 绘图 / 图册 / 分栏 / 日历 / 数据表 / 待办进度）。 */
export interface EditorExtension {
  key: string
  label: string
  hint: string
  icon: string
  group: string
  enabled: boolean
  /** 设置页只读预览使用的示例 Markdown。 */
  preview_markdown?: string
}

interface EditorExtensionsResponse {
  items: EditorExtension[]
  enabled: string[]
  disabled: string[]
}

export const useExtensionsStore = defineStore('editorExtensions', () => {
  const items = ref<EditorExtension[]>([])
  const loading = ref(false)
  const error = ref('')
  const loaded = ref(false)
  let loadPromise: Promise<void> | null = null

  const enabledItems = computed(() => items.value.filter((item) => item.enabled))
  const enabledCount = computed(() => enabledItems.value.length)
  const total = computed(() => items.value.length)

  /** 未加载时按启用处理，避免编辑器菜单在请求返回前短暂少项。 */
  function isEnabled(key: string): boolean {
    const item = items.value.find((entry) => entry.key === key)
    return item ? item.enabled : true
  }

  function apply(data: EditorExtensionsResponse) {
    items.value = data.items
    error.value = ''
    loaded.value = true
  }

  async function ensure(force = false): Promise<void> {
    if (loaded.value && !force) return
    if (loadPromise && !force) return loadPromise
    loading.value = true
    loadPromise = (async () => {
      try {
        apply(await request<EditorExtensionsResponse>('/editor/extensions'))
      } catch (e: any) {
        error.value = e.message || '加载扩展组件失败'
        throw e
      } finally {
        loading.value = false
        loadPromise = null
      }
    })()
    return loadPromise
  }

  async function saveDisabled(disabled: string[]) {
    apply(
      await request<EditorExtensionsResponse>('/editor/extensions', {
        method: 'PUT',
        body: JSON.stringify({ disabled }),
      }),
    )
  }

  /** 单组件切换：乐观更新，失败回滚。 */
  async function setEnabled(key: string, enabled: boolean) {
    const item = items.value.find((entry) => entry.key === key)
    if (!item || item.enabled === enabled) return
    const previous = item.enabled
    item.enabled = enabled
    try {
      const disabled = items.value.filter((entry) => !entry.enabled).map((entry) => entry.key)
      await saveDisabled(disabled)
    } catch (e) {
      item.enabled = previous
      throw e
    }
  }

  /** 批量启停：一次请求写入完整停用集合。 */
  async function setAllEnabled(enabled: boolean) {
    if (!items.value.length) return
    if (items.value.every((item) => item.enabled === enabled)) return
    const previous = items.value.map((item) => ({ item, enabled: item.enabled }))
    items.value.forEach((item) => {
      item.enabled = enabled
    })
    try {
      await saveDisabled(enabled ? [] : items.value.map((item) => item.key))
    } catch (e) {
      previous.forEach(({ item, enabled: value }) => {
        item.enabled = value
      })
      throw e
    }
  }

  /** 把单个内置组件导出为可参考的插件包（含 manifest / 预览样例 / 源码）。 */
  async function exportPackage(key: string) {
    const item = items.value.find((entry) => entry.key === key)
    return download(
      `/editor/extensions/${encodeURIComponent(key)}/export`,
      `kiwi-builtin-${item?.key || key}.zip`,
    )
  }

  /** 导出全部内置组件的参考包集合。 */
  async function exportAllPackages() {
    return download(
      '/editor/extensions/export',
      'kiwi-builtin-extensions.zip',
    )
  }

  return {
    items,
    loading,
    error,
    loaded,
    enabledItems,
    enabledCount,
    total,
    isEnabled,
    ensure,
    setEnabled,
    setAllEnabled,
    exportPackage,
    exportAllPackages,
  }
})
