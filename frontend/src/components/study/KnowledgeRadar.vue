<script setup lang="ts">
// 知识点雷达图：本次正确率 vs 当前掌握度，最多展示 6 个知识点。
import { computed } from 'vue'

const props = defineProps<{
  points: Array<{ title: string; slug?: string; accuracy: number; mastery: number }>
}>()

const MAX_POINTS = 6
const CX = 160
const CY = 136
const RADIUS = 88

const shown = computed(() =>
  [...props.points].sort((a, b) => a.accuracy - b.accuracy).slice(0, MAX_POINTS),
)

const axisCount = computed(() => shown.value.length)

function pointAt(index: number, ratio: number) {
  const angle = (Math.PI * 2 * index) / axisCount.value - Math.PI / 2
  return {
    x: CX + Math.cos(angle) * RADIUS * ratio,
    y: CY + Math.sin(angle) * RADIUS * ratio,
  }
}

function polygon(ratio: number) {
  return shown.value.map((_, i) => {
    const p = pointAt(i, ratio)
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
  }).join(' ')
}

function seriesPolygon(key: 'accuracy' | 'mastery') {
  return shown.value
    .map((p, i) => {
      const q = pointAt(i, Math.max(0, Math.min(1, Number(p[key]) || 0)))
      return `${q.x.toFixed(1)},${q.y.toFixed(1)}`
    })
    .join(' ')
}

const labels = computed(() =>
  shown.value.map((p, i) => {
    const q = pointAt(i, 1.18)
    const cos = Math.cos((Math.PI * 2 * i) / axisCount.value - Math.PI / 2)
    const anchor = cos > 0.25 ? 'start' : cos < -0.25 ? 'end' : 'middle'
    const title = p.title || p.slug || `知识点 ${i + 1}`
    return {
      x: q.x,
      y: q.y,
      anchor,
      text: title.length > 9 ? `${title.slice(0, 8)}…` : title,
    }
  }),
)
</script>

<template>
  <div>
    <div class="flex items-center gap-4 mb-1 px-1">
      <span class="inline-flex items-center gap-1.5 text-[10px] text-slate-500">
        <span class="w-2.5 h-2.5 rounded-sm bg-emerald-500/80" />
        本次正确率
      </span>
      <span class="inline-flex items-center gap-1.5 text-[10px] text-slate-500">
        <span class="w-2.5 h-0.5 bg-violet-500" />
        当前掌握度
      </span>
      <span v-if="points.length > MAX_POINTS" class="ml-auto text-[10px] text-slate-300">
        展示得分最低的 {{ MAX_POINTS }} 项
      </span>
    </div>

    <svg v-if="axisCount >= 3" viewBox="0 0 320 286" class="w-full max-w-[340px] mx-auto" role="img"
      aria-label="知识点正确率与掌握度雷达图">
      <polygon
        v-for="ratio in [0.25, 0.5, 0.75, 1]"
        :key="ratio"
        :points="polygon(ratio)"
        fill="none"
        stroke="#e2e8f0"
        :stroke-width="ratio === 1 ? 1.2 : 0.8"
      />
      <line
        v-for="(_, i) in shown"
        :key="`axis-${i}`"
        :x1="CX"
        :y1="CY"
        :x2="pointAt(i, 1).x"
        :y2="pointAt(i, 1).y"
        stroke="#e2e8f0"
        stroke-width="0.8"
      />

      <polygon
        :points="seriesPolygon('mastery')"
        fill="rgba(124, 58, 237, 0.08)"
        stroke="#7c3aed"
        stroke-width="1.6"
        stroke-dasharray="5 3"
        stroke-linejoin="round"
      />
      <polygon
        :points="seriesPolygon('accuracy')"
        fill="rgba(16, 185, 129, 0.16)"
        stroke="#10b981"
        stroke-width="2"
        stroke-linejoin="round"
      />

      <template v-for="(p, i) in shown" :key="`dot-${i}`">
        <circle
          :cx="pointAt(i, Math.max(0, Math.min(1, p.accuracy))).x"
          :cy="pointAt(i, Math.max(0, Math.min(1, p.accuracy))).y"
          r="3"
          fill="#10b981"
          stroke="#fff"
          stroke-width="1.2"
        />
        <circle
          :cx="pointAt(i, Math.max(0, Math.min(1, p.mastery))).x"
          :cy="pointAt(i, Math.max(0, Math.min(1, p.mastery))).y"
          r="2.4"
          fill="#7c3aed"
          stroke="#fff"
          stroke-width="1"
        />
      </template>

      <text
        v-for="(l, i) in labels"
        :key="`label-${i}`"
        :x="l.x"
        :y="l.y"
        :text-anchor="l.anchor"
        dominant-baseline="middle"
        font-size="9.5"
        fill="#64748b"
      >
        {{ l.text }}
      </text>
    </svg>

    <p v-else class="text-xs text-slate-400 py-6 text-center">
      知识点少于 3 个，暂不绘制雷达图；可查看下方逐项得分。
    </p>
  </div>
</template>
