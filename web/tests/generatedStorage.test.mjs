import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../../templates/react-vite/src/hooks/generatedAppStorage.ts', import.meta.url), 'utf8')
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

test('generated app storage scopes an order key containing a colon', () => {
  const values = new Map()
  const projectId = 'a'.repeat(32)
  const context = {
    exports: {},
    document: { querySelector: () => ({ content: projectId }) },
    window: { localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: key => values.delete(key),
    } },
  }
  vm.runInNewContext(javascript, context)
  const storage = context.exports.generatedAppStorage
  storage.setItem('order-demo:orders', '[1]')
  assert.equal(storage.getItem('order-demo:orders'), '[1]')
  assert.equal(values.get(`myatom.app.${projectId}.order-demo:orders`), '[1]')
  assert.throws(() => storage.setItem('order-demo/orders', '[2]'), /数据键名无效/)
})
