<script setup lang="ts">
/** 阅读态插件区块：只渲染已启用插件，组件按只读模式挂载。 */
import { computed, onErrorCaptured, onMounted, ref } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { usePluginsStore } from '@/stores/plugins'

const props = defineProps<{
  pluginKey: string
  blockType: string
  blockProps?: Record<string, unknown>
}>()

const plugins = usePluginsStore()
const renderError = ref('')

const entry = computed(() => plugins.getComponentBlock(props.pluginKey, props.blockType))
const plugin = computed(() =>
  plugins.plugins.find((item) => item.key === props.pluginKey),
)
const loadError = computed(
  () => plugins.runtimeErrors[props.pluginKey] || renderError.value,
)
const message = computed(() => {
  if (renderError.value) return '组件渲染失败'
  if (loadError.value) return loadError.value
  if (!plugin.value) return '插件未安装或已删除'
  if (!plugin.value.enabled) return '插件已停用'
  if (plugins.runtimeLoading) return '插件运行时加载中…'
  return '插件未注册该区块，或加载失败'
})

onErrorCaptured((error) => {
  renderError.value =
    error instanceof Error && error.message ? error.message : '组件渲染失败'
  return false
})

onMounted(() => {
  void plugins.ensureComponentBlocks()
})
</script>

<template>
  <component
    :is="entry.component"
    v-if="entry && !renderError"
    :block-props="blockProps || {}"
    :readonly="true"
    :selected="false"
    :update-props="() => {}"
    :delete-block="() => {}"
  />
  <div v-else class="kiwi-plugin-embed-fallback">
    <span class="kiwi-plugin-embed-icon">
      <KiwiIcon :name="plugin?.icon || 'puzzle'" :size="15" />
    </span>
    <div class="min-w-0">
      <p class="kiwi-plugin-embed-title">
        {{ plugin?.name || '组件插件' }}
        <code>{{ pluginKey }}:{{ blockType }}</code>
      </p>
      <p class="kiwi-plugin-embed-message" :class="{ 'is-error': !!loadError }">
        {{ message }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.kiwi-plugin-embed-fallback {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px dashed rgb(203 213 225);
  border-radius: 12px;
  background: rgb(248 250 252 / 0.8);
}
.kiwi-plugin-embed-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgb(241 245 249);
  color: rgb(100 116 139);
  flex-shrink: 0;
}
.kiwi-plugin-embed-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.kiwi-plugin-embed-title code {
  margin-left: 6px;
  font-size: 10px;
  font-weight: 400;
  color: rgb(148 163 184);
}
.kiwi-plugin-embed-message {
  margin: 2px 0 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: rgb(100 116 139);
}
.kiwi-plugin-embed-message.is-error {
  color: rgb(225 29 72);
}
</style>
