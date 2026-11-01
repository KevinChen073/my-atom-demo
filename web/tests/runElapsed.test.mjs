import assert from 'node:assert/strict'
import test from 'node:test'
import { withRunElapsed } from '../src/runElapsed.ts'

test('older API snapshots show active time without counting user waits', () => {
  const startedAt = new Date(100_000).toISOString()
  const active = withRunElapsed({ status: 'building', active_seconds: 75, execution_started_at: startedAt }, 104_500)
  assert.equal(active.active_elapsed_seconds, 79.5)
  assert.equal(active.execution_running, true)
  assert.equal(active.elapsed_received_at, 104_500)

  const waiting = withRunElapsed({ status: 'awaiting_plan', active_seconds: 75, execution_started_at: null }, 200_000)
  assert.equal(waiting.active_elapsed_seconds, 75)
  assert.equal(waiting.execution_running, false)
})

test('new API elapsed time takes precedence over legacy fields', () => {
  const snapshot = withRunElapsed({ status: 'building', active_elapsed_seconds: 91.25, execution_running: true,
    active_seconds: 75, execution_started_at: new Date(100_000).toISOString() }, 104_500)
  assert.equal(snapshot.active_elapsed_seconds, 91.25)
  assert.equal(snapshot.execution_running, true)
})

test('missing time data stays unknown', () => {
  const snapshot = withRunElapsed({ status: 'planning' }, 104_500)
  assert.equal(snapshot.active_elapsed_seconds, undefined)
  assert.equal(snapshot.execution_running, false)
})
