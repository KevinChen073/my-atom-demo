import assert from 'node:assert/strict'
import test from 'node:test'
import { canSubmitNewRunRequest } from '../src/requestValidation.ts'

test('a short follow-up can modify an existing version', () => {
  assert.equal(canSubmitNewRunRequest('增加图片', true), true)
  assert.equal(canSubmitNewRunRequest('  ', true), false)
})

test('a first run still needs a descriptive request', () => {
  assert.equal(canSubmitNewRunRequest('增加图片', false), false)
  assert.equal(canSubmitNewRunRequest('做一个支持添加图片的网页应用', false), true)
})
