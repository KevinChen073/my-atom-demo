export type RunElapsedFields = {
  status: string
  active_elapsed_seconds?: number | null
  execution_running?: boolean | null
  active_seconds?: number | null
  execution_started_at?: string | null
  elapsed_received_at?: number
}

const ACTIVE_STATUSES = new Set(['clarifying', 'planning', 'building'])

export function withRunElapsed<T extends RunElapsedFields>(run: T, receivedAt = Date.now()): T {
  const startedAt = run.execution_started_at ? Date.parse(run.execution_started_at) : NaN
  const legacyRunning = ACTIVE_STATUSES.has(run.status) && Number.isFinite(startedAt)
  const accumulated = typeof run.active_seconds === 'number' && Number.isFinite(run.active_seconds)
    ? Math.max(0, run.active_seconds) : 0
  const legacyElapsed = typeof run.active_seconds === 'number' || legacyRunning
    ? accumulated + (legacyRunning ? Math.max(0, receivedAt - startedAt) / 1000 : 0)
    : undefined
  const reportedElapsed = typeof run.active_elapsed_seconds === 'number' && Number.isFinite(run.active_elapsed_seconds)
    ? Math.max(0, run.active_elapsed_seconds) : undefined
  return {
    ...run,
    active_elapsed_seconds: reportedElapsed ?? legacyElapsed,
    execution_running: typeof run.execution_running === 'boolean' ? run.execution_running : legacyRunning,
    elapsed_received_at: receivedAt,
  }
}
