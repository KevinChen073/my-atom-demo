/** Generated apps use this narrow, same-origin API. No model key enters the browser. */
export type AppRecord = { id: string; [field: string]: unknown }

function endpoint(entity: string, id?: string | number): string {
  const version = window.location.pathname.match(/^\/v\/([0-9a-f-]{36})\//)?.[1]
  if (!version) throw new Error('请在 MYATOM 预览中打开应用')
  if (!/^[a-z][a-z0-9_]{0,39}$/.test(entity)) throw new Error('无效的数据实体')
  return `/data/${version}/${entity}${id !== undefined ? `/${encodeURIComponent(String(id))}` : ''}`
}

async function request<T>(url: string, method = 'GET', data?: Record<string, unknown>, idempotencyKey?: string): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: data ? { 'Content-Type': 'application/json', ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}) } : undefined,
    body: data ? JSON.stringify({ data }) : undefined,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `保存失败（${response.status}）`)
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}

export async function listRecords(entity: string): Promise<AppRecord[]> {
  return request<AppRecord[]>(endpoint(entity))
}

export async function createRecord(entity: string, data: Record<string, unknown>): Promise<AppRecord> {
  return request<AppRecord>(endpoint(entity), 'POST', data, crypto.randomUUID())
}

export async function updateRecord(entity: string, id: string | number, data: Record<string, unknown>): Promise<AppRecord> {
  return request<AppRecord>(endpoint(entity, id), 'PATCH', data)
}

export async function deleteRecord(entity: string, id: string | number): Promise<void> {
  return request<void>(endpoint(entity, id), 'DELETE')
}
