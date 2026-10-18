<script setup lang="ts">
/** 新建菜单：模板 / 快速捕获 / 文档 / 画布 / 数据表 / 导入 / 分组 / 链接。 */
import KiwiDropdown from '@/components/ui/KiwiDropdown.vue'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'

const emit = defineEmits<{
  (e: 'template'): void
  (e: 'capture'): void
  (e: 'doc'): void
  (e: 'canvas'): void
  (e: 'database'): void
  (e: 'notebook'): void
  (e: 'import'): void
  (e: 'folder'): void
  (e: 'link'): void
}>()

const items = [
  { key: 'template', label: '从模板新建', hint: '内置结构 · 自定义模板', icon: 'layoutTemplate', tone: 'text-kiwi-500' },
  { key: 'capture', label: '快速捕获', hint: '零散想法 → 收件箱', icon: 'send', tone: 'text-rose-400' },
  { key: 'doc', label: '文档', hint: '富文本 · Markdown', icon: 'fileText', tone: 'text-blue-500' },
  { key: 'canvas', label: '画布', hint: '工程图 / 思维导图 · 模板', icon: 'pen', tone: 'text-violet-500' },
  { key: 'database', label: '数据表', hint: '表格 / 看板 / 画册 / 日历', icon: 'database', tone: 'text-kiwi-500' },
  { key: 'notebook', label: 'Notebook', hint: '代码 / 分析 · 沙箱执行', icon: 'notebook', tone: 'text-indigo-500' },
  { key: 'import', label: '导入文件', hint: '解析为可编辑文档', icon: 'fileImport', tone: 'text-emerald-500' },
  { key: 'folder', label: '分组', hint: '整理工作区条目', icon: 'folder', tone: 'text-amber-400' },
  { key: 'link', label: '链接', hint: '抓取网页正文', icon: 'link2', tone: 'text-sky-500' },
] as const

function choose(key: (typeof items)[number]['key'], close: () => void) {
  close()
  switch (key) {
    case 'template':
      emit('template')
      break
    case 'capture':
      emit('capture')
      break
    case 'doc':
      emit('doc')
      break
    case 'canvas':
      emit('canvas')
      break
    case 'database':
      emit('database')
      break
    case 'notebook':
      emit('notebook')
      break
    case 'import':
      emit('import')
      break
    case 'folder':
      emit('folder')
      break
    case 'link':
      emit('link')
      break
  }
}
</script>

<template>
  <KiwiDropdown width="w-60">
    <template #trigger="{ open }">
      <button
        type="button"
        class="w-7 h-7 grid place-items-center rounded-lg text-slate-500 transition-colors hover:bg-kiwi-50 hover:text-kiwi-700"
        :class="open ? 'bg-kiwi-50 text-kiwi-700' : ''"
        title="新建"
      >
        <KiwiIcon name="plus" :size="15" />
      </button>
    </template>
    <template #default="{ close }">
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        class="w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-kiwi-50/80"
        @click="choose(item.key, close)"
      >
        <span class="w-7 h-7 grid place-items-center rounded-lg bg-white/80 border border-slate-200/70" :class="item.tone">
          <KiwiIcon :name="item.icon" :size="14" />
        </span>
        <span class="min-w-0">
          <span class="block text-[12.5px] font-medium text-slate-700">{{ item.label }}</span>
          <span class="block text-[10px] text-slate-400 truncate">{{ item.hint }}</span>
        </span>
      </button>
    </template>
  </KiwiDropdown>
</template>
