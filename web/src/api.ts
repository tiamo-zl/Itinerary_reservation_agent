export interface SSEEvent {
  type: string
  data: Record<string, any>
}

export interface SpanNode {
  span_id: string
  parent_span_id: string | null
  name: string
  layer: string
  status: string
  duration_ms: number
  attributes: Record<string, unknown>
  children: SpanNode[]
}

export interface TraceSummary {
  trace_id: string
  started_at: string
  span_count: number
  error_count: number
  max_duration_ms: number
  layers: string[]
  task_id: string | null
  task_status: string | null
  tenant_id: string | null
}

export interface TraceDetail {
  trace_id: string
  task_id: string | null
  task_status: string | null
  spans: SpanNode[]
}

export interface HistoryItem {
  values: Record<string, any>
  next: string[]
  created_at: string | null
  metadata: Record<string, any>
  checkpoint_id: string | null
}

export interface Badcase {
  badcase_id: string
  trace_id: string
  task_id: string | null
  tenant_id: string
  category: string
  severity: string
  user_input: string
  expected: string
  actual: string
  comment: string
  root_cause: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface ApprovalItem {
  approval_id: string
  task_id: string
  revision: number
  status: string
  comment: string | null
  payload: {
    request?: Record<string, any>
    options?: {
      flights?: Array<Record<string, any>>
      hotels?: Array<Record<string, any>>
    }
    policy_result?: {
      passed?: boolean
      requires_approval?: boolean
      violations?: Array<Record<string, any>>
    }
    revision?: number
  } | null
  trace_id: string | null
  user_id: string | null
  tenant_id: string | null
  task_status: string | null
  created_at: string
  updated_at: string
}

export interface TaskState {
  values: Record<string, any>
  next: string[]
}

export interface OverviewData {
  totals: {
    traces: number
    spans: number
    errors: number
    avg_duration_ms: number
    error_rate: number
    p95_duration_ms: number
  }
  layers: Array<{
    layer: string
    spans: number
    errors: number
    avg_duration_ms: number
  }>
  llm: {
    calls: number
    prompt_tokens: number
    completion_tokens: number
    cost_usd: number
  }
  approvals: Array<{ status: string; count: number }>
  task_status: Array<{ status: string; count: number }>
  badcases: Array<{ status: string; count: number }>
  recent_traces: TraceSummary[]
}

const API_BASE = import.meta.env.VITE_API_BASE || ''

function url(path: string) {
  return `${API_BASE}${path}`
}

function headers(user?: string): Record<string, string> {
  const result: Record<string, string> = { 'Content-Type': 'application/json' }
  if (user) result['X-Mock-User'] = user
  return result
}

function emitBlock(block: string, onEvent: (event: SSEEvent) => void) {
  let type = 'message'
  const dataLines: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    const value = separator === -1 ? '' : line.slice(separator + 1).trimStart()
    if (field === 'event') type = value
    else if (field === 'data') dataLines.push(value)
  }
  if (!dataLines.length) return
  try {
    onEvent({ type, data: JSON.parse(dataLines.join('\n')) })
  } catch {
    onEvent({ type, data: { raw: dataLines.join('\n') } })
  }
}

/**
 * 读取后端 SSE。返回全部事件，方便页面同时做 UI 更新和调试。
 */
export async function streamPost(
  path: string,
  payload: unknown,
  user: string,
  onEvent: (event: SSEEvent) => void,
): Promise<SSEEvent[]> {
  const response = await fetch(url(path), {
    method: 'POST',
    headers: headers(user),
    body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    throw new Error(`请求失败：${response.status}`)
  }

  const events: SSEEvent[] = []
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const flush = (block: string) => {
    emitBlock(block, (event) => {
      events.push(event)
      onEvent(event)
    })
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let match = buffer.match(/\r?\n\r?\n/)
    while (match && match.index !== undefined) {
      flush(buffer.slice(0, match.index))
      buffer = buffer.slice(match.index + match[0].length)
      match = buffer.match(/\r?\n\r?\n/)
    }
  }
  if (buffer.trim()) flush(buffer)
  return events
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `请求失败：${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function getJson<T>(path: string, user?: string): Promise<T> {
  return readJson<T>(await fetch(url(path), { headers: headers(user) }))
}

export async function postJson<T>(
  path: string,
  payload: unknown,
  user = 'u001',
): Promise<T> {
  return readJson<T>(await fetch(url(path), {
    method: 'POST',
    headers: headers(user),
    body: JSON.stringify(payload),
  }))
}

export async function patchJson<T>(
  path: string,
  payload: unknown,
  user = 'u001',
): Promise<T> {
  return readJson<T>(await fetch(url(path), {
    method: 'PATCH',
    headers: headers(user),
    body: JSON.stringify(payload),
  }))
}
