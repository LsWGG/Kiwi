<script setup lang="ts">
/**
 * 第三方组件插件区块宿主。
 *
 * 插件脚本注册的 Vue 组件在这里渲染；加载失败、插件停用或卸载时保留一个
 * 可删除的占位卡，正文与 props 不丢失。
 */
import { computed, onErrorCaptured, onMounted, ref, watch } from 'vue'
import { NodeViewWrapper, nodeViewProps } from '@tiptap/vue-3'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { usePluginsStore } from '@/stores/plugins'
import { usePluginWindowsStore } from '@/stores/pluginWindows'
import { useEditorEditable } from './useEditorEditable'
import { normalizePluginAlign, type PluginBlockAlign } from './pluginBlock'

const props = defineProps(nodeViewProps)
const plugins = usePluginsStore()
const pluginWindows = usePluginWindowsStore()
const editable = useEditorEditable(props.editor)
const renderError = ref('')

const pluginKey = computed(() => String(props.node.attrs.pluginKey || ''))
const blockType = computed(() => String(props.node.attrs.blockType || ''))
const blockProps = computed<Record<string, unknown>>(() =>
  props.node.attrs.props && typeof props.node.attrs.props === 'object'
    ? (props.node.attrs.props as Record<string, unknown>)
    : {},
)
const entry = computed(() => plugins.getComponentBlock(pluginKey.value, blockType.value))
const plugin = computed(() =>
  plugins.plugins.find((item) => item.key === pluginKey.value),
)
const loadError = computed(
  () => plugins.runtimeErrors[pluginKey.value] || renderError.value,
)
const propsJson = computed(() => JSON.stringify(blockProps.value, null, 2))

const message = computed(() => {
  if (renderError.value) return '组件渲染失败'
  if (loadError.value) return loadError.value
  if (!plugin.value) return '插件未安装或已删除'
  if (!plugin.value.enabled) return '插件已停用'
  if (plugins.runtimeLoading) return '插件运行时加载中…'
  return '插件未注册该区块，或加载失败'
})

const align = computed<PluginBlockAlign>(() =>
  normalizePluginAlign(props.node.attrs.align),
)

function updateProps(patch: Record<string, unknown>) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return
  props.updateAttributes({
    props: { ...blockProps.value, ...patch },
  })
}

/** 区块级水平对齐；写入节点属性并持久化到 kiwi-plugin 围栏。 */
function setAlign(value: PluginBlockAlign) {
  if (align.value === value) return
  props.updateAttributes({ align: value })
}

const ALIGN_OPTIONS: Array<{ value: PluginBlockAlign; icon: string; label: string }> = [
  { value: 'left', icon: 'alignLeft', label: '左对齐' },
  { value: 'center', icon: 'alignCenter', label: '居中' },
  { value: 'right', icon: 'alignRight', label: '右对齐' },
]

/** manifest 声明 pinnable 的区块（如计时器）可以置顶为全局浮窗。 */
const pinnable = computed(() => entry.value?.pinnable === true)
const pinned = computed(
  () => pinnable.value && pluginWindows.isOpen(pluginKey.value, blockType.value),
)

function togglePin() {
  const row = entry.value
  if (!row?.pinnable) return
  const id = pluginWindows.windowId(row.pluginKey, row.type)
  if (pluginWindows.isOpen(row.pluginKey, row.type)) {
    pluginWindows.close(id)
    return
  }
  pluginWindows.open({
    pluginKey: row.pluginKey,
    blockType: row.type,
    title: row.label || row.pluginName,
    icon: row.icon,
    props: { ...blockProps.value },
  })
}

function remove() {
  props.deleteNode()
}

function requestRuntime() {
  if (!pluginKey.value) return
  void plugins.ensureComponentBlocks()
}

onErrorCaptured((error) => {
  renderError.value =
    error instanceof Error && error.message ? error.message : '组件渲染失败'
  return false
})

watch([pluginKey, blockType], () => {
  renderError.value = ''
  if (!entry.value) requestRuntime()
})

onMounted(requestRuntime)
</script>

<template>
  <NodeViewWrapper
    class="kiwi-plugin-block"
    :class="{
      'is-selected': selected,
      'is-readonly': !editable,
      'is-align-center': align === 'center',
      'is-align-right': align === 'right',
    }"
    contenteditable="false"
    data-type="kiwi-plugin-block"
    :data-align="align"
    :data-plugin-key="pluginKey"
    :data-block-type="blockType"
  >
    <!-- 选中时浮出对齐工具条；绝对定位，不参与区块的 flex 对齐计算。 -->
    <div
      v-if="editable && selected"
      class="kiwi-plugin-align-toolbar"
      contenteditable="false"
      @mousedown.prevent
    >
      <button
        v-for="option in ALIGN_OPTIONS"
        :key="option.value"
        type="button"
        class="kiwi-plugin-align-button"
        :class="{ 'is-active': align === option.value }"
        :title="option.label"
        @mousedown.prevent
        @click.stop="setAlign(option.value)"
      >
        <KiwiIcon :name="option.icon" :size="13" />
      </button>
      <template v-if="pinnable">
        <span class="kiwi-plugin-toolbar-sep" />
        <button
          type="button"
          class="kiwi-plugin-align-button"
          :class="{ 'is-active': pinned }"
          :title="pinned ? '取消置顶浮窗' : '置顶为全局浮窗'"
          @mousedown.prevent
          @click.stop="togglePin"
        >
          <KiwiIcon name="pin" :size="13" />
        </button>
      </template>
    </div>

    <div class="kiwi-plugin-surface" :class="{ 'is-fallback': !entry || !!renderError }">
      <component
        :is="entry.component"
        v-if="entry && !renderError"
        :block-props="blockProps"
        :readonly="!editable"
        :selected="selected"
        :update-props="updateProps"
        :delete-block="remove"
      />
      <div v-else class="kiwi-plugin-fallback">
        <span class="kiwi-plugin-fallback-icon">
          <KiwiIcon :name="plugin?.icon || 'puzzle'" :size="16" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="kiwi-plugin-fallback-title">
            {{ plugin?.name || '组件插件' }}
            <code>{{ pluginKey }}:{{ blockType }}</code>
          </p>
          <p class="kiwi-plugin-fallback-message" :class="{ 'is-error': !!loadError }">
            {{ message }}
          </p>
          <details v-if="propsJson !== '{}'" class="kiwi-plugin-fallback-props">
            <summary>查看区块数据</summary>
            <pre>{{ propsJson }}</pre>
          </details>
        </div>
        <button
          v-if="editable"
          type="button"
          class="kiwi-plugin-fallback-remove"
          title="删除插件区块"
          @mousedown.prevent
          @click.stop="remove"
        >
          <KiwiIcon name="trash" :size="13" />
        </button>
      </div>
    </div>
  </NodeViewWrapper>
</template>

<style scoped>
.kiwi-plugin-block {
  position: relative;
  margin: 0.75rem 0;
  border-radius: 12px;
}
/* 对齐不能把插件包进 shrink-to-fit 容器：插件常用 `width: min(100%, …)`
   自适应，百分比在 fit-content 里会退化成 min-content，把番茄钟等布局挤成竖排。
   这里让插件照常拿到整行宽度，只用自动外边距移动组件本身。 */
.kiwi-plugin-block.is-align-center :deep(.kiwi-plugin-surface > *) {
  margin-left: auto;
  margin-right: auto;
}
.kiwi-plugin-block.is-align-right :deep(.kiwi-plugin-surface > *) {
  margin-left: auto;
  margin-right: 0;
}
/* 选中环画在组件自身盒子上，窄卡片不会横跨整行形成空白描边。 */
.kiwi-plugin-surface {
  width: 100%;
  max-width: 100%;
  border-radius: 12px;
}
.kiwi-plugin-block.is-selected :deep(.kiwi-plugin-surface > *) {
  box-shadow: 0 0 0 2px var(--kiwi-accent, #10b981);
}
.kiwi-plugin-align-toolbar {
  position: absolute;
  top: -32px;
  left: 50%;
  z-index: 12;
  display: flex;
  gap: 1px;
  padding: 2px;
  border: 1px solid rgb(226 232 240 / 0.9);
  border-radius: 9px;
  background: rgb(255 255 255 / 0.96);
  box-shadow: 0 6px 18px rgb(15 23 42 / 0.12);
  transform: translateX(-50%);
  backdrop-filter: blur(8px);
}
.kiwi-plugin-align-button {
  display: grid;
  place-items: center;
  width: 26px;
  height: 24px;
  border-radius: 6px;
  color: rgb(100 116 139);
  transition: background 0.15s ease, color 0.15s ease;
}
.kiwi-plugin-align-button:hover {
  background: rgb(241 245 249);
  color: rgb(51 65 85);
}
.kiwi-plugin-align-button.is-active {
  background: rgb(var(--kiwi-50, 236 253 245));
  color: rgb(var(--kiwi-600, 5 150 105));
}
.kiwi-plugin-toolbar-sep {
  width: 1px;
  margin: 3px 2px;
  background: rgb(226 232 240);
}
.kiwi-plugin-fallback {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px dashed rgb(203 213 225);
  border-radius: 12px;
  background: rgb(248 250 252 / 0.8);
}
.kiwi-plugin-fallback-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgb(241 245 249);
  color: rgb(100 116 139);
  flex-shrink: 0;
}
.kiwi-plugin-fallback-title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: rgb(51 65 85);
}
.kiwi-plugin-fallback-title code {
  margin-left: 6px;
  font-size: 10px;
  font-weight: 400;
  color: rgb(148 163 184);
}
.kiwi-plugin-fallback-message {
  margin: 2px 0 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: rgb(100 116 139);
}
.kiwi-plugin-fallback-message.is-error {
  color: rgb(225 29 72);
}
.kiwi-plugin-fallback-props {
  margin-top: 4px;
  font-size: 10px;
  color: rgb(148 163 184);
}
.kiwi-plugin-fallback-props pre {
  margin: 4px 0 0;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 10px;
  color: rgb(100 116 139);
}
.kiwi-plugin-fallback-remove {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 7px;
  color: rgb(148 163 184);
  flex-shrink: 0;
  transition: background 0.15s ease, color 0.15s ease;
}
.kiwi-plugin-fallback-remove:hover {
  background: rgb(254 226 226);
  color: rgb(225 29 72);
}
</style>
