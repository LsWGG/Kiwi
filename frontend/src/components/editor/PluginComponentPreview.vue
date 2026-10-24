<script setup lang="ts">
/** 设置页插件预览：用真实组件和默认 props 渲染，交互只改本地副本。 */
import { computed, onErrorCaptured, onMounted, ref, watch } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { usePluginsStore } from '@/stores/plugins'

const props = defineProps<{
  pluginId: string
  pluginKey: string
  blockType: string
  initialProps?: Record<string, unknown>
}>()

const plugins = usePluginsStore()
const localProps = ref<Record<string, unknown>>({ ...(props.initialProps || {}) })
const error = ref('')
const loading = ref(false)

const entry = computed(() =>
  plugins.getRuntimeBlock(props.pluginKey, props.blockType),
)
const loadError = computed(() => plugins.runtimeErrors[props.pluginKey] || error.value)

function updateProps(patch: Record<string, unknown>) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return
  localProps.value = { ...localProps.value, ...patch }
}

onErrorCaptured((value) => {
  error.value =
    value instanceof Error && value.message ? value.message : '组件渲染失败'
  return false
})

async function load() {
  if (entry.value) return
  loading.value = true
  error.value = ''
  try {
    await plugins.ensurePreviewRuntime(props.pluginId)
  } catch (e: any) {
    error.value = e?.message || '插件预览加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.pluginId, props.blockType],
  () => {
    localProps.value = { ...(props.initialProps || {}) }
    error.value = ''
    void load()
  },
)

onMounted(load)
</script>

<template>
  <component
    :is="entry.component"
    v-if="entry && !error"
    :block-props="localProps"
    :readonly="false"
    :selected="false"
    :update-props="updateProps"
    :delete-block="() => {}"
  />
  <div v-else class="plugin-preview-state" :class="{ 'is-error': !!loadError }">
    <KiwiIcon :name="loadError ? 'alert' : 'loader'" :size="16" :spin="loading" />
    <span>{{ loadError || (loading ? '正在加载插件运行时…' : '等待插件加载') }}</span>
  </div>
</template>

<style scoped>
.plugin-preview-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 120px;
  border: 1px dashed rgb(203 213 225);
  border-radius: 12px;
  color: rgb(100 116 139);
  font-size: 12px;
}
.plugin-preview-state.is-error {
  border-color: rgb(254 202 202);
  background: rgb(254 242 242 / 0.65);
  color: rgb(225 29 72);
}
</style>
