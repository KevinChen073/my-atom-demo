export type ExceptionRecord = {
  id: string
  trace_id: string
  project_id: string | null
  run_id: string | null
  source: 'agent' | 'build' | 'api'
  phase: string
  code: string
  exception_type: string
  reason: string
  severity: string
  occurred_at: string
}

export type TimelineEvent = { type: string; at: string; seq: number }
export type ExceptionPage = { items: ExceptionRecord[]; next_cursor: string | null }
export type ExceptionDetail = { exception: ExceptionRecord; timeline: TimelineEvent[] }

export type ExceptionFilters = {
  source: string
  code: string
  project_id: string
  trace_id: string
}

export class ApiError extends Error {
  constructor(readonly status: number) {
    super('Exception console request failed')
  }
}

async function request<T>(path: string, key: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'GET',
    headers: { 'X-Operations-Key': key },
    cache: 'no-store',
    credentials: 'omit',
    signal,
  })
  if (!response.ok) throw new ApiError(response.status)
  return response.json() as Promise<T>
}

export function listExceptions(
  key: string,
  filters: ExceptionFilters,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<ExceptionPage> {
  const params = new URLSearchParams({ limit: '30' })
  if (cursor) params.set('cursor', cursor)
  for (const [name, value] of Object.entries(filters)) {
    const trimmed = value.trim()
    if (trimmed) params.set(name, trimmed)
  }
  return request<ExceptionPage>(`/api/ops/exceptions?${params.toString()}`, key, signal)
}

export function getException(key: string, id: string, signal?: AbortSignal): Promise<ExceptionDetail> {
  return request<ExceptionDetail>(`/api/ops/exceptions/${encodeURIComponent(id)}`, key, signal)
}
