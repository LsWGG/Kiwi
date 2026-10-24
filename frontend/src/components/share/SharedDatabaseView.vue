<script setup lang="ts">
/** 公开分享页的数据表只读视图：字段表头 + 记录表格。 */
import { computed } from 'vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

interface ShareOption {
  id: string
  name: string
  color?: string
}

interface ShareField {
  id: string
  name?: string
  type?: string
  options?: ShareOption[]
}

interface ShareRow {
  id: string
  data?: Record<string, unknown>
}

interface DatabasePayload {
  name?: string
  description?: string
  fields?: ShareField[]
  rows?: ShareRow[]
  total_rows?: number
  truncated?: boolean
}

interface AttachmentItem {
  filename: string
  url: string
}

const props = defineProps<{ payload?: DatabasePayload | null }>()

const fields = computed(() =>
  (props.payload?.fields || []).filter(
    (field): field is ShareField =>
      !!field && typeof field === 'object' && typeof field.id === 'string',
  ),
)
const rows = computed(() =>
  (props.payload?.rows || []).filter(
    (row): row is ShareRow => !!row && typeof row === 'object' && typeof row.id === 'string',
  ),
)
const totalRows = computed(() => Number(props.payload?.total_rows ?? rows.value.length) || 0)

function safeHref(url: string): boolean {
  if (/^https?:\/\//i.test(url)) return true
  return url.startsWith('/') && !url.startsWith('//')
}

function optionName(field: ShareField, raw: unknown): string {
  if (raw === null || raw === undefined) return ''
  if (typeof raw === 'object') {
    const value = raw as Record<string, unknown>
    return String(value.name || value.label || value.id || '')
  }
  const text = String(raw)
  const option = (field.options || []).find(
    (item) => String(item.id) === text || item.name === text,
  )
  return option?.name || text
}

function attachmentItems(value: unknown): AttachmentItem[] {
  const list = Array.isArray(value) ? value : value ? [value] : []
  const items: AttachmentItem[] = []
  for (const item of list) {
    if (typeof item === 'string') {
      if (!safeHref(item)) continue
      items.push({ filename: item.split('/').pop() || item, url: item })
      continue
    }
    if (item && typeof item === 'object') {
      const record = item as Record<string, unknown>
      const url = String(record.url || '')
      if (!url || !safeHref(url)) continue
      items.push({
        filename: String(record.filename || record.name || url.split('/').pop() || '附件'),
        url,
      })
    }
  }
  return items
}

function displayValue(field: ShareField, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  switch (field.type) {
    case 'select':
      return optionName(field, value)
    case 'multi_select': {
      const list = Array.isArray(value) ? value : [value]
      return list.map((item) => optionName(field, item)).filter(Boolean).join('、')
    }
    case 'checkbox':
      return value ? '是' : '否'
    case 'attachment':
      return attachmentItems(value)
        .map((item) => item.filename)
        .join('、')
    default:
      if (Array.isArray(value)) return value.map((item) => String(item)).join('、')
      if (typeof value === 'object') {
        const record = value as Record<string, unknown>
        return String(record.name || record.label || JSON.stringify(value))
      }
      return String(value)
  }
}

function rowValue(row: ShareRow, field: ShareField): unknown {
  return (row.data || {})[field.id]
}

function isLinkField(field: ShareField): boolean {
  return field.type === 'url'
}

function isAttachmentField(field: ShareField): boolean {
  return field.type === 'attachment'
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
      <span class="inline-flex items-center gap-1">
        <KiwiIcon name="database" :size="11" />
        共 {{ totalRows }} 条记录 · {{ fields.length }} 个字段
      </span>
      <span v-if="payload?.description" class="truncate">{{ payload.description }}</span>
    </div>

    <div class="overflow-hidden rounded-2xl border border-slate-200/70 bg-white/85 shadow-soft">
      <div class="max-h-[68vh] overflow-auto">
        <table class="w-full min-w-max border-collapse text-left text-[12px]">
          <thead class="sticky top-0 z-10 bg-slate-50/95 backdrop-blur">
            <tr class="border-b border-slate-200/80">
              <th class="w-10 px-3 py-2.5 text-[10.5px] font-medium text-slate-400">#</th>
              <th
                v-for="field in fields"
                :key="field.id"
                class="min-w-[120px] whitespace-nowrap px-3 py-2.5 text-[11px] font-semibold text-slate-600"
              >
                {{ field.name || field.id }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in rows"
              :key="row.id"
              class="border-b border-slate-100/80 transition-colors last:border-0 hover:bg-kiwi-50/40"
            >
              <td class="px-3 py-2 text-[10.5px] text-slate-300">{{ index + 1 }}</td>
              <td
                v-for="field in fields"
                :key="field.id"
                class="max-w-[280px] px-3 py-2 align-top text-slate-600"
              >
                <template v-if="isAttachmentField(field)">
                  <span
                    v-for="item in attachmentItems(rowValue(row, field))"
                    :key="item.url"
                    class="mr-2 inline-flex items-center gap-1 text-kiwi-700 hover:underline"
                  >
                    <a
                      :href="item.url"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="inline-flex items-center gap-1"
                    >
                      <KiwiIcon name="paperclip" :size="10" />
                      {{ item.filename }}
                    </a>
                  </span>
                </template>
                <a
                  v-else-if="isLinkField(field) && safeHref(String(rowValue(row, field) || ''))"
                  :href="String(rowValue(row, field))"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="break-all text-sky-600 hover:underline"
                >
                  {{ displayValue(field, rowValue(row, field)) }}
                </a>
                <span v-else class="line-clamp-3 whitespace-pre-wrap">
                  {{ displayValue(field, rowValue(row, field)) }}
                </span>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td
                :colspan="fields.length + 1"
                class="px-4 py-16 text-center text-[12px] text-slate-400"
              >
                数据表还没有记录。
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <p v-if="payload?.truncated" class="mt-2 text-center text-[10.5px] text-slate-400">
      仅展示前 {{ rows.length }} 条，共 {{ totalRows }} 条记录。
    </p>
  </div>
</template>
