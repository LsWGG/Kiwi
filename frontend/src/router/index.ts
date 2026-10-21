import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      // 根路由只渲染子视图；App.vue 已在 main.ts 全局挂载（提供顶栏/侧栏），
      // 不能把 App 当路由组件，否则与全局挂载叠加渲染成两层。
      component: () => import('@/components/layout/RouterHost.vue'),
      children: [
        // 编辑模式
        { path: '', redirect: '/kbs' },
        { path: 'kbs', name: 'kb-manager', component: () => import('@/views/edit/KbManagerView.vue') },
        {
          path: 'notes/:id?',
          name: 'notes',
          component: () => import('@/views/edit/NotesWorkspaceView.vue'),
        },
        { path: 'wiki', name: 'wiki', component: () => import('@/views/edit/WikiOverview.vue') },
        {
          path: 'wiki/:id',
          name: 'wiki-page',
          component: () => import('@/views/edit/WikiPageView.vue'),
        },
        {
          path: 'sources',
          name: 'sources',
          component: () => import('@/views/edit/SourcesView.vue'),
        },
        {
          path: 'sources/:id',
          name: 'source-preview',
          component: () => import('@/views/edit/SourcePreviewView.vue'),
        },
        // 独立导入页已并入笔记工作区；保留旧链接跳转
        { path: 'import', redirect: '/notes' },
        { path: 'chat', name: 'chat', component: () => import('@/views/edit/ChatView.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/settings/LlmConfigView.vue') },
        {
          path: 'settings/embedding',
          name: 'settings-embedding',
          component: () => import('@/views/settings/EmbeddingConfigView.vue'),
        },
        {
          path: 'settings/brand',
          name: 'settings-brand',
          component: () => import('@/views/settings/SystemSettingsView.vue'),
          props: { section: 'brand' },
        },
        {
          path: 'settings/ocr',
          name: 'settings-ocr',
          component: () => import('@/views/settings/SystemSettingsView.vue'),
          props: { section: 'ocr' },
        },
        {
          path: 'settings/operations',
          name: 'settings-operations',
          component: () => import('@/views/settings/OperationsSettingsView.vue'),
        },
        // 旧地址保留跳转
        { path: 'settings/system', redirect: '/settings/brand' },
        // 学习模式（阶段一核心闭环：画像→训练→掌握度→错题）
        { path: 'learn', name: 'learn', component: () => import('@/views/learn/StudyView.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router