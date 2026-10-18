<script setup lang="ts">
/**
 * Kiwi 品牌标记。
 * 编辑模式：知识网络（四个节点 + 交叉引用），对应「知识编译」。
 * 学习模式：掌握度雷达（五轴数据多边形），对应「学习训练」。
 */
withDefaults(
  defineProps<{
    mode?: 'edit' | 'learn'
    size?: number
  }>(),
  { mode: 'edit', size: 32 },
)
</script>

<template>
  <svg
    v-if="mode === 'learn'"
    :width="size"
    :height="size"
    viewBox="0 0 32 32"
    fill="none"
    aria-hidden="true"
    focusable="false"
    class="kiwi-logo kiwi-logo-learn"
  >
    <rect x="1" y="1" width="30" height="30" rx="9" fill="#07130e" stroke="rgba(52,211,153,.3)" />
    <!-- 外圈五轴 -->
    <path
      d="M16 5.4 26.65 13.14 22.58 25.66 9.42 25.66 5.35 13.14Z"
      stroke="rgba(94,234,212,.26)"
      stroke-width="0.9"
      stroke-linejoin="round"
    />
    <!-- 掌握度多边形：各轴进度不同，顶部为已掌握 -->
    <path
      d="M16 7.1 20.97 14.99 20.36 22.59 13.21 20.44 9.86 14.6Z"
      fill="rgba(52,211,153,.18)"
      stroke="rgba(94,234,212,.62)"
      stroke-width="1"
      stroke-linejoin="round"
    />
    <circle cx="16" cy="7.1" r="2.3" fill="#fbbf24" />
    <circle cx="16" cy="7.1" r="4" stroke="rgba(251,191,36,.34)" stroke-width="0.8" />
    <circle cx="20.97" cy="14.99" r="1.45" fill="#5cf2b6" />
    <circle cx="20.36" cy="22.59" r="1.45" fill="#2dd4bf" />
    <circle cx="13.21" cy="20.44" r="1.45" fill="#34d399" />
    <circle cx="9.86" cy="14.6" r="1.45" fill="#5eead4" />
  </svg>

  <svg
    v-else
    :width="size"
    :height="size"
    viewBox="0 0 32 32"
    fill="none"
    aria-hidden="true"
    focusable="false"
    class="kiwi-logo kiwi-logo-edit"
  >
    <rect x="1" y="1" width="30" height="30" rx="9" fill="#0b0e17" stroke="rgba(255,255,255,.16)" />
    <!-- 交叉引用 -->
    <path
      d="M10 9.5v13M22 9.5v13M10 9.5l12 13M22 9.5l-12 13"
      stroke="rgba(255,255,255,.2)"
      stroke-width="0.9"
    />
    <!-- 四类知识节点 -->
    <circle cx="10" cy="9.5" r="2.6" fill="#baf56d" />
    <circle cx="22" cy="9.5" r="2.6" fill="#8b95ff" />
    <circle cx="10" cy="22.5" r="2.6" fill="#5cf2b6" />
    <circle cx="22" cy="22.5" r="2.6" fill="#c88cff" />
  </svg>
</template>
