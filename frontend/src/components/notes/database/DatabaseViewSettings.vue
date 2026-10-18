<script setup lang="ts">
/** 视图设置：名称与各视图的字段配置。 */
import { computed, ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { OPTION_COLORS, dotClass } from './colors'
import type { DbField, DbView, ViewType } from '@/stores/noteDatabase'

const props = defineProps<{
  open: boolean
  fields: DbField[]
  view: DbView | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', view: DbView): void
}>()

const local = ref<DbView | null>(null)
const error = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open || !props.view) return
    local.value = {
      ...props.view,
      hidden_fields: [...(props.view.hidden_fields ?? [])],
      display_fields: Array.isArray(props.view.display_fields)
        ? [...props.view.display_fields]
        : null,
    }
    error.value = ''
  },
  { immediate: true },
)

const selectFields = computed(() => props.fields.filter((f) => f.type === 'select'))
const dateFields = computed(() => props.fields.filter((f) => f.type === 'date'))
const textFields = computed(() =>
  props.fields.filter((f) => ['text', 'long_text', 'url', 'select'].includes(f.type)),
)
const endDateFields = computed(() =>
  dateFields.value.filter((f) => f.id !== local.value?.date_field),
)
const allFields = computed(() => props.fields)
const kanbanTitleField = computed(
  () =>
    props.fields.find((f) => f.type === 'text') ??
    props.fields.find((f) => f.type === 'long_text') ??
    props.fields.find((f) => f.type === 'url') ??
    null,
)
const kanbanDisplayOptions = computed(() =>
  props.fields.filter(
    (f) => f.id !== local.value?.group_field && f.id !== kanbanTitleField.value?.id,
  ),
)

const TYPE_LABEL: Record<ViewType, string> = {
  table: '表格',
  kanban: '看板',
  gallery: '画册',
  calendar: '日历',
}
const TYPE_ICON: Record<ViewType, string> = {
  table: 'table',
  kanban: 'kanban',
  gallery: 'gallery',
  calendar: 'calendar',
}

function toggleHidden(fieldId: string) {
  if (!local.value) return
  const hidden = local.value.hidden_fields ?? []
  local.value.hidden_fields = hidden.includes(fieldId)
    ? hidden.filter((id) => id !== fieldId)
    : [...hidden, fieldId]
}

function toggleDisplayField(fieldId: string) {
  if (!local.value) return
  const current = local.value.display_fields ?? []
  local.value.display_fields = current.includes(fieldId)
    ? current.filter((id) => id !== fieldId)
    : [...current, fieldId]
}

function save() {
  if (!local.value) return
  error.value = ''
  if (!local.value.name.trim()) {
    error.value = '视图名称不能为空'
    return
  }
  const view: DbView = { ...local.value, name: local.value.name.trim() }
  if (view.type === 'kanban' && !view.group_field) {
    error.value = '请选择看板分组字段'
    return
  }
  if (view.type === 'kanban' && Array.isArray(view.display_fields)) {
    view.display_fields = view.display_fields.filter((id) => id !== view.group_field)
  }
  if (view.type === 'calendar') {
    if (!view.date_field) {
      error.value = '请选择日历日期字段'
      return
    }
    if (view.end_field === view.date_field) view.end_field = null
    if (view.end_field && !dateFields.value.some((f) => f.id === view.end_field)) {
      view.end_field = null
    }
  }
  emit('save', view)
}
</script>

<template>
  <KiwiModal :open="open && !!local" title="视图设置" max-w="max-w-md" @close="emit('close')">
    <div v-if="local" class="space-y-3.5">
      <div class="flex items-center gap-2 rounded-xl bg-kiwi-50/60 border border-kiwi-100/70 px-3 py-2">
        <KiwiIcon :name="TYPE_ICON[local.type]" :size="14" class="text-kiwi-500" />
        <span class="text-[12px] text-kiwi-700">{{ TYPE_LABEL[local.type] }}视图</span>
        <span class="text-[10px] text-kiwi-400">所有视图共享同一批记录</span>
      </div>

      <div class="flex items-center gap-3">
        <span class="w-20 shrink-0 text-[11.5px] text-slate-500">视图名称</span>
        <input v-model="local.name" class="kiwi-input !py-1.5 !text-[12px]" />
      </div>

      <!-- 表格：隐藏字段 -->
      <div v-if="local.type === 'table'" class="flex items-start gap-3">
        <span class="w-20 shrink-0 pt-1 text-[11.5px] text-slate-500">显示字段</span>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="field in allFields"
            :key="field.id"
            type="button"
            class="rounded-lg border px-2 py-1 text-[11px] transition-colors"
            :class="
              (local.hidden_fields ?? []).includes(field.id)
                ? 'border-slate-200 bg-slate-50 text-slate-300 line-through'
                : 'border-kiwi-200 bg-kiwi-50/60 text-kiwi-700'
            "
            @click="toggleHidden(field.id)"
          >
            {{ field.name }}
          </button>
        </div>
      </div>

      <!-- 看板：分组字段 / 卡片显示字段 -->
      <template v-else-if="local.type === 'kanban'">
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">分组字段</span>
          <select
            v-model="local.group_field"
            class="flex-1 h-8 rounded-lg border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-600 outline-none focus:border-kiwi-300"
          >
            <option :value="null">请选择单选字段</option>
            <option v-for="field in selectFields" :key="field.id" :value="field.id">
              {{ field.name }}
            </option>
          </select>
        </div>
        <div class="flex items-start gap-3">
          <span class="w-20 shrink-0 pt-1 text-[11.5px] text-slate-500">显示字段</span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="field in kanbanDisplayOptions"
                :key="field.id"
                type="button"
                class="rounded-lg border px-2 py-1 text-[11px] transition-colors"
                :class="
                  (local.display_fields ?? []).includes(field.id)
                    ? 'border-kiwi-200 bg-kiwi-50/60 text-kiwi-700'
                    : 'border-slate-200 bg-white/80 text-slate-400 hover:border-kiwi-200'
                "
                @click="toggleDisplayField(field.id)"
              >
                {{ field.name }}
              </button>
            </div>
            <div class="mt-1.5 flex items-center gap-2 text-[10.5px] text-slate-400">
              <span v-if="local.display_fields === null">
                未选择时自动展示前 2 个字段
              </span>
              <span v-else-if="!(local.display_fields?.length)">
                当前不展示额外字段
              </span>
              <span v-else>已选择 {{ local.display_fields?.length }} 个字段</span>
              <button
                v-if="local.display_fields !== null"
                type="button"
                class="text-kiwi-500 hover:text-kiwi-700"
                @click="local.display_fields = null"
              >
                恢复自动
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- 画册：封面 / 标题 -->
      <template v-else-if="local.type === 'gallery'">
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">封面字段</span>
          <select
            v-model="local.cover_field"
            class="flex-1 h-8 rounded-lg border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-600 outline-none focus:border-kiwi-300"
          >
            <option :value="null">无封面</option>
            <option v-for="field in textFields" :key="field.id" :value="field.id">
              {{ field.name }}
            </option>
          </select>
        </div>
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">标题字段</span>
          <select
            v-model="local.title_field"
            class="flex-1 h-8 rounded-lg border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-600 outline-none focus:border-kiwi-300"
          >
            <option :value="null">默认</option>
            <option v-for="field in textFields" :key="field.id" :value="field.id">
              {{ field.name }}
            </option>
          </select>
        </div>
        <p class="pl-[92px] text-[10.5px] text-slate-400">封面字段为图片 URL 时显示图片，否则显示渐变占位。</p>
      </template>

      <!-- 日历：日期 / 标题 -->
      <template v-else>
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">日期字段</span>
          <select
            v-model="local.date_field"
            class="flex-1 h-8 rounded-lg border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-600 outline-none focus:border-kiwi-300"
          >
            <option :value="null">请选择日期字段</option>
            <option v-for="field in dateFields" :key="field.id" :value="field.id">
              {{ field.name }}
            </option>
          </select>
        </div>
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">结束日期</span>
          <select
            v-model="local.end_field"
            class="flex-1 h-8 rounded-lg border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-600 outline-none focus:border-kiwi-300"
          >
            <option :value="null">无（单日事件）</option>
            <option v-for="field in endDateFields" :key="field.id" :value="field.id">
              {{ field.name }}
            </option>
          </select>
        </div>
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">横条颜色</span>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              class="h-6 rounded-md border px-2 text-[10.5px] transition-colors"
              :class="
                !local.bar_color
                  ? 'border-kiwi-300 bg-kiwi-50 text-kiwi-600'
                  : 'border-slate-200 bg-white/80 text-slate-500 hover:border-kiwi-200'
              "
              title="按记录自动配色，同一天自动错开颜色"
              @click="local.bar_color = null"
            >
              自动
            </button>
            <button
              v-for="color in OPTION_COLORS"
              :key="color"
              type="button"
              class="w-5 h-5 grid place-items-center rounded-full ring-2 ring-offset-1 transition-transform hover:scale-110"
              :class="[dotClass(color), local.bar_color === color ? 'ring-kiwi-400' : 'ring-transparent']"
              :title="color"
              @click="local.bar_color = color"
            >
              <KiwiIcon
                v-if="local.bar_color === color"
                name="check"
                :size="10"
                class="text-white drop-shadow"
              />
            </button>
          </div>
        </div>
        <p class="pl-[92px] text-[10.5px] text-slate-400">
          颜色逐条作用于记录：同一天有交集的多条记录会自动使用不同颜色；“自动”优先沿用记录单选字段的颜色，悬停横条可高亮查看。
        </p>
        <div class="flex items-center gap-3">
          <span class="w-20 shrink-0 text-[11.5px] text-slate-500">标题字段</span>
          <select
            v-model="local.title_field"
            class="flex-1 h-8 rounded-lg border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-600 outline-none focus:border-kiwi-300"
          >
            <option :value="null">默认</option>
            <option v-for="field in textFields" :key="field.id" :value="field.id">
              {{ field.name }}
            </option>
          </select>
        </div>
      </template>

      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>
    </div>

    <div class="flex justify-end gap-2 mt-5">
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button class="kiwi-btn-primary" @click="save">保存视图</button>
    </div>
  </KiwiModal>
</template>
