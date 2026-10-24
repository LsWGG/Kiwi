<script setup lang="ts">
/** 组件插件效果预览：用默认 props 挂载真实运行时。 */
import { computed, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import PluginComponentPreview from '@/components/editor/PluginComponentPreview.vue'
import { usePinPlugin } from '@/composables/usePinPlugin'
import { toast } from '@/components/ui/toast'
import type { Plugin } from '@/stores/plugins'

const props = defineProps<{
  open: boolean
  plugin: Plugin | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const activeType = ref('')
/** 预览插入后的水平对齐效果；不影响插件数据。 */
const align = ref<'left' | 'center' | 'right'>('left')
const ALIGN_OPTIONS = [
  { value: 'left' as const, icon: 'alignLeft', label: '左对齐' },
  { value: 'center' as const, icon: 'alignCenter', label: '居中' },
  { value: 'right' as const, icon: 'alignRight', label: '右对齐' },
]
const activeBlock = computed(() =>
  props.plugin?.blocks.find((block) => block.type === activeType.value) ||
  props.plugin?.blocks[0] ||
  null,
)

watch(
  () => props.plugin?.id,
  () => {
    activeType.value = props.plugin?.blocks[0]?.type || ''
  },
  { immediate: true },
)

function selectBlock(type: string) {
  activeType.value = type
}

const { pinningKey, isPinned, toggleManifestBlock } = usePinPlugin()

/** 预览里直接置顶当前区块，省去先插入笔记再操作。 */
async function togglePin() {
  const plugin = props.plugin
  const block = activeBlock.value
  if (!plugin || !block) return
  try {
    const opened = await toggleManifestBlock(plugin, block)
    toast.success(opened ? `已置顶「${block.label}」` : `已取消置顶「${block.label}」`)
  } catch (e: any) {
    toast.error(e?.message || '置顶插件失败')
  }
}

function formatSize(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}
</script>

<template>
  <KiwiModal
    :open="open"
    :title="plugin ? `预览 · ${plugin.name}` : '插件预览'"
    max-w="max-w-4xl"
    @close="emit('close')"
  >
    <div v-if="plugin" class="space-y-4">
      <div class="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span class="rounded-full bg-violet-50 px-2 py-0.5 text-violet-600">组件插件</span>
        <span class="rounded-full bg-slate-100 px-2 py-0.5">v{{ plugin.version }}</span>
        <code class="rounded-full bg-slate-100 px-2 py-0.5">{{ plugin.key }}</code>
        <span class="text-slate-400">
          {{ plugin.entry || 'index.js' }} · {{ formatSize(plugin.script_size) }}
        </span>
        <span
          class="ml-auto inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-amber-600"
        >
          <KiwiIcon name="alert" :size="11" /> 预览会执行插件脚本
        </span>
      </div>

      <div v-if="plugin.blocks.length > 1" class="flex flex-wrap gap-1.5">
        <button
          v-for="block in plugin.blocks"
          :key="block.type"
          type="button"
          class="rounded-lg border px-2.5 py-1 text-[11px] transition-colors"
          :class="
            activeBlock?.type === block.type
              ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
              : 'border-slate-200 bg-white/60 text-slate-500 hover:bg-slate-50'
          "
          @click="selectBlock(block.type)"
        >
          {{ block.label }}
        </button>
      </div>

      <div
        v-if="activeBlock"
        class="rounded-2xl border border-slate-200/80 bg-white px-5 py-4 shadow-sm"
      >
        <div class="mb-3 flex items-center gap-2 border-b border-slate-100 pb-2">
          <span class="grid h-7 w-7 place-items-center rounded-lg bg-slate-100 text-slate-500">
            <KiwiIcon :name="activeBlock.icon || 'puzzle'" :size="13" />
          </span>
          <div class="min-w-0">
            <p class="text-[12px] font-semibold text-slate-700">{{ activeBlock.label }}</p>
            <p class="text-[10px] text-slate-400">
              {{ activeBlock.category }} · <code>{{ plugin.key }}:{{ activeBlock.type }}</code>
            </p>
          </div>
          <!-- pinnable 区块可直接置顶为全局浮窗，不需要先插入笔记；放在左侧避免被默认浮窗遮挡。 -->
          <button
            v-if="activeBlock.pinnable"
            type="button"
            class="ml-2 inline-flex h-7 shrink-0 items-center gap-1 rounded-lg border px-2 text-[10.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            :class="
              isPinned(plugin.key, activeBlock.type)
                ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-700'
                : 'border-slate-200 bg-white/70 text-slate-500 hover:bg-slate-50'
            "
            :disabled="
              !!pinningKey ||
              (!plugin.enabled && !isPinned(plugin.key, activeBlock.type))
            "
            :title="
              plugin.enabled
                ? '置顶为全局浮窗（无需插入笔记）'
                : isPinned(plugin.key, activeBlock.type)
                  ? '关闭全局浮窗'
                  : '启用插件后可置顶'
            "
            @click="togglePin"
          >
            <KiwiIcon
              :name="pinningKey ? 'loader' : 'pin'"
              :size="11"
              :spin="!!pinningKey"
            />
            {{ isPinned(plugin.key, activeBlock.type) ? '取消置顶' : '置顶' }}
          </button>
          <!-- 模拟插入后的块级对齐，便于第三方组件检查不同宽度下的表现。 -->
          <div class="ml-auto inline-flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white/70 p-0.5">
            <button
              v-for="option in ALIGN_OPTIONS"
              :key="option.value"
              type="button"
              class="grid h-6 w-6 place-items-center rounded-md transition-colors"
              :class="
                align === option.value
                  ? 'bg-kiwi-50 text-kiwi-600'
                  : 'text-slate-400 hover:bg-slate-50 hover:text-slate-600'
              "
              :title="option.label"
              @click="align = option.value"
            >
              <KiwiIcon :name="option.icon" :size="13" />
            </button>
          </div>
        </div>

        <!-- 插件需要整行宽度作为百分比基准；对齐只移动组件自身。 -->
        <div
          class="plugin-preview-stage w-full"
          :class="{
            'is-align-center': align === 'center',
            'is-align-right': align === 'right',
          }"
        >
          <PluginComponentPreview
            :key="`${plugin.id}:${activeBlock.type}`"
            :plugin-id="plugin.id"
            :plugin-key="plugin.key"
            :block-type="activeBlock.type"
            :initial-props="activeBlock.default_props"
          />
        </div>
      </div>
      <div v-else class="rounded-xl bg-slate-50 px-4 py-8 text-center text-[12px] text-slate-400">
        该插件还没有定义区块。
      </div>

      <p class="rounded-xl bg-slate-50/80 px-3 py-2 text-[10.5px] leading-relaxed text-slate-500">
        预览在本地修改区块 props，不会写入任何笔记。正式插入后，内容会以
        <code class="rounded bg-white px-1">kiwi-plugin</code>
        Markdown 围栏保存；卸载插件不会丢失数据。插件颜色建议使用主题变量，会自动跟随系统主题色。
      </p>
      <div class="flex justify-end">
        <button class="kiwi-btn-secondary" @click="emit('close')">关闭</button>
      </div>
    </div>
  </KiwiModal>
</template>

<style scoped>
.plugin-preview-stage.is-align-center > * {
  margin-left: auto;
  margin-right: auto;
}
.plugin-preview-stage.is-align-right > * {
  margin-left: auto;
  margin-right: 0;
}
</style>
