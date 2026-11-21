<script setup lang="ts">
/** 数据表单元格：按字段类型渲染内联编辑控件。 */
import { computed, nextTick, ref, watch } from 'vue'
import type { DbField, SelectOption } from '@/stores/noteDatabase'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiDateInput from '@/components/ui/KiwiDateInput.vue'
import KiwiSelect from '@/components/ui/KiwiSelect.vue'
import DatabaseAttachmentCell from './DatabaseAttachmentCell.vue'
import { chipClass, dotClass } from './colors'

const props = withDefaults(
  defineProps<{
    field: DbField
    value: any
    readonly?: boolean
    /** 弹窗等有背景的场景显示输入框边框，表格内保持无边框。 */
    boxed?: boolean
  }>(),
  { readonly: false, boxed: false },
)
const emit = defineEmits<{ (e: 'update', value: any): void }>()

const options = computed<SelectOption[]>(() => props.field.options ?? [])
const selected = computed(() => options.value.find((o) => o.id === props.value) ?? null)
const multi = computed<string[]>(() => (Array.isArray(props.value) ? props.value : []))
const multiOptions = computed(() =>
  multi.value
    .map((id) => options.value.find((o) => o.id === id))
    .filter((o): o is SelectOption => !!o),
)

// ---------- 文本 / 多行文本 / 数字 / URL / 日期 ----------
const text = ref('')
const input = ref<HTMLInputElement | HTMLTextAreaElement | null>(null)

function asText(value: any): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

watch(
  () => props.value,
  (value) => {
    // 外部更新（批量粘贴、撤销等）需要同步到聚焦中的输入框；
    // 用户输入时 props 与本地文本一致，这里赋值不会打断光标。
    text.value = asText(value)
  },
  { immediate: true },
)

function onDatePicked(value: string) {
  text.value = value
  commitText()
}

function commitText() {
  const value = text.value
  if (props.field.type === 'number') {
    if (!value.trim()) {
      if (props.value !== null && props.value !== undefined) emit('update', null)
      return
    }
    const num = Number(value)
    if (Number.isNaN(num)) {
      text.value = asText(props.value)
      return
    }
    emit('update', num)
    return
  }
  if (value === asText(props.value)) return
  emit('update', value === '' ? null : value)
}

function onEnter(e: KeyboardEvent) {
  ;(e.target as HTMLInputElement).blur()
}

// ---------- 链接：展示为可点击超链接，点铅笔或双击进入编辑 ----------
const urlEditing = ref(false)
const urlInput = ref<HTMLInputElement | null>(null)
const urlText = computed(() => asText(props.value).trim())

/** 只放行常见安全协议；无协议的域名补 https://，其余保留原文不生成链接。 */
function urlHref(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (/^(https?|mailto|tel|ftp):/i.test(trimmed)) return trimmed
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) return ''
  if (trimmed.startsWith('//')) return `https:${trimmed}`
  if (trimmed.startsWith('/') || trimmed.startsWith('#')) return trimmed
  return `https://${trimmed}`
}

const urlLinkable = computed(() => !!urlHref(urlText.value))

function startUrlEdit() {
  text.value = asText(props.value)
  urlEditing.value = true
  void nextTick(() => {
    urlInput.value?.focus()
    urlInput.value?.select()
  })
}

function finishUrlEdit() {
  if (!urlEditing.value) return
  commitText()
  urlEditing.value = false
}

function cancelUrlEdit() {
  text.value = asText(props.value)
  urlEditing.value = false
}

// ---------- 单选 ----------
const selectOptions = computed(() =>
  options.value.map((option) => ({ value: option.id, label: option.name })),
)

function onSelect(value: string | number) {
  emit('update', value ? String(value) : null)
}

// ---------- 多选 ----------
const multiOpen = ref(false)
const trigger = ref<HTMLElement | null>(null)
const panel = ref<{ top: number; left: number }>({ top: 0, left: 0 })

/** 读取 body 的 --ui-scale，用于挂到 <html> 下的浮层定位与缩放。 */
function uiScale(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--ui-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function toggleMulti() {
  if (!multiOpen.value && trigger.value) {
    const rect = trigger.value.getBoundingClientRect()
    const scale = uiScale()
    const width = 210 * scale
    const height = 260 * scale
    panel.value = {
      top: Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - height)),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
    }
  }
  multiOpen.value = !multiOpen.value
}

function toggleOption(id: string) {
  const next = multi.value.includes(id)
    ? multi.value.filter((x) => x !== id)
    : [...multi.value, id]
  emit('update', next)
}

// ---------- 复选 ----------
function onCheck(e: Event) {
  emit('update', (e.target as HTMLInputElement).checked)
}

// ---------- 评分 ----------
const rating = computed(() => {
  const n = Number(props.value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(5, Math.round(n)))
})

function setRating(n: number) {
  emit('update', rating.value === n ? 0 : n)
}

// ---------- 进度（0-100） ----------
const progress = ref(0)

watch(
  () => props.value,
  (value) => {
    const n = Number(value)
    progress.value = Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : 0
  },
  { immediate: true },
)

function onProgressInput(e: Event) {
  progress.value = Number((e.target as HTMLInputElement).value)
}

function commitProgress() {
  if (progress.value === Number(props.value ?? 0)) return
  emit('update', progress.value)
}

// ---------- 只读渲染（笔记阅读模式 / 内嵌数据表） ----------
const staticText = computed(() => {
  const value = props.value
  if (value === null || value === undefined || value === '') return ''
  if (props.field.type === 'checkbox') return value ? '是' : '否'
  if (props.field.type === 'select') {
    return options.value.find((option) => option.id === value)?.name ?? ''
  }
  if (props.field.type === 'multi_select') {
    return multiOptions.value.map((option) => option.name).join('、')
  }
  if (props.field.type === 'progress') return `${progress.value}%`
  if (props.field.type === 'attachment') {
    return Array.isArray(value)
      ? value.map((item: any) => String(item?.filename ?? '')).filter(Boolean).join('、')
      : ''
  }
  return String(value)
})

const attachments = computed<{ filename: string; url: string }[]>(() => {
  if (props.field.type !== 'attachment' || !Array.isArray(props.value)) return []
  return props.value
    .map((item: any) => ({
      filename: String(item?.filename ?? ''),
      url: String(item?.url ?? ''),
    }))
    .filter((item) => item.filename && item.url)
})
</script>

<template>
  <div class="min-w-0" :class="{ 'db-boxed': boxed }">
    <!-- 只读：按字段类型呈现纯内容 -->
    <div v-if="readonly" class="db-static-value">
      <template v-if="field.type === 'checkbox'">
        <KiwiIcon
          :name="value ? 'checkSquare' : 'square'"
          :size="13"
          :class="value ? 'text-kiwi-500' : 'text-slate-300'"
        />
      </template>
      <template v-else-if="field.type === 'select'">
        <span
          v-if="selected"
          class="inline-flex max-w-full truncate rounded border px-1.5 py-px text-[10.5px]"
          :class="chipClass(selected.color)"
        >
          {{ selected.name }}
        </span>
        <span v-else class="db-static-empty">—</span>
      </template>
      <template v-else-if="field.type === 'multi_select'">
        <span
          v-for="option in multiOptions"
          :key="option.id"
          class="rounded border px-1.5 py-px text-[10.5px]"
          :class="chipClass(option.color)"
        >
          {{ option.name }}
        </span>
        <span v-if="!multiOptions.length" class="db-static-empty">—</span>
      </template>
      <template v-else-if="field.type === 'rating'">
        <span class="flex items-center gap-0.5">
          <KiwiIcon
            v-for="n in 5"
            :key="n"
            name="star"
            :size="11"
            :class="n <= rating ? 'text-amber-400 fill-current' : 'text-slate-200'"
          />
        </span>
      </template>
      <template v-else-if="field.type === 'progress'">
        <span class="db-progress-static" :class="{ 'is-complete': progress >= 100 }">
          <span class="db-progress-static-track">
            <i :style="{ width: `${progress}%` }" />
          </span>
          <span class="db-progress-static-label">{{ progress }}%</span>
        </span>
      </template>
      <template v-else-if="field.type === 'attachment'">
        <template v-if="attachments.length">
          <span
            v-for="item in attachments"
            :key="item.url"
            class="inline-flex max-w-full items-center gap-0.5"
          >
            <a
              :href="item.url"
              target="_blank"
              rel="noopener"
              class="db-link inline-flex min-w-0 items-center gap-1 truncate hover:underline"
              :title="item.filename"
              @mousedown.stop
            >
              <KiwiIcon name="paperclip" :size="10" class="shrink-0" />
              <span class="truncate">{{ item.filename }}</span>
            </a>
            <a
              :href="item.url"
              :download="item.filename"
              class="db-static-download"
              title="下载附件"
              @mousedown.stop
              @click.stop
            >
              <KiwiIcon name="download" :size="11" />
            </a>
          </span>
        </template>
        <span v-else class="db-static-empty">—</span>
      </template>
      <template v-else-if="field.type === 'url' && staticText">
        <a
          v-if="urlLinkable"
          :href="urlHref(staticText)"
          target="_blank"
          rel="noopener noreferrer"
          class="db-link truncate hover:underline"
          :title="staticText"
          @mousedown.stop
        >{{ staticText }}</a>
        <span v-else class="db-static-text">{{ staticText }}</span>
      </template>
      <template v-else>
        <span v-if="staticText" class="db-static-text">{{ staticText }}</span>
        <span v-else class="db-static-empty">—</span>
      </template>
    </div>

    <template v-else>
    <!-- checkbox -->
    <label v-if="field.type === 'checkbox'" class="flex items-center h-8 px-2 cursor-pointer">
      <input
        type="checkbox"
        class="w-3.5 h-3.5 rounded accent-kiwi-500"
        :checked="!!value"
        @change="onCheck"
      />
    </label>

    <!-- select -->
    <KiwiSelect
      v-else-if="field.type === 'select'"
      class="w-full"
      :model-value="value ?? ''"
      :options="selectOptions"
      width="w-56"
      placeholder="—"
      trigger-class="!h-8 !w-full !justify-between !rounded-md !border-transparent !bg-transparent !px-2 !text-[12px]"
      @update:model-value="onSelect"
    />

    <!-- multi_select -->
    <div v-else-if="field.type === 'multi_select'" class="relative">
      <button
        ref="trigger"
        type="button"
        class="db-input flex items-center gap-1 min-h-8 text-left overflow-hidden"
        @click.stop="toggleMulti"
      >
        <template v-if="multiOptions.length">
          <span
            v-for="opt in multiOptions.slice(0, 2)"
            :key="opt.id"
            class="shrink-0 rounded border px-1 py-px text-[10px] leading-4"
            :class="chipClass(opt.color)"
          >
            {{ opt.name }}
          </span>
          <span v-if="multiOptions.length > 2" class="text-[10px] text-slate-400">
            +{{ multiOptions.length - 2 }}
          </span>
        </template>
        <span v-else class="text-[11px] text-slate-300">选择…</span>
      </button>
      <Teleport to="html">
        <div v-if="multiOpen" class="fixed inset-0 z-[75]" @mousedown="multiOpen = false">
          <!-- 外层定位不带 zoom，内层再缩放，避免 left/top 一起被放大 -->
          <div class="absolute" :style="{ top: `${panel.top}px`, left: `${panel.left}px` }">
            <div
              class="w-[210px] rounded-xl border border-slate-200/70 bg-white/97 backdrop-blur-xl shadow-lifted p-1 max-h-64 overflow-y-auto animate-scale-in"
              :style="{ zoom: 'var(--ui-scale)' }"
              @mousedown.stop
            >
              <button
                v-for="opt in options"
                :key="opt.id"
                type="button"
                class="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-slate-600 hover:bg-kiwi-50"
                @click="toggleOption(opt.id)"
              >
                <span class="w-3.5 h-3.5 grid place-items-center">
                  <KiwiIcon
                    v-if="multi.includes(opt.id)"
                    name="check"
                    :size="12"
                    class="text-kiwi-600"
                  />
                </span>
                <span class="w-2 h-2 rounded-full shrink-0" :class="dotClass(opt.color)" />
                <span class="truncate">{{ opt.name }}</span>
              </button>
              <p v-if="!options.length" class="px-2 py-2 text-[11px] text-slate-400">
                该字段还没有选项
              </p>
            </div>
          </div>
        </div>
      </Teleport>
    </div>

    <!-- date -->
    <KiwiDateInput
      v-else-if="field.type === 'date'"
      :model-value="text"
      trigger-class="!h-8 !w-full !justify-start !rounded-md !border-transparent !bg-transparent !px-2 !text-[12px]"
      @update:model-value="onDatePicked"
    />

    <!-- long_text -->
    <textarea
      v-else-if="field.type === 'long_text'"
      ref="input"
      v-model="text"
      rows="2"
      class="db-textarea"
      @blur="commitText"
      @keydown.ctrl.enter="onEnter"
      @keydown.meta.enter="onEnter"
    />

    <!-- rating -->
    <div v-else-if="field.type === 'rating'" class="flex items-center h-8 px-1 gap-0.5">
      <button
        v-for="n in 5"
        :key="n"
        type="button"
        class="rating-star"
        :class="n <= rating ? 'text-amber-400' : 'text-slate-300 hover:text-amber-300'"
        :title="n <= rating ? `点击清除评分（当前 ${rating} 分）` : `${n} 分`"
        @click="setRating(n)"
      >
        <KiwiIcon name="star" :size="13" :class="n <= rating ? 'fill-current' : ''" />
      </button>
    </div>

    <!-- progress -->
    <div
      v-else-if="field.type === 'progress'"
      class="db-progress"
      :class="{ 'is-complete': progress >= 100 }"
      :style="{ '--db-progress': `${progress}%` }"
    >
      <input
        class="db-progress-input"
        type="range"
        min="0"
        max="100"
        step="1"
        :value="progress"
        :aria-label="field.name"
        @input="onProgressInput"
        @change="commitProgress"
        @mousedown.stop
        @click.stop
      />
      <span class="db-progress-label">{{ progress }}%</span>
    </div>

    <!-- attachment -->
    <DatabaseAttachmentCell
      v-else-if="field.type === 'attachment'"
      :value="value"
      @update="emit('update', $event)"
    />

    <!-- number -->
    <input
      v-else-if="field.type === 'number'"
      ref="input"
      v-model="text"
      type="number"
      class="db-input tabular-nums"
      @blur="commitText"
      @keydown.enter="onEnter"
    />

    <!-- url：默认展示为可点击超链接，点铅笔 / 双击后编辑 -->
    <div v-else-if="field.type === 'url'" class="db-url-view group/url">
      <input
        v-if="urlEditing"
        ref="urlInput"
        v-model="text"
        type="url"
        class="db-input"
        placeholder="https://"
        @blur="finishUrlEdit"
        @keydown.enter.prevent="finishUrlEdit"
        @keydown.esc.prevent="cancelUrlEdit"
      />
      <template v-else>
        <a
          v-if="urlText && urlLinkable"
          :href="urlHref(urlText)"
          target="_blank"
          rel="noopener noreferrer"
          class="db-url-link"
          :title="`${urlText}（双击编辑）`"
          @mousedown.stop
          @click.stop
          @dblclick.stop.prevent="startUrlEdit"
        >
          <KiwiIcon name="external" :size="11" class="db-url-icon" />
          <span class="truncate">{{ urlText }}</span>
        </a>
        <button
          v-else
          type="button"
          class="db-url-link is-plain"
          :class="{ 'is-empty': !urlText }"
          :title="urlText ? `${urlText}（双击编辑）` : '添加链接'"
          @mousedown.stop
          @click.stop="startUrlEdit"
          @dblclick.stop.prevent="startUrlEdit"
        >
          <KiwiIcon name="link2" :size="11" class="db-url-icon" />
          <span class="truncate">{{ urlText || '—' }}</span>
        </button>
        <button
          type="button"
          class="db-url-edit"
          title="编辑链接"
          @mousedown.stop
          @click.stop="startUrlEdit"
        >
          <KiwiIcon name="edit" :size="11" />
        </button>
      </template>
    </div>

    <!-- text -->
    <input
      v-else
      ref="input"
      v-model="text"
      type="text"
      class="db-input"
      @blur="commitText"
      @keydown.enter="onEnter"
    />
    </template>
  </div>
</template>

<style scoped>
.db-static-value {
  @apply flex min-h-8 flex-wrap items-center gap-1 px-2 py-1 text-[12px] text-slate-700;
}
.db-static-text {
  @apply min-w-0 break-words;
  white-space: pre-wrap;
}
.db-static-empty {
  @apply text-[11px] text-slate-300;
}
/* 链接色跟随主题强调色，避免在主题 / 学习模式下仍固定为某一色相。 */
.db-link {
  color: rgb(var(--theme-accent));
  transition: color 0.15s ease;
}
.db-link:hover {
  color: rgb(var(--theme-accent) / 0.78);
}
.db-static-download {
  @apply inline-grid h-4 w-4 shrink-0 place-items-center rounded text-slate-300 transition-colors;
}
.db-static-download:hover {
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
}
/* 链接字段：平时是超链接，悬停显示编辑入口，双击也可进入编辑。 */
.db-url-view {
  @apply flex h-8 min-w-0 items-center gap-0.5 rounded-md px-1.5;
}
.db-url-link {
  @apply inline-flex min-w-0 flex-1 items-center gap-1 truncate text-[12px] outline-none hover:underline;
  color: rgb(var(--theme-accent));
}
.db-url-link.is-plain {
  color: rgb(var(--theme-text-strong));
}
.db-url-link.is-empty {
  color: rgb(var(--theme-text-faint));
}
.db-url-icon {
  @apply shrink-0 opacity-60;
}
.db-url-edit {
  @apply grid h-5 w-5 shrink-0 place-items-center rounded text-slate-300 opacity-40 transition-all group-hover/url:opacity-100 focus:opacity-100;
}
.db-url-edit:hover {
  background: rgb(var(--theme-accent) / 0.1);
  color: rgb(var(--theme-accent));
}
.db-boxed .db-url-view {
  @apply border border-slate-200 bg-white;
}
.db-input {
  @apply w-full h-8 px-2 rounded-md bg-transparent text-[12px] text-slate-700 outline-none border border-transparent transition-colors hover:bg-white/70 focus:bg-white focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60;
}
.db-textarea {
  @apply w-full min-h-[50px] px-2 py-1.5 rounded-md bg-transparent text-[12px] leading-relaxed text-slate-700 outline-none border border-transparent resize-y transition-colors hover:bg-white/70 focus:bg-white focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60;
}
.db-boxed .db-input,
.db-boxed .db-textarea {
  @apply border-slate-200 bg-white;
}
.db-boxed .db-input:hover,
.db-boxed .db-textarea:hover {
  @apply bg-white;
}
.db-boxed .db-input:focus,
.db-boxed .db-textarea:focus {
  @apply border-kiwi-300;
}
.rating-star {
  @apply w-5 h-6 grid place-items-center rounded transition-transform hover:scale-110;
}

/* ---------- 进度字段 ---------- */
.db-progress {
  --db-progress-color: rgb(var(--theme-accent));
  @apply flex h-8 min-w-0 items-center gap-2 px-1.5;
}
.db-progress.is-complete {
  --db-progress-color: rgb(var(--theme-success));
}
.db-progress-input {
  @apply h-4 min-w-[64px] flex-1 cursor-pointer appearance-none bg-transparent;
}
.db-progress-input::-webkit-slider-runnable-track {
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(
    90deg,
    var(--db-progress-color) var(--db-progress, 0%),
    rgb(var(--theme-border)) var(--db-progress, 0%)
  );
}
.db-progress-input::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  margin-top: -3px;
  border: 2px solid var(--db-progress-color);
  border-radius: 999px;
  background: rgb(var(--theme-surface));
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.16);
  transition: transform 0.12s ease;
}
.db-progress-input:hover::-webkit-slider-thumb {
  transform: scale(1.12);
}
.db-progress-input::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: rgb(var(--theme-border));
}
.db-progress-input::-moz-range-progress {
  height: 6px;
  border-radius: 999px;
  background: var(--db-progress-color);
}
.db-progress-input::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border: 2px solid var(--db-progress-color);
  border-radius: 999px;
  background: rgb(var(--theme-surface));
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.16);
}
.db-progress-label {
  @apply w-8 shrink-0 text-right text-[10.5px] tabular-nums text-slate-500;
}
.db-progress-static {
  --db-progress-color: rgb(var(--theme-accent));
  @apply flex w-full min-w-0 items-center gap-1.5;
}
.db-progress-static.is-complete {
  --db-progress-color: rgb(var(--theme-success));
}
.db-progress-static-track {
  @apply relative h-1.5 min-w-[32px] flex-1 overflow-hidden rounded-full bg-slate-200/80;
}
.db-progress-static-track i {
  @apply absolute inset-y-0 left-0 rounded-full;
  background: var(--db-progress-color);
}
.db-progress-static-label {
  @apply w-7 shrink-0 text-right text-[10px] tabular-nums text-slate-500;
}
</style>
