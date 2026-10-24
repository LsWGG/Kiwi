<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useLlmStore, LlmConfig } from '@/stores/llm'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import KiwiModal from '@/components/ui/KiwiModal.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { toast } from '@/components/ui/toast'

/** embedded：作为「模型配置」子页渲染时隐藏独立页头与设置导航。 */
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const llm = useLlmStore()
const editing = ref(false)
const editId = ref<string | null>(null)
const form = ref({
  name: '',
  base_url: '',
  api_key: '',
  model_name: '',
  is_default: false,
})
const testMsg = ref<{ ok: boolean; message: string } | null>(null)
const testing = ref(false)
const modelLoading = ref(false)
const saving = ref(false)
const showDelete = ref<string | null>(null)
const removing = ref(false)

onMounted(() => llm.fetchConfigs())

// 从已存配置编辑
function startEdit(c?: LlmConfig) {
  editing.value = true
  testMsg.value = null
  if (c) {
    editId.value = c.id
    form.value = {
      name: c.name,
      base_url: c.base_url,
      api_key: '',
      model_name: c.model_name,
      is_default: c.is_default,
    }
  } else {
    editId.value = null
    form.value = {
      name: '',
      base_url: '',
      api_key: '',
      model_name: '',
      is_default: false,
    }
  }
}

async function loadModels() {
  if (!form.value.base_url) {
    toast.info('先填写 Base URL')
    return
  }
  modelLoading.value = true
  try {
    await llm.fetchModels(form.value.base_url.trim(), form.value.api_key || undefined)
    if (llm.models.length) toast.success(`找到 ${llm.models.length} 个模型`)
  } catch (e: any) {
    testMsg.value = { ok: false, message: `拉取模型列表失败：${e.message}` }
  } finally {
    modelLoading.value = false
  }
}

async function testConn() {
  if (!form.value.base_url || !form.value.model_name) {
    toast.info('请先填写 base_url 并选择模型')
    return
  }
  testing.value = true
  testMsg.value = null
  try {
    const res = await llm.testConnection(
      form.value.base_url.trim(),
      form.value.model_name,
      form.value.api_key || undefined,
    )
    testMsg.value = { ok: res.ok, message: res.message }
    if (res.ok) toast.success('连接成功')
    else toast.error(res.message)
  } catch (e: any) {
    testMsg.value = { ok: false, message: e.message }
    toast.error(e.message)
  } finally {
    testing.value = false
  }
}

async function save() {
  if (!form.value.base_url || !form.value.model_name) {
    toast.info('请填写 Base URL 与模型')
    return
  }
  saving.value = true
  const payload = {
    name: form.value.name || form.value.model_name,
    base_url: form.value.base_url.trim(),
    api_key: form.value.api_key || undefined,
    model_name: form.value.model_name,
    is_default: form.value.is_default,
  }
  try {
    if (editId.value) {
      await llm.updateConfig(editId.value, payload)
      toast.success('配置已更新')
    } else {
      await llm.createConfig(payload)
      toast.success('配置已添加')
    }
    editing.value = false
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    saving.value = false
  }
}

async function doDelete() {
  if (!showDelete.value) return
  removing.value = true
  try {
    await llm.deleteConfig(showDelete.value)
    toast.success('配置已删除')
    showDelete.value = null
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    removing.value = false
  }
}

// 切换 default 时显示说明
watch(() => form.value.base_url, () => (testMsg.value = null))

const canSave = computed(() => form.value.base_url.trim() && form.value.model_name)
</script>

<template>
  <div :class="embedded ? '' : 'page-wrap-slim px-8 py-8'">
    <!-- 页头 -->
    <div v-if="!embedded" class="flex items-end justify-between mb-5 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="w-10 h-10 rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 grid place-items-center text-white shadow-glow"
        >
          <KiwiIcon name="settings" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">大模型配置</h1>
          <p class="text-sm text-slate-500 mt-1">
            支持任何 OpenAI 兼容端点。密钥加密存储。级联：知识库默认 &gt; 全局默认。
          </p>
        </div>
      </div>
      <button v-if="!editing" class="kiwi-btn-primary animate-fade-up" @click="startEdit()">
        <KiwiIcon name="plus" :size="16" />
        新增配置
      </button>
    </div>

    <SettingsTabs v-if="!embedded" />

    <!-- 嵌入「模型配置」时保留新增入口，与向量 / OCR 页签的操作位置一致 -->
    <div v-if="embedded" class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p class="text-xs leading-relaxed text-slate-500">
        支持任何 OpenAI 兼容端点；密钥加密存储。级联：知识库默认 &gt; 全局默认。
      </p>
      <button v-if="!editing" class="kiwi-btn-primary !py-1.5 !text-xs" @click="startEdit()">
        <KiwiIcon name="plus" :size="13" />
        新增配置
      </button>
    </div>

    <!-- 编辑表单 -->
    <div
      v-if="editing"
      class="mb-6 rounded-2xl glass-strong p-6 space-y-5 animate-scale-in"
    >
      <div>
        <label class="text-xs font-medium text-slate-500">名称</label>
        <input
          v-model="form.name"
          class="kiwi-input mt-1.5"
          placeholder="如：Ollama 本地"
        />
      </div>
      <div>
        <label class="text-xs font-medium text-slate-500">Base URL（不加 /v1）</label>
        <div class="flex gap-2 mt-1.5">
          <input
            v-model="form.base_url"
            class="kiwi-input"
            placeholder="http://localhost:11434"
          />
          <button
            class="kiwi-btn-secondary !px-3 !py-2 shrink-0"
            :disabled="modelLoading"
            @click="loadModels"
          >
            <KiwiIcon name="loader" :size="13" :spin="modelLoading" />
            {{ modelLoading ? '加载中' : '加载模型' }}
          </button>
        </div>
        <p class="text-[11px] text-slate-400 mt-1.5">从该服务商的 /v1/models 动态拉取模型下拉</p>
      </div>
      <div>
        <label class="text-xs font-medium text-slate-500">API Key（可选，Ollama 留空）</label>
        <input
          v-model="form.api_key"
          type="password"
          name="llm-api-key"
          class="kiwi-input mt-1.5"
          placeholder="sk-…"
          autocomplete="new-password"
          spellcheck="false"
        />
      </div>
      <div>
        <label class="text-xs font-medium text-slate-500">模型</label>
        <select v-model="form.model_name" class="kiwi-input mt-1.5 bg-white/70 cursor-pointer">
          <option value="">下拉挑选或手动输入</option>
          <option v-for="m in llm.models" :key="m.id" :value="m.id">{{ m.id }}</option>
        </select>
        <p v-if="!llm.models.length" class="text-[11px] text-slate-400 mt-1.5">
          {{ modelLoading ? '加载中…' : '点击「加载模型」或直接输入模型名' }}
        </p>
      </div>

      <label class="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
        <input v-model="form.is_default" type="checkbox" class="accent-kiwi-600 w-4 h-4" />
        设为系统默认模型
      </label>

      <p
        v-if="testMsg"
        class="text-sm flex items-center gap-1.5"
        :class="testMsg.ok ? 'text-emerald-600' : 'text-red-500'"
      >
        <KiwiIcon :name="testMsg.ok ? 'check' : 'alert'" :size="14" />
        {{ testMsg.message }}
      </p>

      <div class="flex gap-2 justify-end pt-1">
        <button class="kiwi-btn-ghost" @click="editing = false">取消</button>
        <button class="kiwi-btn-secondary" :disabled="testing" @click="testConn">
          <KiwiIcon name="loader" :size="13" :spin="testing" />
          {{ testing ? '测试中…' : '测试连接' }}
        </button>
        <button class="kiwi-btn-primary" :disabled="!canSave" :loading="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
      <p class="text-[11px] text-slate-400">保存前请先「测试连接」。更新配置时不填 Key 则保留原值。</p>
    </div>

    <!-- 配置列表 -->
    <div v-if="llm.configs.length" class="space-y-2">
      <div
        v-for="(c, i) in llm.configs"
        :key="c.id"
        class="group kiwi-card !shadow-soft p-4 flex items-center gap-3 animate-fade-up"
        :style="{ animationDelay: `${i * 50}ms` }"
      >
        <span class="w-9 h-9 shrink-0 grid place-items-center rounded-xl bg-gradient-to-br from-slate-100 to-white border border-slate-200/60 text-slate-500 group-hover:text-kiwi-600 group-hover:border-kiwi-200 transition-all">
          <KiwiIcon name="settings" :size="16" />
        </span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <p class="font-medium text-slate-700 truncate">{{ c.name }}</p>
            <span
              v-if="c.is_default"
              class="text-[10px] px-2 py-[1px] rounded-full bg-gradient-to-r from-kiwi-500 to-kiwi-700 text-white"
            >默认</span>
          </div>
          <p class="text-xs text-slate-400 mt-0.5 truncate font-mono">
            {{ c.base_url.replace(/^https?:\/\//, '') }} · {{ c.model_name }}
          </p>
        </div>
        <span class="text-xs text-slate-400 shrink-0 flex items-center gap-1" :title="c.has_api_key ? '已配置密钥' : '无密钥'">
          <KiwiIcon :name="c.has_api_key ? 'check' : 'close'" :size="12" :class="c.has_api_key ? 'text-emerald-500' : 'text-slate-300'" />
          {{ c.has_api_key ? '有 Key' : '无 Key' }}
        </span>
        <button class="kiwi-btn-ghost !px-2.5 !py-1 text-xs shrink-0" @click="startEdit(c)">
          <KiwiIcon name="edit" :size="13" />
          编辑
        </button>
        <button class="kiwi-btn-ghost !px-2.5 !py-1 text-xs shrink-0 !text-slate-400 hover:!text-red-500" @click="showDelete = c.id">
          <KiwiIcon name="trash" :size="13" />
        </button>
      </div>
    </div>

    <div v-else-if="!llm.configs.length && !editing" class="text-center py-14">
      <div class="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-br from-kiwi-100 to-white border border-kiwi-100 grid place-items-center text-kiwi-400 mb-4">
        <KiwiIcon name="settings" :size="26" />
      </div>
      <p class="text-sm text-slate-500">还没有模型配置</p>
      <p class="text-xs text-slate-400 mt-1.5 mb-5">添加一个连接（可指向本机 Ollama）</p>
      <button class="kiwi-btn-primary" @click="startEdit()">
        <KiwiIcon name="plus" :size="16" />
        添加第一个配置
      </button>
    </div>

    <!-- 删除确认 -->
    <KiwiModal :open="!!showDelete" title="删除配置" @close="showDelete = null">
      <div class="space-y-4">
        <p class="text-sm text-slate-600">
          确定删除该模型配置吗？引用它的知识库将回退到其他可用模型。
        </p>
        <div class="flex gap-2 justify-end">
          <button class="kiwi-btn-ghost" @click="showDelete = null">取消</button>
          <button class="kiwi-btn-danger" :loading="removing" @click="doDelete">
            {{ removing ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </KiwiModal>
  </div>
</template>