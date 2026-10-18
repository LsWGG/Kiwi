<script setup lang="ts">
/** 页头标签入口：多标签时全部展开，空间不足才折叠为 +N。 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useNotesStore, type NoteOut, type NoteSummary } from '@/stores/notes'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import NoteTagEditor from './NoteTagEditor.vue'
import { tagChipClass } from './tagPalette'

const props = defineProps<{ note: NoteOut | NoteSummary }>()

const notes = useNotesStore()
const trigger = ref<HTMLButtonElement | null>(null)
const measure = ref<HTMLElement | null>(null)
const open = ref(false)
const pos = ref({ left: '0px', top: '0px' })
const visibleTags = ref<string[]>([])
const tags = computed(() => props.note.tags || [])
const hiddenCount = computed(() => Math.max(0, tags.value.length - visibleTags.value.length))
const triggerTitle = computed(() =>
  tags.value.length ? `标签：${tags.value.join('、')}（点击编辑）` : '设置标签',
)

const CHIP_EXTRA = 'h-[16px] max-w-[9rem] shrink-0 truncate text-[9.5px]'

function tagClass(index: number) {
  return `${tagChipClass(index)} ${CHIP_EXTRA}`
}

function fitTags() {
  const all = tags.value
  if (!all.length) {
    visibleTags.value = []
    return
  }
  const measureEl = measure.value
  if (!measureEl || measureEl.children.length < all.length) {
    visibleTags.value = all
    return
  }
  // 可用宽度：随窗口变化，但不超过两侧工具栏能承受的范围。
  const maxWidth = Math.min(340, Math.max(150, window.innerWidth * 0.32))
  const widths = all.map((_, index) => {
    const el = measureEl.children[index] as HTMLElement | undefined
    return el ? el.getBoundingClientRect().width : 0
  })
  const gap = 3
  const badgeWidth = 24
  const total = (count: number) =>
    widths.slice(0, count).reduce((sum, width) => sum + width, 0) +
    Math.max(0, count - 1) * gap +
    (count < all.length ? badgeWidth : 0)

  let count = all.length
  while (count > 1 && total(count) > maxWidth) count--
  visibleTags.value = all.slice(0, count)
}

let frame = 0
function scheduleFit() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => void nextTick(fitTags))
}

function place() {
  if (!open.value) return
  const rect = trigger.value?.getBoundingClientRect()
  if (!rect) return
  const width = 264
  pos.value = {
    left: `${Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8))}px`,
    top: `${Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 300))}px`,
  }
}

watch(open, (value) => {
  if (value) place()
})

watch(tags, () => scheduleFit(), { immediate: true, deep: true })

function toggle() {
  open.value = !open.value
  if (open.value) {
    void notes.fetchTags().catch(() => [])
  }
}

function close() {
  open.value = false
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

watch(open, (value) => {
  if (value) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
})

onMounted(() => {
  window.addEventListener('resize', scheduleFit)
  scheduleFit()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('resize', scheduleFit)
  cancelAnimationFrame(frame)
})
</script>

<template>
  <button
    ref="trigger"
    type="button"
    class="group relative inline-flex h-[22px] shrink-0 items-center rounded-full border text-[10.5px] leading-none transition-all"
    :class="
      tags.length
        ? 'max-w-[45vw] gap-1 border-transparent bg-transparent px-0.5 hover:bg-white/60'
        : 'border-dashed border-slate-200 bg-white/50 px-2 text-slate-400 hover:border-kiwi-300 hover:text-kiwi-600'
    "
    :title="triggerTitle"
    @click="toggle"
  >
    <template v-if="tags.length">
      <span class="flex min-w-0 items-center gap-[3px] overflow-hidden">
        <span
          v-for="(tag, index) in visibleTags"
          :key="tag"
          :class="tagClass(index)"
        >{{ tag }}</span>
        <span
          v-if="hiddenCount"
          class="inline-flex h-[16px] min-w-[18px] shrink-0 items-center justify-center rounded-full border border-slate-200/80 bg-white px-1 text-[9px] font-semibold tabular-nums text-slate-500"
          :title="`还有 ${hiddenCount} 个标签：${tags.slice(visibleTags.length).join('、')}`"
        >
          +{{ hiddenCount }}
        </span>
      </span>
    </template>
    <span v-else>添加标签</span>

    <!-- 隐藏测量行：与实际标签同尺寸，用于判断何时需要折叠。 -->
    <span
      ref="measure"
      aria-hidden="true"
      class="pointer-events-none invisible absolute left-0 top-0 flex items-center gap-[3px] whitespace-nowrap"
    >
      <span v-for="(tag, index) in tags" :key="`m-${tag}`" :class="tagClass(index)">{{ tag }}</span>
    </span>
  </button>

  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[95]"
      @mousedown="close"
      @contextmenu.prevent="close"
    >
      <div
        class="absolute w-[264px] rounded-xl border border-slate-200/80 bg-white/95 p-3 shadow-lifted backdrop-blur-xl animate-scale-in"
        :style="pos"
        @mousedown.stop
      >
        <div class="mb-2 flex items-center justify-between">
          <p class="text-[11.5px] font-medium text-slate-600">
            笔记标签
            <span v-if="tags.length" class="ml-1 text-[10px] font-normal text-slate-400">
              {{ tags.length }} 个
            </span>
          </p>
          <button
            type="button"
            class="rounded p-0.5 text-slate-400 transition-colors hover:text-slate-600"
            @click="close"
          >
            <KiwiIcon name="close" :size="11" />
          </button>
        </div>
        <NoteTagEditor
          :note-id="note.id"
          :tags="tags"
          @updated="place"
        />
      </div>
    </div>
  </Teleport>
</template>
