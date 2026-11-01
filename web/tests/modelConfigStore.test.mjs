import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/modelConfigStore.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText

async function loadStore(hostname, storage) {
  globalThis.window = { location: { hostname } }
  globalThis.localStorage = storage
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#${crypto.randomUUID()}`)
}

function storage() {
  const values = new Map()
  return {
    values,
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
}

const config = {
  provider: 'deepseek', api_key: 'fake-test-key',
  base_url: 'https://api.deepseek.com', model_name: 'deepseek-chat',
}

for (const hostname of ['127.0.0.1', 'myatom-azure-check.example.com']) {
  test(`${hostname}: save, restore, clear and defaults`, async () => {
    const browserStorage = storage()
    const store = await loadStore(hostname, browserStorage)
    assert.equal(store.currentModelConfig(), null)

    // A server-provided local default is available for this page, not saved implicitly.
    assert.equal(store.setActiveModelConfig(config), true)
    assert.equal(browserStorage.values.size, 0)

    assert.equal(store.setActiveModelConfig(config, true), true)
    assert.deepEqual(JSON.parse(browserStorage.getItem('myatom.model-config.v1')), config)
    const refreshed = await loadStore(hostname, browserStorage)
    assert.deepEqual(refreshed.currentModelConfig(), config)

    assert.equal(refreshed.setActiveModelConfig(null, true), true)
    assert.equal(browserStorage.getItem('myatom.model-config.v1'), null)
    assert.equal((await loadStore(hostname, browserStorage)).currentModelConfig(), null)
  })
}

test('storage write failure does not claim a saved configuration', async () => {
  const browserStorage = storage()
  browserStorage.setItem = () => { throw Error('blocked') }
  const store = await loadStore('myatom-azure-check.example.com', browserStorage)
  assert.equal(store.setActiveModelConfig(config, true), false)
  assert.equal(store.currentModelConfig(), null)
})
