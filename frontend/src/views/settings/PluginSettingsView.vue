<script setup lang="ts">
/** 组件插件：预览、导入导出、启停与元信息维护。 */
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiConfirm from '@/components/ui/KiwiConfirm.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import PluginPreviewDialog from '@/components/settings/PluginPreviewDialog.vue'
import PluginPinMenu from '@/components/settings/PluginPinMenu.vue'
import { toast } from '@/components/ui/toast'
import {
  usePluginsStore,
  type Plugin,
  type PluginBlock,
  type PluginInspection,
  type PluginSpec,
} from '@/stores/plugins'
import { useExtensionsStore, type EditorExtension } from '@/stores/extensions'

// 阅读视图体积较大，仅在首次打开内置组件预览时加载。
const BuiltinExtensionPreviewDialog = defineAsyncComponent(
  () => import('@/components/settings/BuiltinExtensionPreviewDialog.vue'),
)

const plugins = usePluginsStore()
const extensions = useExtensionsStore()

interface PluginDraft {
  id: string
  key: string
  name: string
  version: string
  description: string
  author: string
  icon: string
  homepage: string
}

function emptyDraft(): PluginDraft {
  return {
    id: '',
    key: '',
    name: '',
    version: '1.0.0',
    description: '',
    author: '',
    icon: 'puzzle',
    homepage: '',
  }
}

const loading = ref(true)
const busy = ref(false)
const togglingAll = ref(false)
const extensionsBusy = ref(false)
const draft = ref<PluginDraft>(emptyDraft())
const editorOpen = ref(false)
const specOpen = ref(false)
const spec = ref<PluginSpec | null>(null)
const importing = ref(false)
const overwrite = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const removing = ref<Plugin | null>(null)
const expanded = ref<Set<string>>(new Set())
const previewPlugin = ref<Plugin | null>(null)
const previewBuiltin = ref<EditorExtension | null>(null)
const exporting = ref('')
const builtinExporting = ref('')
const devKitBusy = ref(false)
const pendingFile = ref<File | null>(null)
const inspection = ref<PluginInspection | null>(null)

const isEdit = computed(() => !!draft.value.id)
const blockCount = computed(() =>
  plugins.plugins.reduce((sum, item) => sum + item.blocks.length, 0),
)
const enabledCount = computed(
  () => plugins.plugins.filter((item) => item.enabled).length,
)
const activeExample = computed(
  () => spec.value?.examples?.component ?? spec.value?.example ?? {},
)
const specFields = computed(() => Object.entries(spec.value?.fields ?? {}))

onMounted(async () => {
  // 规范与列表并行加载：打开「开发规范」弹窗时无需再等待。
  void plugins
    .spec()
    .then((value) => {
      spec.value = value
    })
    .catch(() => {})
  // 内置扩展组件与组件插件并行加载，互不阻塞。
  void extensions
    .ensure(true)
    .catch((e: any) => toast.error(e.message || '加载扩展组件失败'))
  try {
    await plugins.load()
  } catch (e: any) {
    toast.error(e.message || '加载插件失败')
  } finally {
    loading.value = false
  }
})

function toggleExpanded(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function openPreview(plugin: Plugin) {
  previewPlugin.value = plugin
}

function openEdit(plugin: Plugin) {
  draft.value = {
    id: plugin.id,
    key: plugin.key,
    name: plugin.name,
    version: plugin.version,
    description: plugin.description,
    author: plugin.author,
    icon: plugin.icon || 'puzzle',
    homepage: plugin.homepage,
  }
  editorOpen.value = true
}

async function savePlugin() {
  if (!draft.value.name.trim()) {
    toast.error('请填写插件名称')
    return
  }
  busy.value = true
  try {
    await plugins.update(draft.value.id, {
      name: draft.value.name.trim(),
      version: draft.value.version.trim(),
      description: draft.value.description.trim(),
      author: draft.value.author.trim(),
      icon: draft.value.icon.trim() || 'puzzle',
      homepage: draft.value.homepage.trim(),
    })
    toast.success('插件信息已更新')
    editorOpen.value = false
  } catch (e: any) {
    toast.error(e.message || '保存插件失败')
  } finally {
    busy.value = false
  }
}

async function toggleEnabled(plugin: Plugin) {
  try {
    await plugins.update(plugin.id, { enabled: !plugin.enabled })
    toast.success(plugin.enabled ? '插件已停用' : '插件已启用')
  } catch (e: any) {
    toast.error(e.message || '切换插件状态失败')
  }
}

/** 批量启停：逐个更新以复用单插件的校验与区块缓存刷新。 */
async function setAllEnabled(enabled: boolean) {
  const targets = plugins.plugins.filter((plugin) => plugin.enabled !== enabled)
  if (!targets.length || togglingAll.value) return
  togglingAll.value = true
  try {
    for (const plugin of targets) {
      await plugins.update(plugin.id, { enabled })
    }
    toast.success(enabled ? '已启用全部插件' : '已停用全部插件')
  } catch (e: any) {
    toast.error(e.message || '批量切换插件状态失败')
  } finally {
    togglingAll.value = false
  }
}

/** 内置扩展组件：停用后编辑器工具栏与斜杠菜单同步隐藏。 */
async function toggleExtension(item: EditorExtension) {
  if (extensionsBusy.value) return
  const next = !item.enabled
  extensionsBusy.value = true
  try {
    await extensions.setEnabled(item.key, next)
    toast.success(next ? `已启用「${item.label}」` : `已停用「${item.label}」`)
  } catch (e: any) {
    toast.error(e.message || '切换扩展组件失败')
  } finally {
    extensionsBusy.value = false
  }
}

function retryExtensions() {
  void extensions
    .ensure(true)
    .catch((e: any) => toast.error(e.message || '加载扩展组件失败'))
}

async function setAllExtensions(enabled: boolean) {
  if (extensionsBusy.value) return
  extensionsBusy.value = true
  try {
    await extensions.setAllEnabled(enabled)
    toast.success(enabled ? '已启用全部扩展组件' : '已停用全部扩展组件')
  } catch (e: any) {
    toast.error(e.message || '批量切换扩展组件失败')
  } finally {
    extensionsBusy.value = false
  }
}

async function exportBuiltin(key: string) {
  if (builtinExporting.value) return
  builtinExporting.value = key
  try {
    const filename = await extensions.exportPackage(key)
    toast.success(`已导出 ${filename}`)
  } catch (e: any) {
    toast.error(e.message || '导出内置组件失败')
  } finally {
    builtinExporting.value = ''
  }
}

async function exportAllBuiltins() {
  if (builtinExporting.value) return
  builtinExporting.value = '__all__'
  try {
    const filename = await extensions.exportAllPackages()
    toast.success(`已导出 ${filename}`)
  } catch (e: any) {
    toast.error(e.message || '导出内置组件失败')
  } finally {
    builtinExporting.value = ''
  }
}

async function exportPluginRow(plugin: Plugin) {
  if (exporting.value) return
  exporting.value = plugin.id
  try {
    const filename = await plugins.exportPlugin(plugin.id)
    toast.success(`已导出 ${filename}`)
  } catch (e: any) {
    toast.error(e.message || '导出插件失败')
  } finally {
    exporting.value = ''
  }
}

async function confirmRemove() {
  const plugin = removing.value
  if (!plugin) return
  removing.value = null
  try {
    await plugins.remove(plugin.id)
    if (previewPlugin.value?.id === plugin.id) previewPlugin.value = null
    toast.success('插件已删除')
  } catch (e: any) {
    toast.error(e.message || '删除插件失败')
  }
}

function pickFile() {
  fileInput.value?.click()
}

/** 导入先预检：确认第三方代码来源后才落库。 */
async function onFileChosen(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importing.value = true
  try {
    inspection.value = await plugins.inspectFile(file)
    pendingFile.value = file
  } catch (e: any) {
    toast.error(e.message || '插件包解析失败')
  } finally {
    importing.value = false
  }
}

function closeInspection() {
  pendingFile.value = null
  inspection.value = null
}

async function confirmImport() {
  const file = pendingFile.value
  if (!file || importing.value) return
  importing.value = true
  try {
    const plugin = await plugins.importFile(file, overwrite.value)
    closeInspection()
    toast.success(`已导入「${plugin.name}」 v${plugin.version}`)
    // 导入后立即打开预览，确认效果符合预期。
    previewPlugin.value = plugin
  } catch (e: any) {
    toast.error(e.message || '导入插件失败')
  } finally {
    importing.value = false
  }
}

async function getDevKit() {
  if (devKitBusy.value) return
  devKitBusy.value = true
  try {
    const filename = await plugins.downloadDevKit()
    toast.success(`已下载 ${filename}`)
  } catch (e: any) {
    toast.error(e.message || '下载开发套件失败')
  } finally {
    devKitBusy.value = false
  }
}

async function openSpec() {
  specOpen.value = true
  if (spec.value) return
  try {
    spec.value = await plugins.spec()
  } catch (e: any) {
    toast.error(e.message || '加载开发规范失败')
  }
}

async function copyText(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value)
    toast.success(`${label}已复制`)
  } catch {
    toast.error('复制失败，请手动选择文本')
  }
}

function copyExample() {
  if (!spec.value) return
  void copyText(JSON.stringify(activeExample.value, null, 2), '示例 manifest ')
}

function copyAiPrompt() {
  if (!spec.value?.ai_prompt) return
  void copyText(spec.value.ai_prompt, 'AI 提示词')
}

function blockSummary(block: PluginBlock) {
  return `${block.label} · ${block.type}`
}

function formatSize(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

function hasProps(block: PluginBlock) {
  return Object.keys(block.default_props || {}).length > 0
}
</script>

<template>
  <div class="page-wrap-slim px-4 py-6 sm:px-8 sm:py-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-slate-500 to-kiwi-600 text-white shadow-glow"
        >
          <KiwiIcon name="puzzle" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">插件与区块</h1>
          <p class="mt-1 text-sm text-slate-500">
            管理编辑器内置扩展组件，以及可预览、可导入导出的组件插件。
          </p>
        </div>
      </div>
      <div class="grid w-full grid-cols-3 gap-1.5 sm:flex sm:w-auto sm:flex-wrap sm:items-center sm:gap-2">
        <button
          class="kiwi-btn-ghost justify-center whitespace-nowrap !px-1 sm:!px-3.5"
          @click="openSpec"
        >
          <span class="hidden sm:inline-flex"><KiwiIcon name="file" :size="14" /></span>
          开发规范
        </button>
        <button
          class="kiwi-btn-ghost justify-center whitespace-nowrap !px-1 sm:!px-3.5"
          :disabled="devKitBusy"
          @click="getDevKit"
        >
          <span class="hidden sm:inline-flex">
            <KiwiIcon :name="devKitBusy ? 'loader' : 'download'" :size="14" :spin="devKitBusy" />
          </span>
          开发套件
        </button>
        <button
          class="kiwi-btn-ghost justify-center whitespace-nowrap !px-1 sm:!px-3.5"
          :disabled="importing"
          @click="pickFile"
        >
          <span class="hidden sm:inline-flex">
            <KiwiIcon :name="importing ? 'loader' : 'fileImport'" :size="14" :spin="importing" />
          </span>
          {{ importing ? '解析中…' : '导入插件' }}
        </button>
      </div>
    </div>

    <SettingsTabs />

    <!-- 内置扩展组件：与编辑器「+ → 扩展组件」和斜杠菜单联动 -->
    <section class="mb-5 animate-fade-up rounded-2xl glass-strong p-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex items-center gap-2.5">
          <span class="grid h-8 w-8 place-items-center rounded-lg bg-kiwi-50 text-kiwi-500">
            <KiwiIcon name="layoutTemplate" :size="16" />
          </span>
          <div>
            <h2 class="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-slate-800">
              内置扩展组件
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-normal text-slate-500">
                已启用 {{ extensions.enabledCount }} / {{ extensions.total }}
              </span>
            </h2>
            <p class="mt-0.5 text-[11px] leading-relaxed text-slate-500">
              控制编辑器「+ → 扩展组件」与斜杠菜单中的内置区块；可导出为插件包，作为开发参考。
            </p>
          </div>
        </div>
        <div class="flex w-full flex-wrap items-center gap-1 sm:ml-auto sm:w-auto">
          <button
            class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2"
            :disabled="extensionsBusy || !extensions.total || extensions.enabledCount === extensions.total"
            @click="setAllExtensions(true)"
          >
            <KiwiIcon name="check" :size="11" /> 全部启用
          </button>
          <button
            class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2"
            :disabled="extensionsBusy || !extensions.total || extensions.enabledCount === 0"
            @click="setAllExtensions(false)"
          >
            <KiwiIcon name="close" :size="11" /> 全部停用
          </button>
          <button
            class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2"
            :disabled="!!builtinExporting || !extensions.total"
            title="导出全部内置组件参考包"
            @click="exportAllBuiltins"
          >
            <KiwiIcon
              :name="builtinExporting === '__all__' ? 'loader' : 'fileExport'"
              :size="11"
              :spin="builtinExporting === '__all__'"
            />
            全部导出
          </button>
        </div>
      </div>

      <div
        v-if="extensions.loading && !extensions.loaded"
        class="py-8 text-center text-[11.5px] text-slate-400"
      >
        <KiwiIcon name="loader" :size="16" :spin="true" class="inline-block" />
        读取扩展组件…
      </div>
      <div
        v-else-if="extensions.error && !extensions.loaded"
        class="mt-3 rounded-xl border border-rose-100 bg-rose-50/60 px-3 py-2 text-[11.5px] text-rose-500"
      >
        {{ extensions.error }}
        <button class="ml-1 underline" @click="retryExtensions">重试</button>
      </div>
      <div v-else class="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="item in extensions.items"
          :key="item.key"
          class="flex items-center gap-2.5 rounded-xl border border-slate-200/70 bg-white/55 px-3 py-2 transition-colors"
          :class="item.enabled ? '' : 'opacity-60'"
        >
          <span
            class="grid h-7 w-7 shrink-0 place-items-center rounded-lg"
            :class="item.enabled ? 'bg-kiwi-50 text-kiwi-600' : 'bg-slate-100 text-slate-400'"
          >
            <KiwiIcon :name="item.icon" :size="13" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-[12px] font-medium text-slate-700">{{ item.label }}</p>
            <p class="truncate text-[10.5px] text-slate-400">{{ item.hint }}</p>
          </div>
          <button
            type="button"
            class="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-kiwi-600"
            :title="`预览「${item.label}」`"
            @click="previewBuiltin = item"
          >
            <KiwiIcon name="eye" :size="13" />
          </button>
          <button
            type="button"
            class="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-kiwi-600 disabled:opacity-50"
            :disabled="!!builtinExporting"
            :title="`导出「${item.label}」插件包`"
            @click="exportBuiltin(item.key)"
          >
            <KiwiIcon
              :name="builtinExporting === item.key ? 'loader' : 'fileExport'"
              :size="13"
              :spin="builtinExporting === item.key"
            />
          </button>
          <button
            type="button"
            role="switch"
            :aria-checked="item.enabled"
            :disabled="extensionsBusy"
            class="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-70"
            :class="item.enabled ? 'bg-kiwi-500' : 'bg-slate-300'"
            :title="item.enabled ? `停用${item.label}` : `启用${item.label}`"
            @click="toggleExtension(item)"
          >
            <span
              class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
              :class="item.enabled ? 'left-[18px]' : 'left-0.5'"
            />
          </button>
        </div>
      </div>
    </section>

    <div class="mb-2 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 class="text-[14px] font-semibold text-slate-800">组件插件</h2>
        <p class="text-[11px] text-slate-500">
          组件插件以 zip 包提供 JavaScript / Vue 区块，效果与内置组件一致。声明
          <code class="rounded bg-slate-100 px-1">pinnable</code>
          的区块可从卡片「置顶」直接放到全局浮窗，无需插入笔记。
        </p>
      </div>
    </div>

    <div
      class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-slate-200/70 bg-white/50 px-4 py-2.5 text-[11.5px] text-slate-500"
    >
      <span>共 {{ plugins.plugins.length }} 个组件插件</span>
      <span class="text-slate-300">·</span>
      <span>已启用 {{ enabledCount }} 个</span>
      <span class="text-slate-300">·</span>
      <span>{{ blockCount }} 个区块</span>
      <div class="flex w-full flex-wrap items-center gap-1 sm:ml-auto sm:w-auto sm:justify-end">
        <button
          class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2"
          :disabled="togglingAll || !plugins.plugins.length || enabledCount === plugins.plugins.length"
          @click="setAllEnabled(true)"
        >
          <KiwiIcon name="check" :size="11" /> 全部启用
        </button>
        <button
          class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2"
          :disabled="togglingAll || !plugins.plugins.length || enabledCount === 0"
          @click="setAllEnabled(false)"
        >
          <KiwiIcon name="close" :size="11" /> 全部停用
        </button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".zip,application/zip"
        class="hidden"
        @change="onFileChosen"
      />
    </div>

    <div v-if="loading" class="py-16 text-center text-sm text-slate-400">
      <KiwiIcon name="loader" :size="18" :spin="true" class="inline-block" />
      读取插件…
    </div>

    <div
      v-else-if="!plugins.plugins.length"
      class="rounded-2xl glass-strong px-6 py-14 text-center"
    >
      <div class="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-kiwi-50 text-kiwi-500">
        <KiwiIcon name="puzzle" :size="22" />
      </div>
      <h3 class="text-sm font-semibold text-slate-700">还没有组件插件</h3>
      <p class="mx-auto mt-1 max-w-md text-xs leading-relaxed text-slate-500">
        组件插件用 zip 打包 JavaScript / Vue 组件，导入前会先解析并展示插件信息，
        并提示第三方代码执行风险。可在开发规范中下载示例与开发套件。
      </p>
      <button class="kiwi-btn-primary mt-4" @click="pickFile">
        <KiwiIcon name="fileImport" :size="14" /> 导入第一个组件插件
      </button>
    </div>

    <div v-else class="space-y-3">
      <section
        v-for="plugin in plugins.plugins"
        :key="plugin.id"
        class="animate-fade-up rounded-2xl glass-strong p-4"
      >
        <div class="flex flex-wrap items-start gap-3">
          <span
            class="grid h-10 w-10 shrink-0 place-items-center rounded-xl"
            :class="plugin.enabled ? 'bg-kiwi-50 text-kiwi-600' : 'bg-slate-100 text-slate-400'"
          >
            <KiwiIcon :name="plugin.icon || 'puzzle'" :size="19" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="text-[14px] font-semibold text-slate-800">{{ plugin.name }}</h2>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                v{{ plugin.version }}
              </span>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-500">
                {{ plugin.key }}
              </span>
              <span
                class="rounded-full px-2 py-0.5 text-[10px]"
                :class="plugin.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'"
              >
                {{ plugin.enabled ? '已启用' : '已停用' }}
              </span>
              <span
                v-if="plugin.source === 'import'"
                class="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-600"
              >
                导入
              </span>
            </div>
            <p v-if="plugin.description" class="mt-1 text-xs leading-relaxed text-slate-500">
              {{ plugin.description }}
            </p>
            <p class="mt-1 text-[10.5px] text-slate-400">
              <code class="rounded bg-slate-100 px-1">{{ plugin.entry || 'index.js' }}</code>
              · 脚本 {{ formatSize(plugin.script_size) }}
              <template v-if="plugin.has_style"> · 样式 {{ formatSize(plugin.style_size) }}</template>
              · 运行时按需加载
            </p>
            <div class="mt-2 flex flex-wrap items-center gap-1.5">
              <span
                v-for="block in plugin.blocks"
                :key="block.key"
                class="rounded-md border border-slate-200/80 bg-white/70 px-1.5 py-0.5 text-[10.5px] text-slate-500"
                :title="block.description"
              >
                {{ blockSummary(block) }}
              </span>
              <span v-if="!plugin.blocks.length" class="text-[10.5px] text-slate-400">
                未定义区块
              </span>
            </div>
            <p v-if="plugin.author" class="mt-1.5 text-[10.5px] text-slate-400">
              {{ plugin.author }}
              <a
                v-if="plugin.homepage"
                :href="plugin.homepage"
                target="_blank"
                rel="noreferrer"
                class="ml-1 text-kiwi-500 hover:underline"
              >主页</a>
            </p>
          </div>
          <div
            class="flex w-full flex-wrap items-center justify-end gap-1.5 border-t border-slate-200/60 pt-2 sm:w-auto sm:shrink-0 sm:border-0 sm:pt-0"
          >
            <PluginPinMenu :plugin="plugin" />
            <button
              class="kiwi-btn-ghost !px-2 !py-1.5"
              title="预览插件效果"
              @click="openPreview(plugin)"
            >
              <KiwiIcon name="eye" :size="13" />
            </button>
            <button
              class="kiwi-btn-ghost !px-2 !py-1.5"
              :disabled="!!exporting"
              :title="`导出「${plugin.name}」插件包`"
              @click="exportPluginRow(plugin)"
            >
              <KiwiIcon
                :name="exporting === plugin.id ? 'loader' : 'fileExport'"
                :size="13"
                :spin="exporting === plugin.id"
              />
            </button>
            <button
              type="button"
              role="switch"
              :aria-checked="plugin.enabled"
              class="relative h-5 w-9 rounded-full transition-colors"
              :class="plugin.enabled ? 'bg-kiwi-500' : 'bg-slate-300'"
              :title="plugin.enabled ? '停用插件' : '启用插件'"
              @click="toggleEnabled(plugin)"
            >
              <span
                class="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
                :class="plugin.enabled ? 'left-[18px]' : 'left-0.5'"
              />
            </button>
            <button
              class="kiwi-btn-ghost !px-2 !py-1.5"
              title="编辑插件信息"
              @click="openEdit(plugin)"
            >
              <KiwiIcon name="edit" :size="13" />
            </button>
            <button
              class="kiwi-btn-ghost !px-2 !py-1.5"
              title="查看区块与默认属性"
              @click="toggleExpanded(plugin.id)"
            >
              <KiwiIcon :name="expanded.has(plugin.id) ? 'chevronsUp' : 'chevronsDown'" :size="13" />
            </button>
            <button
              class="kiwi-btn-ghost !px-2 !py-1.5 text-rose-500"
              title="删除插件"
              @click="removing = plugin"
            >
              <KiwiIcon name="trash" :size="13" />
            </button>
          </div>
        </div>

        <div v-if="expanded.has(plugin.id)" class="mt-3 space-y-2 border-t border-slate-200/70 pt-3">
          <div
            v-for="block in plugin.blocks"
            :key="block.key"
            class="rounded-xl border border-slate-200/70 bg-white/60 p-3"
          >
            <div class="flex items-center gap-2 text-xs font-medium text-slate-700">
              <KiwiIcon :name="block.icon || 'puzzle'" :size="13" class="text-kiwi-500" />
              {{ block.label }}
              <code class="text-[10px] text-slate-400">{{ block.key }}</code>
              <span class="ml-auto text-[10px] text-slate-400">{{ block.category }}</span>
            </div>
            <div class="mt-2">
              <p class="text-[10.5px] text-slate-400">
                默认属性（插入区块时写入 Markdown，可在编辑器内修改）
              </p>
              <pre
                v-if="hasProps(block)"
                class="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-2 text-[10.5px] leading-relaxed text-slate-600"
              >{{ JSON.stringify(block.default_props, null, 2) }}</pre>
              <p v-else class="mt-1 text-[10.5px] text-slate-400">无默认属性，由组件自行初始化。</p>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 编辑插件元信息（代码与区块由 zip 包定义） -->
    <KiwiModal
      :open="editorOpen"
      title="编辑组件插件"
      max-w="max-w-2xl"
      @close="editorOpen = false"
    >
      <div class="space-y-4">
        <div class="grid gap-3 md:grid-cols-2">
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">插件 key</span>
            <input v-model="draft.key" disabled class="kiwi-input font-mono" />
            <span class="mt-1 block text-[10px] text-slate-400">
              全局唯一 slug，创建后不可修改
            </span>
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">名称</span>
            <input v-model="draft.name" class="kiwi-input" placeholder="组件插件名称" />
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">版本</span>
            <input v-model="draft.version" class="kiwi-input font-mono" placeholder="1.0.0" />
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">图标</span>
            <input v-model="draft.icon" class="kiwi-input font-mono" placeholder="puzzle" />
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">作者</span>
            <input v-model="draft.author" class="kiwi-input" placeholder="可选" />
          </label>
          <label class="block">
            <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">主页</span>
            <input v-model="draft.homepage" class="kiwi-input" placeholder="https://（可选）" />
          </label>
        </div>
        <label class="block">
          <span class="mb-1.5 block text-[11.5px] font-medium text-slate-600">简介</span>
          <textarea v-model="draft.description" rows="2" class="kiwi-input resize-y" />
        </label>
        <p class="rounded-xl bg-slate-50 px-3 py-2 text-[10.5px] leading-relaxed text-slate-500">
          组件插件的区块、默认属性与执行入口由 zip 包定义，此处仅编辑元信息。
          如需更新代码，请重新打包并导入（可勾选覆盖同 key 插件）。
        </p>

        <div class="flex justify-end gap-2 pt-1">
          <button class="kiwi-btn-ghost" @click="editorOpen = false">取消</button>
          <button class="kiwi-btn-primary" :disabled="busy" @click="savePlugin">
            <KiwiIcon :name="busy ? 'loader' : 'check'" :size="14" :spin="busy" />
            {{ busy ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 导入预检：先解析包并展示信息，确认后才执行第三方代码安装 -->
    <KiwiModal
      :open="!!inspection && !!pendingFile"
      title="导入组件插件"
      max-w="max-w-xl"
      @close="closeInspection"
    >
      <div v-if="inspection" class="space-y-4">
        <div class="flex items-start gap-3">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-kiwi-50 text-kiwi-600">
            <KiwiIcon name="puzzle" :size="19" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-[14px] font-semibold text-slate-800">{{ inspection.name }}</h3>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                v{{ inspection.version }}
              </span>
              <span class="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] text-violet-600">
                组件插件
              </span>
            </div>
            <p v-if="inspection.description" class="mt-1 text-[11.5px] leading-relaxed text-slate-500">
              {{ inspection.description }}
            </p>
            <p class="mt-1 text-[10.5px] text-slate-400">
              文件 {{ pendingFile?.name }} · key <code class="rounded bg-slate-100 px-1">{{ inspection.key }}</code>
            </p>
          </div>
        </div>

        <div class="grid gap-2 rounded-xl border border-slate-200/80 bg-white/60 px-3 py-2.5 text-[11px] text-slate-500 sm:grid-cols-2">
          <span>
            区块：<strong class="font-medium text-slate-700">{{ inspection.block_count }}</strong> 个
          </span>
          <span>
            入口：<code class="rounded bg-slate-100 px-1">{{ inspection.entry || 'index.js' }}</code>
          </span>
          <span v-if="inspection.has_style">包含样式文件</span>
        </div>

        <div v-if="inspection.blocks.length" class="flex flex-wrap gap-1.5">
          <span
            v-for="label in inspection.blocks"
            :key="label"
            class="rounded-md border border-slate-200/80 bg-white/70 px-1.5 py-0.5 text-[10.5px] text-slate-500"
          >
            {{ label }}
          </span>
        </div>

        <div class="rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2.5">
          <p class="flex items-center gap-1.5 text-[11.5px] font-medium text-amber-700">
            <KiwiIcon name="shield" :size="13" /> 第三方代码执行提示
          </p>
          <p class="mt-1 text-[10.5px] leading-relaxed text-amber-700/90">
            组件插件包含可执行 JavaScript，导入并启用后会在你的浏览器中运行，可以访问当前页面数据并修改区块内容。
            请只导入来源可信的插件包；停用或删除插件后，已保存的区块会降级为静态卡片，Markdown 数据不会丢失。
          </p>
        </div>

        <label class="flex cursor-pointer items-center gap-2 text-[11.5px] text-slate-600">
          <input v-model="overwrite" type="checkbox" class="h-3.5 w-3.5 accent-kiwi-600" />
          覆盖同 key 插件（保留原有启用状态）
        </label>

        <div class="flex justify-end gap-2">
          <button class="kiwi-btn-ghost" @click="closeInspection">取消</button>
          <button class="kiwi-btn-primary" :disabled="importing" @click="confirmImport">
            <KiwiIcon :name="importing ? 'loader' : 'fileImport'" :size="14" :spin="importing" />
            {{ importing ? '导入中…' : '确认导入' }}
          </button>
        </div>
      </div>
    </KiwiModal>

    <!-- 开发规范：仅从页面顶部入口打开，弹窗内按「概览 / 规则 / 字段 / 示例」分组 -->
    <KiwiModal
      :open="specOpen"
      title="组件插件开发规范"
      max-w="max-w-4xl"
      @close="specOpen = false"
    >
      <div v-if="!spec" class="py-10 text-center text-sm text-slate-400">
        <KiwiIcon name="loader" :size="16" :spin="true" class="inline-block" /> 读取规范…
      </div>
      <div v-else class="space-y-4 text-slate-600">
        <!-- 概览：一句话说明 + 承载格式 + 三步流程 -->
        <section
          class="rounded-2xl border border-slate-200/80 bg-gradient-to-br from-violet-50/80 via-white to-kiwi-50/60 p-4"
        >
          <div class="flex flex-wrap items-start gap-3">
            <span
              class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-violet-500 shadow-sm"
            >
              <KiwiIcon name="puzzle" :size="19" />
            </span>
            <div class="min-w-0 flex-1">
              <h3 class="text-[14px] font-semibold text-slate-800">
                用 zip 交付一个可执行的组件插件
              </h3>
              <p class="mt-1 text-[11.5px] leading-relaxed text-slate-500">
                {{ spec.package }}
              </p>
            </div>
            <div class="flex flex-wrap gap-1.5 text-[10px]">
              <span
                class="rounded-full bg-white/80 px-2 py-0.5 text-slate-500 ring-1 ring-slate-200/70"
              >
                manifest v{{ spec.manifest_version }}
              </span>
              <span
                class="rounded-full bg-white/80 px-2 py-0.5 font-mono text-slate-500 ring-1 ring-slate-200/70"
              >
                kind: component
              </span>
              <span
                class="rounded-full bg-white/80 px-2 py-0.5 font-mono text-violet-500 ring-1 ring-violet-200/70"
              >
                {{ spec.skill }}
              </span>
            </div>
          </div>

          <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div
              v-for="(step, index) in [
                { title: '打包 ZIP', desc: 'plugin.json + 入口 ESM + 可选 CSS' },
                { title: '导入预检', desc: '确认 key、区块与第三方代码提示' },
                { title: '启用并插入', desc: '在编辑器「+ → 插件区块」中使用' },
              ]"
              :key="step.title"
              class="flex items-center gap-2 rounded-xl bg-white/70 px-3 py-2 ring-1 ring-slate-200/60"
            >
              <span
                class="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-violet-50 text-[10px] font-semibold text-violet-600"
              >
                {{ index + 1 }}
              </span>
              <div class="min-w-0">
                <p class="text-[11px] font-medium text-slate-700">{{ step.title }}</p>
                <p class="text-[10px] leading-relaxed text-slate-400">{{ step.desc }}</p>
              </div>
            </div>
          </div>
        </section>

        <!-- 关键规则 + 主题色适配 -->
        <div class="grid gap-3 lg:grid-cols-5">
          <section class="rounded-2xl border border-slate-200/80 bg-white/60 p-4 lg:col-span-3">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h3 class="flex items-center gap-1.5 text-[12.5px] font-semibold text-slate-700">
                <KiwiIcon name="checkSquare" :size="14" class="text-kiwi-500" /> 关键规则
              </h3>
              <span class="text-[10px] text-slate-400">{{ spec.rules.length }} 条</span>
            </div>
            <ul class="grid gap-1 sm:grid-cols-2">
              <li
                v-for="rule in spec.rules"
                :key="rule"
                class="flex gap-1.5 rounded-lg px-1.5 py-1 text-[11px] leading-relaxed text-slate-600"
              >
                <KiwiIcon name="check" :size="11" class="mt-0.5 shrink-0 text-kiwi-500" />
                <span>{{ rule }}</span>
              </li>
            </ul>
          </section>

          <section class="rounded-2xl border border-kiwi-100 bg-kiwi-50/40 p-4 lg:col-span-2">
            <h3 class="flex items-center gap-1.5 text-[12.5px] font-semibold text-slate-700">
              <KiwiIcon name="sparkle" :size="14" class="text-kiwi-500" /> 跟随系统主题色
            </h3>
            <p class="mt-1.5 text-[11px] leading-relaxed text-slate-500">
              插件展示颜色不要写死品牌色。使用 <code class="rounded bg-white/80 px-1">--kiwi-*</code>
              CSS 变量或运行时 <code class="rounded bg-white/80 px-1">host.theme</code>，
              切换主题色与学习模式时自动同步。
            </p>
            <div class="mt-2 overflow-hidden rounded-xl bg-slate-900">
              <div
                class="flex items-center justify-between border-b border-white/10 px-3 py-1.5 text-[9.5px] text-slate-400"
              >
                <span class="font-mono">style.css</span>
                <button
                  class="inline-flex items-center gap-1 text-slate-300 transition-colors hover:text-white"
                  title="复制主题色代码"
                  @click="copyText('color: rgb(var(--kiwi-600));\nbackground: rgb(var(--kiwi-50));', '主题色代码')"
                >
                  <KiwiIcon name="copy" :size="10" /> 复制
                </button>
              </div>
              <pre class="overflow-x-auto px-3 py-2 text-[10px] leading-relaxed text-kiwi-200">.card {
  color: rgb(var(--kiwi-600));
  background: rgb(var(--kiwi-50));
}</pre>
            </div>
            <p class="mt-2 text-[10px] leading-relaxed text-slate-400">
              运行时也可读取 accent / accentStrong / accentSoft / shade(step, alpha)。
            </p>
          </section>
        </div>

        <!-- Manifest 字段：双列卡片，避免长表格把弹窗撑得过长 -->
        <section class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white/60">
          <div
            class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200/70 px-4 py-2.5"
          >
            <h3 class="flex items-center gap-1.5 text-[12.5px] font-semibold text-slate-700">
              <KiwiIcon name="file" :size="14" class="text-slate-400" /> Manifest 字段
            </h3>
            <span class="text-[10px] text-slate-400">homepage / entry / style 等标注可选的字段可留空</span>
          </div>
          <div class="grid grid-cols-1 gap-px bg-slate-200/60 sm:grid-cols-2">
            <div
              v-for="([field, desc], index) in specFields"
              :key="field"
              class="bg-white/80 px-3.5 py-2"
              :class="{
                'sm:col-span-2':
                  specFields.length % 2 === 1 && index === specFields.length - 1,
              }"
            >
              <code class="block truncate font-mono text-[10px] text-violet-600" :title="field">
                {{ field }}
              </code>
              <p class="mt-0.5 text-[10.5px] leading-relaxed text-slate-500">{{ desc }}</p>
            </div>
          </div>
        </section>

        <!-- 示例插件包 manifest -->
        <section class="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900">
          <div
            class="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-2"
          >
            <div class="flex items-center gap-2">
              <span class="flex items-center gap-1">
                <span class="h-2 w-2 rounded-full bg-rose-400/80" />
                <span class="h-2 w-2 rounded-full bg-amber-400/80" />
                <span class="h-2 w-2 rounded-full bg-emerald-400/80" />
              </span>
              <span class="font-mono text-[10.5px] text-slate-400">plugin.json</span>
            </div>
            <button
              class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
              @click="copyExample"
            >
              <KiwiIcon name="copy" :size="11" /> 复制示例
            </button>
          </div>
          <pre class="max-h-72 overflow-auto px-4 py-3 text-[10px] leading-relaxed text-slate-200">{{ JSON.stringify(activeExample, null, 2) }}</pre>
        </section>

        <!-- 大模型辅助开发 -->
        <div
          class="flex flex-wrap items-center gap-2.5 rounded-2xl border border-violet-100 bg-violet-50/50 px-3.5 py-3"
        >
          <span
            class="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white text-violet-500 shadow-sm"
          >
            <KiwiIcon name="sparkle" :size="15" />
          </span>
          <p class="min-w-0 flex-1 text-[10.5px] leading-relaxed text-slate-500">
            <strong class="font-medium text-slate-600">交给大模型开发：</strong>
            下载开发套件，内含完整规范、可运行示例与 <code class="rounded bg-white/80 px-1">{{ spec.skill }}</code>
            skill / AI 提示词，可让大模型按规范生成可直接导入的插件包。
          </p>
          <div class="flex w-full flex-wrap items-center gap-1.5 sm:w-auto">
            <button
              class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2"
              :disabled="devKitBusy"
              @click="getDevKit"
            >
              <KiwiIcon
                :name="devKitBusy ? 'loader' : 'download'"
                :size="11"
                :spin="devKitBusy"
              />
              开发套件
            </button>
            <button class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2" @click="copyAiPrompt">
              <KiwiIcon name="copy" :size="11" /> AI 提示词
            </button>
            <button class="kiwi-btn-ghost whitespace-nowrap !px-1.5 !py-1 text-[10.5px] sm:!px-2" @click="specOpen = false">
              关闭
            </button>
          </div>
        </div>
      </div>
    </KiwiModal>

    <PluginPreviewDialog
      :open="!!previewPlugin"
      :plugin="previewPlugin"
      @close="previewPlugin = null"
    />

    <BuiltinExtensionPreviewDialog
      :open="!!previewBuiltin"
      :extension="previewBuiltin"
      @close="previewBuiltin = null"
    />

    <KiwiConfirm
      :model-value="!!removing"
      title="删除插件"
      :message="`删除「${removing?.name || ''}」后，其区块会立即从编辑器菜单移除，已插入的区块会降级为静态卡片。`"
      confirm-text="删除"
      danger
      @update:model-value="(value: boolean) => { if (!value) removing = null }"
      @confirm="confirmRemove"
    />
  </div>
</template>
