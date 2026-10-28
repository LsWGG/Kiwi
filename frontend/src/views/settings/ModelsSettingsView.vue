<script setup lang="ts">
/**
 * 模型配置：把大模型、向量模型与 OCR 收敛到同一个设置页，
 * 通过子页签切换，避免设置一级导航被同类配置撑长。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import KiwiIcon from '@/components/ui/KiwiIcon.vue'
import SettingsTabs from '@/components/settings/SettingsTabs.vue'
import { IS_DESKTOP } from '@/desktop/env'
import LlmConfigView from './LlmConfigView.vue'
import EmbeddingConfigView from './EmbeddingConfigView.vue'
import OcrConfigView from './OcrConfigView.vue'
import TranscribeConfigView from './TranscribeConfigView.vue'

type ModelTab = 'llm' | 'embedding' | 'ocr' | 'transcribe'

const TABS: {
  key: ModelTab
  label: string
  icon: string
  hint: string
  description: string
}[] = [
  {
    key: 'llm',
    label: '大模型',
    icon: 'sparkle',
    hint: '对话 / 摘要 / 行内 AI',
    description: '兼容 OpenAI 的对话端点，密钥加密存储。',
  },
  {
    key: 'embedding',
    label: '向量模型',
    icon: 'layers',
    hint: '检索与知识库索引',
    description: '本地 fastembed 或线上 embedding 接口。',
  },
  {
    key: 'ocr',
    label: 'OCR',
    icon: 'scanText',
    hint: '扫描件图片识别',
    description: '为 PDF / 图片配置视觉识别接口。',
  },
  {
    key: 'transcribe',
    label: '语音转写',
    icon: 'mic',
    hint: '录音 / 会议转写',
    description: '本地 faster-whisper 或飞书妙记，扫码即可授权。',
  },
]

const route = useRoute()
const router = useRouter()

const active = computed<ModelTab>(() => {
  const tab = String(route.query.tab || 'llm')
  return (TABS.some((item) => item.key === tab) ? tab : 'llm') as ModelTab
})

function select(key: ModelTab) {
  if (key === active.value) return
  void router.replace({
    path: '/settings/models',
    query: key === 'llm' ? {} : { tab: key },
  })
}
</script>

<template>
  <div class="page-wrap-slim px-8 py-8">
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up">
      <div class="flex items-center gap-3">
        <span
          class="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-kiwi-400 to-kiwi-600 text-white shadow-glow"
        >
          <KiwiIcon name="layers" :size="20" />
        </span>
        <div>
          <h1 class="text-2xl font-semibold text-slate-800">模型配置</h1>
          <p class="mt-1 text-sm text-slate-500">
            统一管理对话、向量与 OCR 等在线模型接入；所有密钥加密存储。
          </p>
        </div>
      </div>
    </div>

    <SettingsTabs />

    <!-- 桌面版模型策略 -->
    <div
      v-if="IS_DESKTOP"
      class="mb-4 rounded-xl border border-kiwi-200/70 bg-kiwi-50/50 px-4 py-3 text-[11.5px] leading-relaxed text-slate-600"
    >
      <p class="font-medium text-slate-700">桌面版未内置任何模型</p>
      <p class="mt-1">
        大模型与向量模型可连接本机 Ollama / LM Studio 或线上 OpenAI 兼容接口；
        在线 OCR、语音转写与飞书妙记在桌面版已禁用。连接非本机地址前会要求确认数据外发风险。
      </p>
    </div>

    <!-- 子页签：说明每类模型在系统中的用途，切换时保持 URL 可分享 -->
    <div class="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        type="button"
        class="group flex items-start gap-3 rounded-2xl border p-3 text-left transition-all"
        :class="
          active === tab.key
            ? 'border-kiwi-200 bg-white shadow-soft ring-1 ring-kiwi-100'
            : 'border-slate-200/70 bg-white/50 hover:border-kiwi-200 hover:bg-white/80'
        "
        :aria-pressed="active === tab.key"
        @click="select(tab.key)"
      >
        <span
          class="grid h-9 w-9 shrink-0 place-items-center rounded-xl transition-colors"
          :class="
            active === tab.key
              ? 'bg-kiwi-50 text-kiwi-600'
              : 'bg-slate-100 text-slate-400 group-hover:text-slate-500'
          "
        >
          <KiwiIcon :name="tab.icon" :size="16" />
        </span>
        <span class="min-w-0 flex-1">
          <span class="flex items-center gap-1.5">
            <span
              class="text-[12.5px] font-semibold"
              :class="active === tab.key ? 'text-kiwi-700' : 'text-slate-700'"
            >{{ tab.label }}</span>
            <KiwiIcon
              v-if="active === tab.key"
              name="check"
              :size="11"
              class="text-kiwi-500"
            />
          </span>
          <span class="mt-0.5 block text-[10.5px] text-slate-400">{{ tab.hint }}</span>
          <span class="mt-1 block text-[10.5px] leading-relaxed text-slate-400">
            {{ tab.description }}
          </span>
        </span>
      </button>
    </div>

    <div class="min-w-0">
      <LlmConfigView v-if="active === 'llm'" embedded />
      <EmbeddingConfigView v-else-if="active === 'embedding'" embedded />
      <OcrConfigView v-else-if="active === 'ocr'" embedded />
      <TranscribeConfigView v-else embedded />
    </div>
  </div>
</template>
