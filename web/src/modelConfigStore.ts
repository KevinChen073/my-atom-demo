export type ModelConfig = {
  provider: 'deepseek' | 'openai_compatible'
  api_key: string
  base_url: string
  model_name: string
}

const STORAGE_KEY = 'myatom.model-config.v1'
export const isLocalWorkbench = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
export const DEFAULT_MODEL: ModelConfig = {
  provider: 'deepseek', api_key: '', base_url: 'https://api.deepseek.com', model_name: 'deepseek-chat',
}

export function readSavedModelConfig(): ModelConfig | null {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (!value || !['deepseek', 'openai_compatible'].includes(value.provider)
      || typeof value.api_key !== 'string' || typeof value.base_url !== 'string'
      || typeof value.model_name !== 'string') return null
    return value as ModelConfig
  } catch { return null }
}

let activeConfig: ModelConfig | null = readSavedModelConfig()
let usePlatformModel = false
export function setPlatformModel(value: boolean): void { usePlatformModel = value }
export function currentModelConfig(): ModelConfig | null { return activeConfig }
export function setActiveModelConfig(config: ModelConfig | null, persist = false): boolean {
  if (persist) {
    try {
      if (config) localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
      else localStorage.removeItem(STORAGE_KEY)
    } catch { return false }
  }
  activeConfig = config
  return true
}

export function modelRequestHeader(): Record<string, string> {
  return !usePlatformModel && activeConfig?.api_key ? { 'X-Myatom-Model-Config': JSON.stringify(activeConfig) } : {}
}
