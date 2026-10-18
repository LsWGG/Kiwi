<script setup lang="ts">
// 路由根壳：App.vue 已在全局挂载提供顶栏/侧栏，
// 这里只渲染子路由，避免 App 被嵌套渲染两遍。
import { RouterView } from 'vue-router'
</script>

<template>
  <RouterView />
</template>