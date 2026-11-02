import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/inviteCode.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText
const { canSubmitInviteCode } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('short invitation codes can be submitted by both button and Enter form path', () => {
  assert.equal(canSubmitInviteCode('demo1234'), true)
  assert.equal(canSubmitInviteCode(' x '), true)
  assert.equal(canSubmitInviteCode(''), false)
  assert.equal(canSubmitInviteCode('   '), false)
})
