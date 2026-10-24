import { ref, shallowRef, type Component } from 'vue'
import { defineStore } from 'pinia'
import { download, request, upload } from '@/api/client'
import { pluginHost } from '@/components/editor/plugins/host'

export type PluginKind = 'component'

export interface PluginBlock {
  key: string
  plugin_key: string
  plugin_name: string
  plugin_version: string
  type: string
  label: string
  icon: string
  description: string
  category: string
  kind: PluginKind
  template_markdown: string
  default_props: Record<string, unknown>
  /** manifest 声明可置顶为全局浮窗。 */
  pinnable: boolean
}

export interface Plugin {
  id: string
  key: string
  name: string
  version: string
  description: string
  author: string
  icon: string
  homepage: string
  enabled: boolean
  kind: PluginKind
  entry: string
  source: string
  has_script: boolean
  has_style: boolean
  script_size: number
  style_size: number
  script_url: string
  style_url: string
  blocks: PluginBlock[]
  created_at: string
  updated_at: string
}

export interface PluginInspection {
  kind: PluginKind
  key: string
  name: string
  version: string
  description: string
  entry: string
  style: string
  has_script: boolean
  has_style: boolean
  block_count: number
  blocks: string[]
}

export interface PluginSpec {
  manifest_version: number
  package: string
  rules: string[]
  fields: Record<string, string>
  example: Record<string, unknown>
  examples?: {
    component: Record<string, unknown>
  }
  skill?: string
  dev_kit_url?: string
  ai_prompt?: string
}

/** 已加载插件运行时注册的单个区块。 */
export interface PluginRuntimeBlock {
  key: string
  pluginId: string
  pluginKey: string
  pluginName: string
  type: string
  label: string
  icon: string
  description: string
  category: string
  component: Component
  defaultProps: Record<string, unknown>
  pinnable: boolean
}

type RuntimeSetup = (
  host: typeof pluginHost,
) =>
  | { blocks?: Record<string, any> }
  | Record<string, any>
  | void
  | Promise<{ blocks?: Record<string, any> } | Record<string, any> | void>

function errorText(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  return fallback
}

export const usePluginsStore = defineStore('plugins', () => {
  const plugins = ref<Plugin[]>([])
  const blocks = ref<PluginBlock[]>([])
  const loading = ref(false)
  const error = ref('')

  // 已加载的运行时区块：key = `<plugin key>:<type>`。使用 shallowRef，
  // 避免 Vue 深度代理第三方组件对象。
  const runtimeBlocks = shallowRef<Record<string, PluginRuntimeBlock>>({})
  const runtimeErrors = ref<Record<string, string>>({})
  const runtimeLoading = ref(false)
  const runtimeLoaded = ref(false)

  let listLoaded = false
  let listPromise: Promise<Plugin[]> | null = null
  let blocksLoaded = false
  let blocksPromise: Promise<void> | null = null
  let runtimePromise: Promise<void> | null = null
  const runtimeVersions = new Map<string, string>()
  const styleLinks = new Map<string, HTMLLinkElement>()

  async function ensureList(force = false): Promise<Plugin[]> {
    if (listLoaded && !force) return plugins.value
    if (listPromise && !force) return listPromise
    listPromise = (async () => {
      try {
        plugins.value = await request<Plugin[]>('/plugins')
        listLoaded = true
        return plugins.value
      } finally {
        listPromise = null
      }
    })()
    return listPromise
  }

  async function load() {
    loading.value = true
    error.value = ''
    try {
      await ensureList(true)
    } catch (e: any) {
      error.value = e.message || '加载插件失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  /** 编辑器懒加载区块；失败不阻塞编辑，下次再试。 */
  async function ensureBlocks(force = false): Promise<PluginBlock[]> {
    if (blocksLoaded && !force) return blocks.value
    if (blocksPromise && !force) {
      await blocksPromise
      return blocks.value
    }
    blocksPromise = (async () => {
      try {
        blocks.value = await request<PluginBlock[]>('/plugins/blocks')
        blocksLoaded = true
      } catch {
        // 插件服务不可用时编辑器照常使用内置区块。
      } finally {
        blocksPromise = null
      }
    })()
    await blocksPromise
    return blocks.value
  }

  function removeStyle(pluginId: string) {
    styleLinks.get(pluginId)?.remove()
    styleLinks.delete(pluginId)
  }

  function clearRuntime() {
    runtimeBlocks.value = {}
    runtimeErrors.value = {}
    runtimeLoaded.value = false
    runtimeLoading.value = false
    runtimePromise = null
    runtimeVersions.clear()
    for (const id of Array.from(styleLinks.keys())) removeStyle(id)
  }

  function invalidateBlocks() {
    blocksLoaded = false
    clearRuntime()
    void ensureBlocks(true)
  }

  function pluginEnabled(key: string): boolean {
    return plugins.value.find((plugin) => plugin.key === key)?.enabled === true
  }

  /** 编辑器 NodeView 只解析已启用插件的运行时。 */
  function getComponentBlock(
    pluginKey: string,
    type: string,
  ): PluginRuntimeBlock | undefined {
    const row = runtimeBlocks.value[`${pluginKey}:${type}`]
    return row && pluginEnabled(pluginKey) ? row : undefined
  }

  /** 预览允许读取已安装但暂时停用的插件运行时。 */
  function getRuntimeBlock(
    pluginKey: string,
    type: string,
  ): PluginRuntimeBlock | undefined {
    return runtimeBlocks.value[`${pluginKey}:${type}`]
  }

  async function ensurePluginStyle(plugin: Plugin): Promise<void> {
    if (!plugin.has_style || !plugin.style_url) return
    const existing = styleLinks.get(plugin.id)
    if (existing?.getAttribute('href') === plugin.style_url) return
    existing?.remove()
    await new Promise<void>((resolve) => {
      const link = document.createElement('link')
      let settled = false
      const done = () => {
        if (settled) return
        settled = true
        resolve()
      }
      link.rel = 'stylesheet'
      link.href = plugin.style_url
      link.dataset.kiwiPluginStyle = plugin.id
      link.addEventListener('load', done, { once: true })
      link.addEventListener('error', done, { once: true })
      document.head.appendChild(link)
      styleLinks.set(plugin.id, link)
      // 不因样式加载失败阻塞组件渲染。
      window.setTimeout(done, 1200)
    })
  }

  function normalizeSetupResult(
    result: Awaited<ReturnType<RuntimeSetup>>,
  ): Record<string, any> {
    if (!result || typeof result !== 'object') {
      throw new Error('setup(host) 没有返回区块注册表')
    }
    const raw = result as Record<string, any>
    const defs = raw.blocks && typeof raw.blocks === 'object' ? raw.blocks : raw
    if (!defs || typeof defs !== 'object' || Array.isArray(defs)) {
      throw new Error('setup(host) 的 blocks 必须是对象')
    }
    return defs
  }

  async function loadPluginRuntime(plugin: Plugin, force = false) {
    if (plugin.kind !== 'component' || !plugin.script_url) {
      throw new Error('该插件没有可执行入口')
    }
    const version = `${plugin.updated_at}:${plugin.script_url}`
    if (!force && runtimeVersions.get(plugin.id) === version) return
    const mod: any = await import(/* @vite-ignore */ plugin.script_url)
    const setup: RuntimeSetup | undefined =
      mod?.setup ??
      mod?.default?.setup ??
      (typeof mod?.default === 'function' ? mod.default : undefined)
    if (typeof setup !== 'function') {
      throw new Error('入口脚本必须导出 setup(host) 函数')
    }
    const result = await setup(pluginHost)
    const defs = normalizeSetupResult(result)
    const manifestByType = new Map(plugin.blocks.map((block) => [block.type, block]))
    const rows: PluginRuntimeBlock[] = []
    for (const [type, rawDef] of Object.entries(defs)) {
      if (!rawDef || typeof rawDef !== 'object') continue
      const def = rawDef as Record<string, any>
      // 兼容 { component } 与直接传 Vue 组件两种写法。
      const component = def.component ?? (def.render || def.setup ? def : null)
      if (!component) continue
      const manifestBlock = manifestByType.get(type)
      rows.push({
        key: `${plugin.key}:${type}`,
        pluginId: plugin.id,
        pluginKey: plugin.key,
        pluginName: plugin.name,
        type,
        label: String(manifestBlock?.label || def.label || type),
        icon: String(manifestBlock?.icon || def.icon || 'puzzle'),
        description: String(manifestBlock?.description || def.description || ''),
        category: String(manifestBlock?.category || '插件区块'),
        component: component as Component,
        defaultProps: {
          ...(manifestBlock?.default_props || {}),
          ...(def.defaultProps && typeof def.defaultProps === 'object'
            ? def.defaultProps
            : {}),
        },
        pinnable: manifestBlock?.pinnable === true,
      })
    }
    if (!rows.length) {
      throw new Error('插件没有注册任何可用区块')
    }
    const next = { ...runtimeBlocks.value }
    for (const [key, row] of Object.entries(next)) {
      if (row.pluginId === plugin.id) delete next[key]
    }
    for (const row of rows) next[row.key] = row
    runtimeBlocks.value = next
    runtimeVersions.set(plugin.id, version)
    await ensurePluginStyle(plugin)
  }

  /** 编辑器 / 阅读态加载所有已启用的组件插件。 */
  async function ensureComponentBlocks(force = false): Promise<void> {
    if (runtimeLoaded.value && !force) return
    if (runtimePromise && !force) return runtimePromise
    runtimePromise = (async () => {
      runtimeLoading.value = true
      try {
        await ensureList()
        const active = plugins.value.filter(
          (plugin) =>
            plugin.enabled &&
            plugin.kind === 'component' &&
            plugin.has_script &&
            plugin.script_url,
        )
        const errors: Record<string, string> = {}
        await Promise.all(
          active.map(async (plugin) => {
            try {
              await loadPluginRuntime(plugin, force)
            } catch (e) {
              errors[plugin.key] = errorText(e, '插件运行时加载失败')
            }
          }),
        )
        // 已卸载插件的旧错误一并清掉，保留当前启用插件的失败信息。
        runtimeErrors.value = errors
        runtimeLoaded.value = true
      } finally {
        runtimeLoading.value = false
        runtimePromise = null
      }
    })()
    return runtimePromise
  }

  /** 预览：按需加载单个插件，不受启用状态限制（停用插件不会自动加载）。 */
  async function ensurePreviewRuntime(pluginId: string): Promise<Plugin> {
    await ensureList()
    let plugin = plugins.value.find((item) => item.id === pluginId)
    if (!plugin) {
      plugin = await request<Plugin>(`/plugins/${pluginId}`)
      plugins.value = [...plugins.value, plugin]
    }
    if (plugin.kind !== 'component') return plugin
    try {
      await loadPluginRuntime(plugin)
      const next = { ...runtimeErrors.value }
      delete next[plugin.key]
      runtimeErrors.value = next
    } catch (e) {
      runtimeErrors.value = {
        ...runtimeErrors.value,
        [plugin.key]: errorText(e, '插件运行时加载失败'),
      }
      throw e
    }
    return plugin
  }

  async function update(id: string, patch: Record<string, unknown>) {
    const plugin = await request<Plugin>(`/plugins/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
    const index = plugins.value.findIndex((item) => item.id === id)
    if (index >= 0) plugins.value[index] = plugin
    invalidateBlocks()
    return plugin
  }

  async function remove(id: string) {
    await request<void>(`/plugins/${id}`, { method: 'DELETE' })
    plugins.value = plugins.value.filter((item) => item.id !== id)
    removeStyle(id)
    invalidateBlocks()
  }

  async function inspectFile(file: File): Promise<PluginInspection> {
    const form = new FormData()
    form.append('file', file)
    return upload<PluginInspection>('/plugins/inspect', form)
  }

  async function importFile(file: File, overwrite = false) {
    const form = new FormData()
    form.append('file', file)
    const suffix = overwrite ? '?overwrite=true' : ''
    const plugin = await upload<Plugin>(`/plugins/import${suffix}`, form)
    await load()
    invalidateBlocks()
    return plugin
  }

  async function exportPlugin(id: string) {
    const plugin = plugins.value.find((item) => item.id === id)
    return download(
      `/plugins/${id}/export`,
      `${plugin?.key || 'plugin'}-${plugin?.version || '1.0.0'}.zip`,
    )
  }

  async function downloadDevKit() {
    return download('/plugins/dev-kit', 'kiwi-plugin-dev-kit.zip')
  }

  async function spec() {
    return request<PluginSpec>('/plugins/spec')
  }

  return {
    plugins,
    blocks,
    loading,
    error,
    runtimeBlocks,
    runtimeErrors,
    runtimeLoading,
    runtimeLoaded,
    load,
    ensureList,
    ensureBlocks,
    ensureComponentBlocks,
    ensurePreviewRuntime,
    getComponentBlock,
    getRuntimeBlock,
    update,
    remove,
    inspectFile,
    importFile,
    exportPlugin,
    downloadDevKit,
    spec,
  }
})
