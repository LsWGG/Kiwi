import { test, expect } from './fixtures'
import { randomUUID } from 'node:crypto'

/**
 * 问答 Agent 关键交互回归（M6）。
 *
 * 不依赖真实模型：拦截 SSE，固定返回「读取网页 → 待确认新建笔记 → 确认后完成」。
 * 重点保护：确认卡在 approval 事件到达后无需点击页面就能出现；确认后能继续
 * 收到完成回答与笔记链接。
 */

const ACTION_ID = 'e2e-action-1'
const NOTE_ID = '11111111-1111-4111-8111-111111111111'

function sse(frames: Array<[string, unknown]>) {
  return frames
    .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join('')
}

const approvalFrames: Array<[string, unknown]> = [
  ['trace', { trace_id: 'e2e-trace-1' }],
  [
    'plan',
    {
      steps: [
        { id: 'p1', title: '读取网页', status: 'done' },
        { id: 'p2', title: '新建笔记', status: 'active' },
      ],
    },
  ],
  ['stage', { stage: 'tool-1', status: 'done', message: '读取网页完成' }],
  [
    'approval',
    {
      action_id: ACTION_ID,
      tool: 'create_note',
      label: '新建笔记',
      summary: '新建笔记《关雎》',
      args: {
        title: '关雎',
        body_md: '# 关雎\n\n关关雎鸠，在河之洲。',
      },
      arg_labels: { title: '标题', body_md: '正文' },
      expires_at: Math.floor(Date.now() / 1000) + 600,
    },
  ],
  [
    'done',
    {
      ok: true,
      awaiting_approval: true,
      action_id: ACTION_ID,
      plan: [
        { id: 'p1', title: '读取网页', status: 'done' },
        { id: 'p2', title: '新建笔记', status: 'active' },
      ],
    },
  ],
]

const doneFrames: Array<[string, unknown]> = [
  ['trace', { trace_id: 'e2e-trace-2' }],
  ['stage', { stage: 'execute', status: 'done', message: '新建笔记完成' }],
  [
    'chunk',
    {
      text: `已创建 [关雎](kiwi://note/${NOTE_ID})，并放到知识库根目录。`,
    },
  ],
  ['done', { ok: true, plan: [{ id: 'p1', title: '新建笔记', status: 'done' }] }],
]

test.describe('问答 Agent 确认流', () => {
  test('刷新后保留处理步骤、行动计划与流转入口', async ({ page, api, kb }) => {
    const created = await api.post('/api/chat/sessions', {
      data: {
        scope: { scope: 'kb', kb_ids: [kb.id], note_ids: [], folder_ids: [] },
        intent: 'auto',
        messages: [
          { role: 'user', content: '你好' },
          {
            role: 'assistant',
            content: '你好！有什么我可以帮你的吗？',
            steps: [
              {
                id: 'agent',
                message: '已完成思考',
                detail: '',
                status: 'done',
              },
              {
                id: 'tool-1',
                message: '读取网页完成',
                detail: '网页正文',
                status: 'done',
              },
            ],
            plan: [
              { id: 'p1', title: '读取网页', status: 'done' },
              { id: 'p2', title: '整理回答', status: 'done' },
            ],
            trace_id: 'seed-trace-1',
            started_at: Date.now() - 26_000,
            finished_at: Date.now(),
          },
        ],
      },
    })
    expect(created.status(), await created.text()).toBe(201)
    const sessionId = (await created.json()).id

    try {
      await page.addInitScript((id) => {
        localStorage.setItem('kiwi.kb.edit', id as string)
      }, kb.id)
      await page.goto('/chat', { waitUntil: 'networkidle' })
      await expect(page.getByText(/已完成 2 个步骤/)).toBeVisible()
      await expect(
        page.getByText('行动计划', { exact: true }),
      ).toBeVisible()
      await expect(
        page.getByRole('button', { name: 'Agent 流转' }),
      ).toBeVisible()
    } finally {
      await api.delete(`/api/chat/sessions/${sessionId}`)
    }
  })

  test('approval 到达后确认卡自动出现，确认后返回笔记链接', async ({ page, kb }) => {
    const sessionId = randomUUID()
    const detail = {
      id: sessionId,
      title: '新的问答',
      scope: { scope: 'kb', kb_ids: [kb.id], note_ids: [], folder_ids: [] },
      intent: 'auto',
      llm_config_id: null,
      message_count: 1,
      messages: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    await page.route('**/api/chat/sessions?*', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ json: { items: [] } })
        return
      }
      await route.fulfill({ json: detail })
    })
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({ status: 201, json: detail })
        return
      }
      await route.continue()
    })
    await page.route(`**/api/chat/sessions/${sessionId}`, async (route) => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({ json: detail })
        return
      }
      await route.continue()
    })

    const tracePayload = {
      id: 'e2e-trace-2',
      started_at: Date.now() / 1000 - 8,
      finished_at: Date.now() / 1000,
      duration_ms: 8000,
      status: 'done',
      query: '把网页内容新建为笔记',
      query_chars: 12,
      model: 'e2e-model',
      scope: 'kb',
      planner_source: 'rules',
      planner_ms: 120,
      planner_queries: 1,
      events: [
        {
          at: 0.12,
          kind: 'planner',
          name: '检索规划',
          ms: 120,
          ok: true,
          detail: 'rules',
          input: { query: '把网页内容新建为笔记' },
          output: { queries: ['网页内容'], source: 'rules' },
          meta: { source: 'rules' },
        },
        {
          at: 1.2,
          kind: 'model',
          name: 'e2e-model',
          ms: 900,
          ok: true,
          detail: 'chars=30',
          input: {
            model: 'e2e-model',
            messages: [
              { role: 'system', content: '系统提示' },
              { role: 'user', content: '把网页内容新建为笔记' },
            ],
          },
          output: '{"action":{"tool":"create_note"},"answer":null}',
          meta: {
            usage: {
              prompt_tokens: 10,
              completion_tokens: 5,
              total_tokens: 15,
            },
            finish_reason: 'stop',
            attempts: 1,
          },
        },
      ],
    }
    await page.route('**/api/maintenance/agent-traces**', async (route) => {
      const pathname = new URL(route.request().url()).pathname
      // 单条轨迹接口与会话页弹窗；列表接口仍返回 items 包装。
      if (/\/agent-traces\/[^/]+$/.test(pathname)) {
        await route.fulfill({ json: tracePayload })
        return
      }
      await route.fulfill({ json: { items: [tracePayload] } })
    })

    let streamCalls = 0
    await page.route('**/api/chat/stream', async (route) => {
      streamCalls += 1
      await new Promise((resolve) => setTimeout(resolve, 600))
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: { 'Cache-Control': 'no-cache' },
        body: streamCalls === 1 ? sse(approvalFrames) : sse(doneFrames),
      })
    })

    await page.addInitScript((id) => {
      localStorage.setItem('kiwi.kb.edit', id as string)
    }, kb.id)
    await page.goto('/chat', { waitUntil: 'networkidle' })
    await page.waitForTimeout(600)

    const input = page.locator('[aria-label="输入问题"]')
    await input.fill('把网页 https://example.com/poem 内容新建为笔记，放到知识库根目录')
    await input.press('Enter')

    // 关键回归：不点击页面，approval 到达后卡片应立即进入 DOM 并可见。
    const card = page.locator(`[data-approval-action="${ACTION_ID}"]`)
    await expect(card).toBeVisible({ timeout: 10_000 })
    await expect(card).toBeInViewport({ ratio: 0.2 })
    await expect(card).toContainText('需要你确认')

    await page.getByRole('button', { name: '允许执行', exact: true }).click()
    await expect(page.getByText('已创建', { exact: false })).toBeVisible({
      timeout: 10_000,
    })
    const link = page.locator(`a[data-id="${NOTE_ID}"]`).first()
    await expect(link).toBeVisible()
    await expect(streamCalls).toBe(2)

    // 每条回复都可以在原地查看本轮 Agent 流转；关闭弹窗后仍停留在问答页。
    const traceButton = page.getByRole('button', { name: 'Agent 流转' }).first()
    await expect(traceButton).toBeVisible()
    await traceButton.click()
    const traceDialog = page.getByRole('dialog', { name: 'Agent 流转详情' })
    await expect(traceDialog).toBeVisible()
    await expect(traceDialog).toContainText('e2e-model')
    await expect(page).toHaveURL(/\/chat/)

    await traceDialog.getByRole('button', { name: '关闭', exact: true }).click()
    await expect(traceDialog).toBeHidden()
    await expect(page).toHaveURL(/\/chat/)
    await expect(page.locator('[aria-label="输入问题"]')).toBeVisible()
  })
})
