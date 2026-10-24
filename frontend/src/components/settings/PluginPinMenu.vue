<script setup lang="ts">
/**
 * 设置页插件卡片的置顶入口：不创建 / 插入笔记，也能把 pinnable 区块
 * 放到全局浮窗。仅 manifest 声明了 pinnable 的插件显示该按钮。
 */
import { computed } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import { toast } from '@/components/ui/toast'
import { usePinPlugin } from '@/composables/usePinPlugin'
import type { Plugin, PluginBlock } from '@/stores/plugins'

const props = defineProps<{ plugin: Plugin }>()

const { pinningKey, isPinned, toggleManifestBlock } = usePinPlugin()

const blocks = computed(() =>
  props.plugin.blocks.filter((block) => block.pinnable),
)
const pinnedCount = computed(
  () =>
    blocks.value.filter((block) => isPinned(props.plugin.key, block.type)).length,
)

async function toggle(block: PluginBlock) {
  try {
    const opened = await toggleManifestBlock(props.plugin, block)
    toast.success(opened ? `已置顶「${block.label}」` : `已取消置顶「${block.label}」`)
  } catch (e: any) {
    toast.error(e?.message || '置顶插件失败')
  }
}
</script>

<template>
  <KiwiDropdown v-if="blocks.length" align="right" width="w-64">
    <template #trigger="{ open }">
      <button
        type="button"
        class="kiwi-btn-ghost !px-2 !py-1.5"
        :class="open ? 'bg-kiwi-50 text-kiwi-600' : pinnedCount ? 'text-kiwi-600' : ''"
        :disabled="!plugin.enabled && !pinnedCount"
        :title="
          plugin.enabled
            ? '置顶为全局浮窗（无需插入笔记）'
            : pinnedCount
              ? '管理置顶浮窗'
              : '启用插件后可置顶'
        "
      >
        <KiwiIcon name="pin" :size="13" />
        <span class="text-[10.5px]">置顶</span>
        <span
          v-if="pinnedCount"
          class="rounded-full bg-kiwi-100 px-1 text-[9.5px] tabular-nums text-kiwi-700"
        >
          {{ pinnedCount }}
        </span>
      </button>
    </template>
    <template #default="{ close }">
      <p class="px-2.5 pb-1 pt-1 text-[9.5px] font-medium tracking-wide text-slate-400">
        置顶为全局浮窗
      </p>
      <button
        v-for="block in blocks"
        :key="block.type"
        type="button"
        class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-kiwi-50 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="!!pinningKey"
        @click="close(); toggle(block)"
      >
        <span
          class="grid h-6 w-6 shrink-0 place-items-center rounded-md"
          :class="
            isPinned(plugin.key, block.type)
              ? 'bg-kiwi-50 text-kiwi-600'
              : 'bg-slate-100 text-slate-400'
          "
        >
          <KiwiIcon
            :name="pinningKey === `${plugin.key}:${block.type}` ? 'loader' : 'pin'"
            :size="11"
            :spin="pinningKey === `${plugin.key}:${block.type}`"
          />
        </span>
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[11.5px] text-slate-600">{{ block.label }}</span>
          <span class="block truncate text-[9.5px] text-slate-400">
            {{
              isPinned(plugin.key, block.type)
                ? '已置顶，点击关闭浮窗'
                : '点击置顶，无需插入笔记'
            }}
          </span>
        </span>
        <KiwiIcon
          v-if="isPinned(plugin.key, block.type)"
          name="check"
          :size="11"
          class="shrink-0 text-kiwi-500"
        />
      </button>
    </template>
  </KiwiDropdown>
</template>
