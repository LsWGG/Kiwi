import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 公开只读分享：不进入工作区布局，也不需要访问令牌。
    {
      path: '/share/:token',
      name: 'note-share',
      component: () => import('@/views/NoteShareView.vue'),
    },
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
        // 品牌作为设置首页；大模型 / 向量 / OCR 合并到「模型配置」的同一页
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/settings/SystemSettingsView.vue'),
        },
        {
          path: 'settings/models',
          name: 'settings-models',
          component: () => import('@/views/settings/ModelsSettingsView.vue'),
        },
        {
          path: 'settings/brand',
          redirect: '/settings',
        },
        {
          path: 'settings/embedding',
          redirect: { path: '/settings/models', query: { tab: 'embedding' } },
        },
        {
          path: 'settings/ocr',
          redirect: { path: '/settings/models', query: { tab: 'ocr' } },
        },
        {
          path: 'settings/operations',
          name: 'settings-operations',
          component: () => import('@/views/settings/OperationsSettingsView.vue'),
        },
        {
          path: 'settings/plugins',
          name: 'settings-plugins',
          component: () => import('@/views/settings/PluginSettingsView.vue'),
        },
        // 旧地址保留跳转
        { path: 'settings/system', redirect: '/settings' },
        // 学习模式（阶段一核心闭环：画像→训练→掌握度→错题）
        { path: 'learn', name: 'learn', component: () => import('@/views/learn/StudyView.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router