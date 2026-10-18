<script setup lang="ts">
/** 插入表格：选择行数与列数，带尺寸预览。 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'

const props = withDefaults(defineProps<{ open: boolean }>(), { open: false })
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'insert', size: { rows: number; cols: number }): void
}>()

const MIN = 1
const MAX = 20
const rows = ref(3)
const cols = ref(3)

function clamp(value: number): number {
  if (!Number.isFinite(value)) return 3
  return Math.min(MAX, Math.max(MIN, Math.round(value)))
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    rows.value = 3
    cols.value = 3
  },
)

const safeRows = computed(() => clamp(rows.value))
const safeCols = computed(() => clamp(cols.value))
// 预览最多展示 8×8，避免大表格撑破弹窗
const previewRows = computed(() => Math.min(8, safeRows.value))
const previewCols = computed(() => Math.min(8, safeCols.value))

function step(field: 'rows' | 'cols', delta: number) {
  const target = field === 'rows' ? rows : cols
  target.value = clamp(clamp(target.value) + delta)
}

function submit() {
  emit('insert', { rows: safeRows.value, cols: safeCols.value })
}
</script>

<template>
  <KiwiModal :open="open" title="插入表格" max-w="max-w-sm" @close="emit('close')">
    <div class="flex items-end gap-3">
      <label class="min-w-0 flex-1">
        <span class="mb-1.5 block text-[11px] font-medium text-slate-500">行数</span>
        <div class="flex items-center gap-1">
          <button type="button" class="table-step" title="减少行数" @click="step('rows', -1)">−</button>
          <input
            v-model.number="rows"
            type="number"
            :min="MIN"
            :max="MAX"
            class="kiwi-input !w-14 text-center tabular-nums"
            @keyup.enter="submit"
          />
          <button type="button" class="table-step" title="增加行数" @click="step('rows', 1)">+</button>
        </div>
      </label>
      <span class="pb-2 text-slate-300">×</span>
      <label class="min-w-0 flex-1">
        <span class="mb-1.5 block text-[11px] font-medium text-slate-500">列数</span>
        <div class="flex items-center gap-1">
          <button type="button" class="table-step" title="减少列数" @click="step('cols', -1)">−</button>
          <input
            v-model.number="cols"
            type="number"
            :min="MIN"
            :max="MAX"
            class="kiwi-input !w-14 text-center tabular-nums"
            @keyup.enter="submit"
          />
          <button type="button" class="table-step" title="增加列数" @click="step('cols', 1)">+</button>
        </div>
      </label>
    </div>

    <div class="mt-4 rounded-xl border border-slate-200/70 bg-slate-50/60 p-3">
      <div
        class="grid gap-1"
        :style="{ gridTemplateColumns: `repeat(${previewCols}, minmax(0, 1fr))` }"
      >
        <span
          v-for="cell in previewRows * previewCols"
          :key="cell"
          class="h-3.5 rounded-[3px] border border-slate-200/80"
          :class="cell <= previewCols ? 'bg-kiwi-100/70' : 'bg-white'"
        />
      </div>
      <p class="mt-2 text-[11px] tabular-nums text-slate-400">
        {{ safeRows }} 行 × {{ safeCols }} 列 · 首行为表头
        <span v-if="safeRows > 8 || safeCols > 8">（预览已截断）</span>
      </p>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button class="kiwi-btn-primary" @click="submit">插入表格</button>
    </div>
  </KiwiModal>
</template>

<style scoped>
.table-step {
  @apply h-8 w-7 shrink-0 rounded-lg border border-slate-200/80 bg-white text-[14px] leading-none text-slate-500 transition-colors hover:border-kiwi-200 hover:text-kiwi-700;
}
</style>
