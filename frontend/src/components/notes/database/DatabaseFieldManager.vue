<script setup lang="ts">
/** 字段管理：新增/重命名/调整类型/选项编辑/排序/删除。 */
import { ref, watch } from 'vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import { FIELD_TYPES, fieldTypeMeta } from './meta'
import { OPTION_COLORS, dotClass } from './colors'
import { newFieldId, type DbField, type FieldType, type SelectOption } from '@/stores/noteDatabase'

const props = defineProps<{ open: boolean; fields: DbField[] }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', fields: DbField[]): void
}>()

let seq = 0
function optionId() {
  seq += 1
  return `o_${Date.now().toString(36)}_${seq}`
}

const draft = ref<DbField[]>([])
const newName = ref('')
const newType = ref<FieldType>('text')
const error = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    draft.value = props.fields.map((f) => ({
      ...f,
      options: f.options?.map((o) => ({ ...o })),
    }))
    newName.value = ''
    newType.value = 'text'
    error.value = ''
  },
  { immediate: true },
)

function addField() {
  const name = newName.value.trim()
  if (!name) return
  draft.value.push({
    id: newFieldId(),
    name,
    type: newType.value,
    ...(newType.value === 'select' || newType.value === 'multi_select'
      ? { options: [] }
      : {}),
  })
  newName.value = ''
  newType.value = 'text'
}

function removeField(index: number) {
  if (draft.value.length <= 1) {
    error.value = '至少保留一个字段'
    return
  }
  draft.value.splice(index, 1)
}

function moveField(index: number, delta: number) {
  const next = index + delta
  if (next < 0 || next >= draft.value.length) return
  const [item] = draft.value.splice(index, 1)
  draft.value.splice(next, 0, item)
}

function onTypeChange(field: DbField, type: FieldType) {
  field.type = type
  if ((type === 'select' || type === 'multi_select') && !field.options) {
    field.options = []
  }
}

function addOption(field: DbField) {
  const options = (field.options ??= [])
  const color = OPTION_COLORS[options.length % OPTION_COLORS.length]
  const option: SelectOption = {
    id: optionId(),
    name: `选项 ${options.length + 1}`,
    color,
  }
  options.push(option)
}

function removeOption(field: DbField, index: number) {
  field.options?.splice(index, 1)
}

function cycleColor(field: DbField, option: SelectOption) {
  const idx = OPTION_COLORS.indexOf((option.color ?? 'slate') as any)
  option.color = OPTION_COLORS[(idx + 1) % OPTION_COLORS.length]
}

function save() {
  error.value = ''
  const cleaned: DbField[] = []
  for (const field of draft.value) {
    const name = field.name.trim()
    if (!name) {
      error.value = '字段名称不能为空'
      return
    }
    const item: DbField = { id: field.id, name, type: field.type }
    if (field.type === 'select' || field.type === 'multi_select') {
      const options: SelectOption[] = []
      for (const option of field.options ?? []) {
        const optionName = option.name.trim()
        if (!optionName) {
          error.value = `字段「${name}」存在空选项`
          return
        }
        options.push({ id: option.id, name: optionName, color: option.color })
      }
      item.options = options
    }
    cleaned.push(item)
  }
  emit('save', cleaned)
}
</script>

<template>
  <KiwiModal :open="open" title="字段管理" max-w="max-w-2xl" @close="emit('close')">
    <div class="max-h-[58vh] overflow-y-auto -mx-1 px-1 space-y-2">
      <div
        v-for="(field, index) in draft"
        :key="field.id"
        class="rounded-xl border border-slate-200/70 bg-white/60 p-2.5"
      >
        <div class="flex items-center gap-2">
          <span class="w-6 h-6 grid place-items-center rounded-md bg-kiwi-50 text-kiwi-500 shrink-0">
            <KiwiIcon :name="fieldTypeMeta(field.type).icon" :size="12" />
          </span>
          <input
            v-model="field.name"
            class="min-w-0 flex-1 h-7 rounded-md border border-slate-200/80 bg-white/80 px-2 text-[12px] text-slate-700 outline-none focus:border-kiwi-300 focus:ring-2 focus:ring-kiwi-200/60"
          />
          <select
            :value="field.type"
            class="h-7 rounded-md border border-slate-200/80 bg-white/80 px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
            @change="onTypeChange(field, ($event.target as HTMLSelectElement).value as FieldType)"
          >
            <option v-for="meta in FIELD_TYPES" :key="meta.type" :value="meta.type">
              {{ meta.label }}
            </option>
          </select>
          <div class="flex items-center">
            <button class="fm-icon" title="上移" :disabled="index === 0" @click="moveField(index, -1)">
              <KiwiIcon name="chevron" :size="11" class="rotate-180" />
            </button>
            <button
              class="fm-icon"
              title="下移"
              :disabled="index === draft.length - 1"
              @click="moveField(index, 1)"
            >
              <KiwiIcon name="chevron" :size="11" />
            </button>
            <button class="fm-icon hover:!text-rose-500" title="删除字段" @click="removeField(index)">
              <KiwiIcon name="trash" :size="12" />
            </button>
          </div>
        </div>

        <div
          v-if="field.type === 'select' || field.type === 'multi_select'"
          class="mt-2 pl-8 space-y-1"
        >
          <div
            v-for="(option, oi) in field.options ?? []"
            :key="option.id"
            class="flex items-center gap-1.5"
          >
            <button
              type="button"
              class="w-2.5 h-2.5 rounded-full shrink-0 ring-2 ring-white"
              :class="dotClass(option.color)"
              title="切换颜色"
              @click="cycleColor(field, option)"
            />
            <input
              v-model="option.name"
              class="min-w-0 flex-1 h-6 rounded-md border border-slate-200/70 bg-white/70 px-1.5 text-[11px] text-slate-600 outline-none focus:border-kiwi-300"
            />
            <button class="fm-icon" title="删除选项" @click="removeOption(field, oi)">
              <KiwiIcon name="close" :size="10" />
            </button>
          </div>
          <button
            type="button"
            class="flex items-center gap-1 text-[10.5px] text-slate-400 hover:text-kiwi-600"
            @click="addOption(field)"
          >
            <KiwiIcon name="plus" :size="10" />
            添加选项
          </button>
        </div>
      </div>

      <div class="flex items-center gap-2 rounded-xl border border-dashed border-slate-200/80 p-2">
        <input
          v-model="newName"
          class="min-w-0 flex-1 h-7 rounded-md border border-slate-200/80 bg-white/80 px-2 text-[12px] outline-none focus:border-kiwi-300"
          placeholder="新字段名称"
          @keyup.enter="addField"
        />
        <select
          v-model="newType"
          class="h-7 rounded-md border border-slate-200/80 bg-white/80 px-1.5 text-[11px] text-slate-600 outline-none"
        >
          <option v-for="meta in FIELD_TYPES" :key="meta.type" :value="meta.type">
            {{ meta.label }}
          </option>
        </select>
        <button class="kiwi-btn-secondary !py-1 !px-2.5 !text-[11px]" :disabled="!newName.trim()" @click="addField">
          <KiwiIcon name="plus" :size="12" />
          添加
        </button>
      </div>

      <p v-if="error" class="text-[11.5px] text-rose-500">{{ error }}</p>
    </div>

    <div class="flex justify-end gap-2 mt-4">
      <button class="kiwi-btn-secondary" @click="emit('close')">取消</button>
      <button class="kiwi-btn-primary" @click="save">保存字段</button>
    </div>
  </KiwiModal>
</template>

<style scoped>
.fm-icon {
  @apply w-6 h-6 grid place-items-center rounded-md text-slate-300 transition-colors hover:bg-kiwi-50 hover:text-kiwi-600 disabled:opacity-30 disabled:pointer-events-none;
}
</style>
