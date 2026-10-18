<script setup lang="ts">
import { computed } from 'vue'
import { iconSVG } from './icons'

const props = withDefaults(
  defineProps<{
    name: string
    size?: number | string
    spin?: boolean
  }>(),
  { size: 18, spin: false },
)

const inner = computed(() => iconSVG(props.name))

const sizePx = computed(() =>
  typeof props.size === 'number' ? `${props.size}px` : props.size,
)
</script>

<template>
  <svg
    viewBox="0 0 24 24"
    :width="sizePx"
    :height="sizePx"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    :class="spin ? 'animate-spin' : ''"
    v-html="inner"
  />
</template>