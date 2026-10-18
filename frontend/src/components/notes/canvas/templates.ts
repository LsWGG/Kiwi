/**
 * 内置画布模板。
 *
 * 布局约定：同一层节点保持 32px 以上间距，列之间保持 70px 以上间距，
 * 避免节点互相遮挡；连线尽量使用对侧锚点，由舞台的自适应端口分配均摊。
 */
import {
  emptyDoc,
  makeEdge,
  makeNode,
  type CanvasDoc,
  type CanvasEdge,
  type CanvasNode,
  type CanvasThemeId,
} from './types'

export interface CanvasTemplate {
  id: string
  name: string
  desc: string
  icon: string
  theme?: CanvasThemeId
  build: () => { nodes: CanvasNode[]; edges: CanvasEdge[] }
}

function link(
  from: CanvasNode,
  to: CanvasNode,
  opts: {
    fromSide?: CanvasEdge['from']['side']
    toSide?: CanvasEdge['to']['side']
    curve?: CanvasEdge['curve']
    arrow?: CanvasEdge['arrow']
    dashed?: boolean
    label?: string
    tone?: CanvasEdge['tone']
  } = {},
): CanvasEdge {
  return makeEdge(
    { nodeId: from.id, side: opts.fromSide ?? 'auto' },
    { nodeId: to.id, side: opts.toSide ?? 'auto' },
    {
      curve: opts.curve ?? 'orthogonal',
      arrow: opts.arrow ?? 'end',
      dashed: opts.dashed,
      label: opts.label,
      tone: opts.tone,
    },
  )
}

function mindEdge(from: CanvasNode, to: CanvasNode): CanvasEdge {
  return makeEdge(
    { nodeId: from.id, side: 'right' },
    { nodeId: to.id, side: 'left' },
    { curve: 'bezier', arrow: 'none' },
  )
}

function flowchart() {
  const start = makeNode('round', 320, 20, '开始', { tone: 'green', bold: true })
  const collect = makeNode('rect', 320, 130, '收集需求', { tone: 'neutral' })
  const review = makeNode('diamond', 314, 260, '评审通过？', { tone: 'amber' })
  const develop = makeNode('rect', 650, 280, '进入开发', { tone: 'accent' })
  const revise = makeNode('rect', 30, 280, '修改方案', { tone: 'rose' })
  const release = makeNode('rect', 650, 430, '上线发布', { tone: 'accent' })
  const end = makeNode('round', 650, 560, '结束', { tone: 'green', bold: true })
  const nodes = [start, collect, review, develop, revise, release, end]
  const edges = [
    link(start, collect, { fromSide: 'bottom', toSide: 'top' }),
    link(collect, review, { fromSide: 'bottom', toSide: 'top' }),
    link(review, develop, { fromSide: 'right', toSide: 'left', label: '是', tone: 'green' }),
    link(review, revise, { fromSide: 'left', toSide: 'right', label: '否', tone: 'rose' }),
    link(revise, collect, {
      fromSide: 'top',
      toSide: 'left',
      curve: 'bezier',
      dashed: true,
      label: '重新提交',
    }),
    link(develop, release, { fromSide: 'bottom', toSide: 'top' }),
    link(release, end, { fromSide: 'bottom', toSide: 'top' }),
  ]
  return { nodes, edges }
}

function mindmap() {
  const center = makeNode('round', 40, 330, '产品知识体系', {
    tone: 'accent',
    bold: true,
    fontSize: 18,
    w: 240,
    h: 88,
  })
  const research = makeNode('round', 390, 40, '用户研究', { tone: 'green' })
  const design = makeNode('round', 390, 220, '产品设计', { tone: 'violet' })
  const tech = makeNode('round', 390, 400, '技术实现', { tone: 'amber' })
  const ops = makeNode('round', 390, 580, '上线运营', { tone: 'rose' })
  const leaf = (x: number, y: number, text: string, tone: CanvasNode['tone']) =>
    makeNode('rect', x, y, text, { tone, w: 184, h: 72 })

  const interview = leaf(700, 8, '访谈与问卷', 'green')
  const persona = leaf(700, 104, '用户画像', 'green')
  const prototype = leaf(700, 192, '交互原型', 'violet')
  const visual = leaf(700, 288, '视觉规范', 'violet')
  const architecture = leaf(700, 376, '架构设计', 'amber')
  const quality = leaf(700, 472, '质量保障', 'amber')
  const analytics = leaf(700, 560, '数据复盘', 'rose')
  const growth = leaf(700, 656, '增长实验', 'rose')
  const nodes = [
    center,
    research,
    design,
    tech,
    ops,
    interview,
    persona,
    prototype,
    visual,
    architecture,
    quality,
    analytics,
    growth,
  ]
  const edges = [
    mindEdge(center, research),
    mindEdge(center, design),
    mindEdge(center, tech),
    mindEdge(center, ops),
    mindEdge(research, interview),
    mindEdge(research, persona),
    mindEdge(design, prototype),
    mindEdge(design, visual),
    mindEdge(tech, architecture),
    mindEdge(tech, quality),
    mindEdge(ops, analytics),
    mindEdge(ops, growth),
  ]
  return { nodes, edges }
}

function architecture() {
  const client = makeNode('network', 20, 270, '客户端\nWeb · 移动端', {
    variant: 'client',
    tone: 'accent',
  })
  const gateway = makeNode('network', 250, 270, 'API 网关\nKong', {
    variant: 'router',
    tone: 'violet',
  })
  const user = makeNode('rect', 490, 110, '用户服务\n认证 · 权限', { tone: 'neutral' })
  const knowledge = makeNode('rect', 490, 280, '知识服务\n笔记 · Wiki', { tone: 'neutral' })
  const search = makeNode('rect', 490, 450, '检索服务\n召回 · 重排', { tone: 'neutral' })
  const postgres = makeNode('network', 760, 90, 'PostgreSQL\n主数据库', {
    variant: 'database',
    tone: 'green',
  })
  const storage = makeNode('network', 760, 260, '对象存储\nMinIO', {
    variant: 'storage',
    tone: 'amber',
  })
  const vector = makeNode('network', 760, 430, '向量索引\nQdrant', {
    variant: 'database',
    tone: 'rose',
  })
  const nodes = [client, gateway, user, knowledge, search, postgres, storage, vector]
  const edges = [
    link(client, gateway, { fromSide: 'right', toSide: 'left', label: 'HTTPS' }),
    link(gateway, user, { fromSide: 'right', toSide: 'left' }),
    link(gateway, knowledge, { fromSide: 'right', toSide: 'left' }),
    link(gateway, search, { fromSide: 'right', toSide: 'left' }),
    link(user, postgres, { fromSide: 'right', toSide: 'left' }),
    link(knowledge, postgres, { fromSide: 'right', toSide: 'left' }),
    link(knowledge, storage, { fromSide: 'right', toSide: 'left' }),
    link(search, vector, { fromSide: 'right', toSide: 'left' }),
  ]
  return { nodes, edges }
}

function orgChart() {
  const lead = makeNode('round', 372, 20, '产品负责人', {
    tone: 'accent',
    bold: true,
    w: 200,
    h: 72,
  })
  const product = makeNode('rect', -36, 160, '产品组', { tone: 'violet', w: 200, h: 72 })
  const rnd = makeNode('rect', 372, 160, '研发组', { tone: 'green', w: 200, h: 72 })
  const operation = makeNode('rect', 780, 160, '运营组', { tone: 'amber', w: 200, h: 72 })
  const child = (x: number, text: string) =>
    makeNode('rect', x, 300, text, { tone: 'neutral', w: 176, h: 60, fontSize: 14 })
  const research = child(-126, '用户研究')
  const experience = child(78, '体验设计')
  const frontend = child(282, '前端开发')
  const backend = child(486, '后端开发')
  const content = child(690, '内容运营')
  const growth = child(894, '增长运营')
  const nodes = [
    lead,
    product,
    rnd,
    operation,
    research,
    experience,
    frontend,
    backend,
    content,
    growth,
  ]
  const edges = [
    link(lead, product, { fromSide: 'bottom', toSide: 'top' }),
    link(lead, rnd, { fromSide: 'bottom', toSide: 'top' }),
    link(lead, operation, { fromSide: 'bottom', toSide: 'top' }),
    link(product, research, { fromSide: 'bottom', toSide: 'top' }),
    link(product, experience, { fromSide: 'bottom', toSide: 'top' }),
    link(rnd, frontend, { fromSide: 'bottom', toSide: 'top' }),
    link(rnd, backend, { fromSide: 'bottom', toSide: 'top' }),
    link(operation, content, { fromSide: 'bottom', toSide: 'top' }),
    link(operation, growth, { fromSide: 'bottom', toSide: 'top' }),
  ]
  return { nodes, edges }
}

function umlClass() {
  const user = makeNode(
    'uml',
    20,
    30,
    'User\n- PK id: UUID\n- name: string\n- email: string\n+ login(): void',
    { tone: 'accent', w: 250, h: 160 },
  )
  const order = makeNode(
    'uml',
    350,
    30,
    'Order\n- PK id: UUID\n- FK userId: UUID\n- status: OrderStatus\n- total: money\n+ pay(): Payment',
    { tone: 'green', w: 270, h: 184 },
  )
  const product = makeNode(
    'uml',
    700,
    30,
    'Product\n- PK id: UUID\n- name: string\n- price: money\n- stock: int\n+ isAvailable(): boolean',
    { tone: 'amber', w: 250, h: 176 },
  )
  const item = makeNode(
    'uml',
    350,
    320,
    'OrderItem\n- PK id: UUID\n- FK orderId: UUID\n- FK productId: UUID\n- quantity: int\n- unitPrice: money\n+ subtotal(): money',
    { tone: 'violet', w: 270, h: 196 },
  )
  const nodes = [user, order, product, item]
  const edges = [
    link(user, order, {
      fromSide: 'right',
      toSide: 'left',
      label: '1 → 0..*',
    }),
    link(order, item, {
      fromSide: 'bottom',
      toSide: 'top',
      label: '1 → 1..*',
    }),
    link(product, item, {
      fromSide: 'left',
      toSide: 'right',
      curve: 'bezier',
      dashed: true,
      label: '1 → 0..*',
    }),
  ]
  return { nodes, edges }
}

function erDiagram() {
  const users = makeNode(
    'table',
    20,
    30,
    'users\nPK id BIGINT\nname VARCHAR(80)\nemail VARCHAR(160)\ncreated_at TIMESTAMPTZ',
    { tone: 'accent', w: 260, h: 170 },
  )
  const orders = makeNode(
    'table',
    360,
    30,
    'orders\nPK id BIGINT\nFK user_id BIGINT\nstatus VARCHAR(20)\ntotal NUMERIC(12,2)\ncreated_at TIMESTAMPTZ',
    { tone: 'green', w: 280, h: 192 },
  )
  const products = makeNode(
    'table',
    720,
    30,
    'products\nPK id BIGINT\nsku VARCHAR(64)\nname VARCHAR(120)\nprice NUMERIC(12,2)\nstock INT',
    { tone: 'amber', w: 280, h: 192 },
  )
  const items = makeNode(
    'table',
    360,
    330,
    'order_items\nPK id BIGINT\nFK order_id BIGINT\nFK product_id BIGINT\nquantity INT\nunit_price NUMERIC(12,2)',
    { tone: 'violet', w: 280, h: 200 },
  )
  const nodes = [users, orders, products, items]
  const edges = [
    link(users, orders, { fromSide: 'right', toSide: 'left', label: '1 : N' }),
    link(orders, items, { fromSide: 'bottom', toSide: 'top', label: '1 : N' }),
    link(products, items, {
      fromSide: 'left',
      toSide: 'right',
      curve: 'bezier',
      label: '1 : N',
    }),
  ]
  return { nodes, edges }
}

function networkTopology() {
  const client = makeNode('network', 20, 370, '客户端\nBrowser', {
    variant: 'client',
    tone: 'neutral',
  })
  const internet = makeNode('network', 20, 190, '互联网\nInternet', {
    variant: 'cloud',
    tone: 'accent',
  })
  const firewall = makeNode('network', 250, 190, '防火墙\nWAF', {
    variant: 'firewall',
    tone: 'rose',
  })
  const router = makeNode('network', 480, 190, '负载均衡\nNginx', {
    variant: 'router',
    tone: 'violet',
  })
  const app1 = makeNode('network', 720, 70, '应用服务器 01\nJava · 8C16G', {
    variant: 'server',
    tone: 'green',
  })
  const app2 = makeNode('network', 720, 200, '应用服务器 02\nJava · 8C16G', {
    variant: 'server',
    tone: 'green',
  })
  const app3 = makeNode('network', 720, 330, '应用服务器 03\nJava · 8C16G', {
    variant: 'server',
    tone: 'green',
  })
  const database = makeNode('network', 980, 70, '主数据库\nPostgreSQL 16', {
    variant: 'database',
    tone: 'green',
  })
  const storage = makeNode('network', 980, 200, '对象存储\nMinIO', {
    variant: 'storage',
    tone: 'amber',
  })
  const cache = makeNode('network', 980, 330, '缓存集群\nRedis 7', {
    variant: 'database',
    tone: 'rose',
  })
  const nodes = [
    client,
    internet,
    firewall,
    router,
    app1,
    app2,
    app3,
    database,
    storage,
    cache,
  ]
  const edges = [
    link(client, internet, { fromSide: 'top', toSide: 'bottom', label: 'HTTPS' }),
    link(internet, firewall, { fromSide: 'right', toSide: 'left', label: '入口流量' }),
    link(firewall, router, { fromSide: 'right', toSide: 'left' }),
    link(router, app1, { fromSide: 'right', toSide: 'left' }),
    link(router, app2, { fromSide: 'right', toSide: 'left' }),
    link(router, app3, { fromSide: 'right', toSide: 'left' }),
    link(app1, database, { fromSide: 'right', toSide: 'left' }),
    link(app2, storage, { fromSide: 'right', toSide: 'left' }),
    link(app3, cache, { fromSide: 'right', toSide: 'left' }),
  ]
  return { nodes, edges }
}

/** 自由端点连线：时序图中的消息 / 生命线不依附具体节点。 */
function freeLink(
  from: { x: number; y: number },
  to: { x: number; y: number },
  opts: { label?: string; dashed?: boolean; tone?: CanvasEdge['tone'] } = {},
): CanvasEdge {
  const edge = makeEdge(
    { nodeId: null, side: 'right' },
    { nodeId: null, side: 'left' },
    { curve: 'straight', arrow: 'end', ...opts },
  )
  edge.from.x = from.x
  edge.from.y = from.y
  edge.to.x = to.x
  edge.to.y = to.y
  return edge
}

function lifeline(node: CanvasNode, bottom: number): CanvasEdge {
  const edge = makeEdge(
    { nodeId: node.id, side: 'bottom' },
    { nodeId: null, side: 'right' },
    { curve: 'straight', arrow: 'none', dashed: true },
  )
  edge.to.x = node.x + node.w / 2
  edge.to.y = bottom
  return edge
}

function sequence() {
  const title = makeNode('text', 60, 0, '文章请求时序图', {
    w: 360,
    h: 34,
    fontSize: 18,
    bold: true,
    align: 'left',
  })
  const subtitle = makeNode('text', 60, 34, '参与者 · 消息顺序 · 返回结果', {
    w: 360,
    h: 24,
    fontSize: 12,
    align: 'left',
  })
  const client = makeNode('rect', 60, 80, '客户端\nBrowser', {
    tone: 'neutral',
    w: 200,
    h: 76,
  })
  const edge = makeNode('rect', 400, 80, 'CDN 边缘\n缓存 · 回源', {
    tone: 'accent',
    w: 200,
    h: 76,
  })
  const origin = makeNode('rect', 740, 80, '源站服务\nSSR · MDX', {
    tone: 'green',
    w: 200,
    h: 76,
  })
  const analytics = makeNode('rect', 1080, 80, '分析服务\n异步埋点', {
    tone: 'violet',
    w: 200,
    h: 76,
  })
  const edgeActive = makeNode('rect', 492, 196, '', {
    tone: 'accent',
    w: 16,
    h: 348,
  })
  const originActive = makeNode('rect', 832, 276, '', {
    tone: 'green',
    w: 16,
    h: 232,
  })
  const renderNote = makeNode('text', 890, 356, '渲染 MDX\n约 120ms', {
    w: 170,
    h: 52,
    fontSize: 12,
    align: 'left',
  })
  const nodes = [
    title,
    subtitle,
    client,
    edge,
    origin,
    analytics,
    edgeActive,
    originActive,
    renderNote,
  ]
  const edges = [
    lifeline(client, 780),
    lifeline(edge, 780),
    lifeline(origin, 780),
    lifeline(analytics, 780),
    freeLink({ x: 160, y: 210 }, { x: 492, y: 210 }, {
      label: 'GET /articles/:slug',
      tone: 'accent',
    }),
    freeLink({ x: 508, y: 326 }, { x: 832, y: 326 }, {
      label: '缓存未命中 · 回源',
    }),
    freeLink({ x: 832, y: 474 }, { x: 508, y: 474 }, {
      label: '200 · HTML + Cache-Control',
      dashed: true,
      tone: 'green',
    }),
    freeLink({ x: 492, y: 560 }, { x: 160, y: 560 }, {
      label: '200 · 边缘缓存命中',
      dashed: true,
      tone: 'accent',
    }),
    freeLink({ x: 160, y: 684 }, { x: 1180, y: 684 }, {
      label: 'pageview beacon',
      dashed: true,
      tone: 'violet',
    }),
  ]
  return { nodes, edges }
}

function stateMachine() {
  const title = makeNode('text', 40, 20, '审批状态流转', {
    w: 360,
    h: 34,
    fontSize: 18,
    bold: true,
    align: 'left',
  })
  const subtitle = makeNode('text', 40, 54, '状态 · 事件 · 分支', {
    w: 360,
    h: 24,
    fontSize: 12,
    align: 'left',
  })
  const start = makeNode('round', 20, 150, '开始', {
    tone: 'green',
    bold: true,
    w: 120,
    h: 56,
  })
  const draft = makeNode('rect', 200, 140, '草稿', { tone: 'neutral' })
  const pending = makeNode('rect', 460, 140, '待审批', { tone: 'amber' })
  const review = makeNode('diamond', 700, 120, '审批通过？', { tone: 'amber' })
  const approved = makeNode('rect', 960, 50, '已通过', { tone: 'green' })
  // 驳回分支放在审批菱形正下方，避免“已通过 → 已发布”的连线穿过其它状态。
  const rejected = makeNode('rect', 706, 280, '已驳回', { tone: 'rose' })
  const revision = makeNode('rect', 706, 420, '修改中', { tone: 'violet' })
  const published = makeNode('rect', 960, 300, '已发布', { tone: 'accent' })
  const end = makeNode('round', 992, 470, '结束', {
    tone: 'green',
    bold: true,
    w: 120,
    h: 56,
  })
  const nodes = [
    title,
    subtitle,
    start,
    draft,
    pending,
    review,
    approved,
    rejected,
    revision,
    published,
    end,
  ]
  const edges = [
    link(start, draft, { fromSide: 'right', toSide: 'left' }),
    link(draft, pending, { fromSide: 'right', toSide: 'left', label: '提交' }),
    link(pending, review, { fromSide: 'right', toSide: 'left', label: '进入审批' }),
    link(review, approved, {
      fromSide: 'right',
      toSide: 'left',
      label: '通过',
      tone: 'green',
    }),
    link(review, rejected, {
      fromSide: 'bottom',
      toSide: 'top',
      label: '驳回',
      tone: 'rose',
    }),
    link(rejected, revision, {
      fromSide: 'bottom',
      toSide: 'top',
      label: '补充材料',
    }),
    link(revision, draft, {
      fromSide: 'bottom',
      toSide: 'bottom',
      dashed: true,
      label: '重新提交',
    }),
    link(approved, published, {
      fromSide: 'bottom',
      toSide: 'top',
      label: '发布上线',
    }),
    link(published, end, { fromSide: 'bottom', toSide: 'top' }),
  ]
  return { nodes, edges }
}

function layeredArchitecture() {
  const title = makeNode('text', 40, 0, '数据报表平台架构', {
    w: 480,
    h: 36,
    fontSize: 20,
    bold: true,
    align: 'left',
  })
  const zone = (x: number, w: number) =>
    makeNode('rect', x, 84, '', { tone: 'neutral', w, h: 540, container: true })
  const zoneA = zone(40, 420)
  const zoneB = zone(500, 460)
  const zoneC = zone(1000, 400)
  const label = (x: number, text: string) =>
    makeNode('text', x, 96, text, {
      w: 360,
      h: 56,
      fontSize: 12,
      bold: true,
      align: 'left',
    })
  const labelA = label(64, 'COLLECTION\n采集层')
  const labelB = label(524, 'PROCESSING\n处理层')
  const labelC = label(1024, 'DISSEMINATION\n分发层')

  const pos = makeNode('rect', 80, 180, 'POS 导出\n每日生成 CSV', {
    tone: 'neutral',
    w: 340,
    h: 84,
  })
  const store = makeNode('rect', 80, 300, '线上商城导出\n订单 · 平铺文件', {
    tone: 'neutral',
    w: 340,
    h: 84,
  })
  const supplier = makeNode('rect', 80, 430, '供应商报价单\n外部 · XLSX', {
    tone: 'neutral',
    w: 340,
    h: 84,
  })
  const shared = makeNode('rect', 540, 170, '共享盘\n无版本控制 · 部门目录', {
    tone: 'amber',
    w: 380,
    h: 104,
  })
  const spreadsheet = makeNode(
    'rect',
    540,
    340,
    '电子表格手工汇总\n本地工作簿 · 宏 · 人工核对',
    { tone: 'amber', w: 380, h: 104 },
  )
  const rdbms = makeNode('rect', 540, 500, '本地数据库\n库存 · 财务', {
    tone: 'green',
    w: 380,
    h: 80,
  })
  const portal = makeNode('rect', 1040, 170, '报表门户\n手动刷新', {
    tone: 'rose',
    w: 320,
    h: 100,
  })
  const email = makeNode('rect', 1040, 350, '邮件报表包\n每周 PDF', {
    tone: 'neutral',
    w: 320,
    h: 90,
  })
  const managers = makeNode('rect', 1040, 500, '区域经理\n12 个区域', {
    tone: 'neutral',
    w: 320,
    h: 84,
  })
  const legend = makeNode(
    'text',
    40,
    656,
    '图例：—— 数据流      - - 外部 / 人工环节      ▢ 瓶颈环节',
    { w: 760, h: 28, fontSize: 12, align: 'left' },
  )
  const nodes = [
    title,
    zoneA,
    zoneB,
    zoneC,
    labelA,
    labelB,
    labelC,
    pos,
    store,
    supplier,
    shared,
    spreadsheet,
    rdbms,
    portal,
    email,
    managers,
    legend,
  ]
  const edges = [
    link(pos, shared, { fromSide: 'right', toSide: 'left', label: 'CSV' }),
    link(store, shared, { fromSide: 'right', toSide: 'left', label: 'EXPORT' }),
    link(supplier, spreadsheet, {
      fromSide: 'right',
      toSide: 'left',
      dashed: true,
      label: 'XLSX',
    }),
    link(shared, spreadsheet, {
      fromSide: 'bottom',
      toSide: 'top',
      dashed: true,
      label: 'COPY',
    }),
    link(spreadsheet, rdbms, { fromSide: 'bottom', toSide: 'top', label: 'LOAD' }),
    link(spreadsheet, portal, { fromSide: 'right', toSide: 'left', label: 'XLSX' }),
    link(portal, email, { fromSide: 'bottom', toSide: 'top', label: 'PDF' }),
    link(email, managers, {
      fromSide: 'bottom',
      toSide: 'top',
      dashed: true,
      label: 'EMAIL',
    }),
  ]
  return { nodes, edges }
}

export const CANVAS_TEMPLATES: CanvasTemplate[] = [
  {
    id: 'blank',
    name: '空白画布',
    desc: '从零开始，自由绘制',
    icon: 'square',
    build: () => ({ nodes: [], edges: [] }),
  },
  {
    id: 'flowchart',
    name: '流程图',
    desc: '开始 → 判断 → 分支 → 结束',
    icon: 'listTree',
    build: flowchart,
  },
  {
    id: 'mindmap',
    name: '思维导图',
    desc: '中心主题向四周发散',
    icon: 'graph',
    theme: 'paper',
    build: mindmap,
  },
  {
    id: 'sequence',
    name: '时序图',
    desc: '参与者、消息顺序与返回结果',
    icon: 'listOrdered',
    theme: 'engineering',
    build: sequence,
  },
  {
    id: 'state-machine',
    name: '状态流转图',
    desc: '状态、事件与条件分支',
    icon: 'target',
    theme: 'engineering',
    build: stateMachine,
  },
  {
    id: 'architecture',
    name: '系统架构',
    desc: '客户端 / 服务层 / 存储层',
    icon: 'columns',
    theme: 'blueprint',
    build: architecture,
  },
  {
    id: 'layered-architecture',
    name: '分层架构图',
    desc: '采集 / 处理 / 分发与数据流',
    icon: 'layers',
    theme: 'engineering',
    build: layeredArchitecture,
  },
  {
    id: 'org',
    name: '组织架构',
    desc: '负责人与团队层级',
    icon: 'folder',
    build: orgChart,
  },
  {
    id: 'uml-class',
    name: 'UML 类图',
    desc: '类、属性、方法与关联关系',
    icon: 'code',
    theme: 'blueprint',
    build: umlClass,
  },
  {
    id: 'er',
    name: '库表设计',
    desc: '实体关系与字段定义',
    icon: 'database',
    theme: 'blueprint',
    build: erDiagram,
  },
  {
    id: 'network',
    name: '网络拓扑',
    desc: '云、防火墙、服务与存储',
    icon: 'cloud',
    theme: 'blueprint',
    build: networkTopology,
  },
]

/** 用模板内容替换文档（保留当前视口由调用方执行自动居中）。 */
export function applyTemplate(doc: CanvasDoc, template: CanvasTemplate): CanvasDoc {
  const { nodes, edges } = template.build()
  return {
    ...emptyDoc(),
    // 模板只替换内容，主题沿用画布当前设置，避免应用模板时整块配色突变。
    theme: doc.theme,
    grid: doc.grid,
    snap: doc.snap,
    nodes,
    edges,
    viewport: doc.viewport,
  }
}
