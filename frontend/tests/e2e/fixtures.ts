import {
  test as base,
  expect,
  type APIRequestContext,
  type Locator,
  type Page,
} from '@playwright/test'

export const BACKEND_URL = process.env.PW_BACKEND_URL || 'http://127.0.0.1:8000'

export type KbFixture = { id: string; name: string }

export interface NoteSummary {
  id: string
  title: string
  kind: string
  folder_id: string | null
  parent_note_id: string | null
  sort_order: number
  props_json: Record<string, any>
}

export interface NoteOut extends NoteSummary {
  kb_id: string
  body_md: string
  status: string
  view_mode: string
  is_locked?: boolean
  unlocked?: boolean
  encrypted?: boolean
}

/** 直接走后端 API 准备测试数据，避免用 UI 铺数据导致用例互相依赖。 */
export class NotesApi {
  constructor(
    private readonly request: APIRequestContext,
    readonly kbId: string,
  ) {}

  private url(path: string) {
    return `/api/notes${path}${path.includes('?') ? '&' : '?'}kb_id=${this.kbId}`
  }

  async createNote(input: {
    title: string
    body_md?: string
    kind?: string
    folder_id?: string | null
    parent_note_id?: string | null
  }): Promise<NoteOut> {
    const res = await this.request.post(this.url(''), {
      data: { kind: 'doc', body_md: '', ...input },
    })
    expect(res.status(), await res.text()).toBe(201)
    return (await res.json()) as NoteOut
  }

  async createTag(name: string) {
    const res = await this.request.post(this.url('/tags'), { data: { name } })
    expect(res.status(), await res.text()).toBe(201)
    return (await res.json()) as { id: string; name: string }
  }

  async createFolder(name: string, parentId: string | null = null) {
    const res = await this.request.post(this.url('/folders'), {
      data: { name, parent_id: parentId },
    })
    expect(res.status(), await res.text()).toBe(201)
    return (await res.json()) as { id: string; name: string }
  }

  async getNote(id: string): Promise<NoteOut> {
    const res = await this.request.get(this.url(`/${id}`))
    expect(res.status(), await res.text()).toBe(200)
    return (await res.json()) as NoteOut
  }

  async getTree(): Promise<{ folders: any[]; notes: NoteSummary[] }> {
    const res = await this.request.get(this.url('/tree'))
    expect(res.status(), await res.text()).toBe(200)
    return (await res.json()) as { folders: any[]; notes: NoteSummary[] }
  }
}

type Fixtures = {
  api: APIRequestContext
  kb: KbFixture
  notesApi: NotesApi
}

export const test = base.extend<Fixtures>({
  api: async ({ playwright }, use) => {
    const context = await playwright.request.newContext({ baseURL: BACKEND_URL })
    await use(context)
    await context.dispose()
  },
  kb: async ({ api }, use, testInfo) => {
    const res = await api.post('/api/kbs', {
      data: {
        name: `E2E ${testInfo.title} ${Date.now()}`,
        learning_enabled: false,
        wiki_compile_interval_hours: 0,
        todo_sync_interval_hours: 0,
      },
    })
    expect(res.status(), await res.text()).toBe(201)
    const body = await res.json()
    await use({ id: body.id, name: body.name })
    // 知识库删除是硬删除并级联清理笔记、任务与附件。
    await api.delete(`/api/kbs/${body.id}`)
  },
  notesApi: async ({ api, kb }, use) => {
    await use(new NotesApi(api, kb.id))
  },
})

/** 在当前测试的浏览器上下文写入选中知识库，再打开工作区。 */
export async function openWorkspace(page: Page, kbId: string, path = '/notes') {
  await page.addInitScript((id) => {
    localStorage.setItem('kiwi.kb.edit', id as string)
    localStorage.setItem('kiwi.kb.learn', id as string)
  }, kbId)
  await page.goto(path)
}

/** 按行内相对高度把一条目录行拖到另一条上（0.5 = 正中，进入分组/成为子笔记）。 */
export async function dragRow(
  page: Page,
  source: Locator,
  target: Locator,
  ratio = 0.5,
) {
  await expect(source).toBeVisible()
  await expect(target).toBeVisible()
  const from = await source.boundingBox()
  const to = await target.boundingBox()
  if (!from || !to) throw new Error('拖拽源或目标不可见')

  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  // 组件以 4px 位移作为拖拽阈值，先小幅移动进入拖拽态。
  await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2 + 6, {
    steps: 3,
  })
  await page.mouse.move(to.x + to.width / 2, to.y + to.height * ratio, { steps: 12 })
  await page.mouse.up()
}

/** 拖到目录底部的「松开移到根目录」投放区。 */
export async function dragToRoot(page: Page, source: Locator) {
  await expect(source).toBeVisible()
  const from = await source.boundingBox()
  if (!from) throw new Error('拖拽源不可见')

  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
  await page.mouse.down()
  await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2 + 6, {
    steps: 3,
  })
  const drop = page.locator('[data-tree-root-drop]')
  await expect(drop).toBeVisible()
  const to = await drop.boundingBox()
  if (!to) throw new Error('根目录投放区不可见')
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 })
  await page.mouse.up()
}

export { expect }
