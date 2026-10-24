/**
 * 组件插件置顶：让设置页、预览弹窗与命令面板复用同一套「加载运行时 → 打开浮窗」
 * 逻辑，避免每个入口各写一遍默认 props 的解析。
 */
import { ref } from 'vue'
import {
  usePluginsStore,
  type Plugin,
  type PluginBlock,
  type PluginRuntimeBlock,
} from '@/stores/plugins'
import { usePluginWindowsStore } from '@/stores/pluginWindows'

export function usePinPlugin() {
  const plugins = usePluginsStore()
  const pluginWindows = usePluginWindowsStore()
  /** 正在加载运行时的区块 key，用于禁用重复点击。 */
  const pinningKey = ref('')

  function isPinned(pluginKey: string, blockType: string): boolean {
    return pluginWindows.isOpen(pluginKey, blockType)
  }

  function openRuntimeBlock(row: PluginRuntimeBlock): void {
    // 已置顶时只聚焦：不要把正在倒计时的浮窗重置回默认 props。
    if (isPinned(row.pluginKey, row.type)) {
      pluginWindows.focus(pluginWindows.windowId(row.pluginKey, row.type))
      return
    }
    pluginWindows.open({
      pluginKey: row.pluginKey,
      blockType: row.type,
      title: row.label || row.pluginName,
      icon: row.icon,
      props: { ...row.defaultProps },
    })
  }

  function toggleRuntimeBlock(row: PluginRuntimeBlock): boolean {
    if (isPinned(row.pluginKey, row.type)) {
      pluginWindows.close(pluginWindows.windowId(row.pluginKey, row.type))
      return false
    }
    openRuntimeBlock(row)
    return true
  }

  /** 设置页只有 manifest，按需加载该插件的运行时后再打开浮窗。 */
  async function toggleManifestBlock(plugin: Plugin, block: PluginBlock): Promise<boolean> {
    if (isPinned(plugin.key, block.type)) {
      pluginWindows.close(pluginWindows.windowId(plugin.key, block.type))
      return false
    }
    if (!plugin.enabled) throw new Error('请先启用插件')
    const key = `${plugin.key}:${block.type}`
    pinningKey.value = key
    try {
      await plugins.ensurePreviewRuntime(plugin.id)
      const row = plugins.getRuntimeBlock(plugin.key, block.type)
      if (!row) throw new Error('插件运行时尚未注册该区块')
      openRuntimeBlock(row)
      return true
    } finally {
      pinningKey.value = ''
    }
  }

  return {
    pinningKey,
    isPinned,
    openRuntimeBlock,
    toggleRuntimeBlock,
    toggleManifestBlock,
  }
}
