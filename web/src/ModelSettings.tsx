import { useEffect, useState } from 'react'
import { currentModelConfig, DEFAULT_MODEL, setActiveModelConfig } from './modelConfigStore'
import type { ModelConfig } from './modelConfigStore'
import './model-settings.css'

type Defaults = ModelConfig

export function ModelSettings({ onChange }: { onChange: (config: ModelConfig | null) => void }) {
  const [open, setOpen] = useState(false)
  const [config, setConfig] = useState<ModelConfig>(currentModelConfig() || DEFAULT_MODEL)
  const [visible, setVisible] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (currentModelConfig()) return
    let cancelled = false
    fetch('/api/model/defaults', { credentials: 'same-origin' }).then(async response => {
      if (!response.ok) return
      const defaults = await response.json() as Defaults
      if (cancelled || currentModelConfig()) return
      const next = { provider: defaults.provider || 'deepseek', api_key: defaults.api_key || '',
        base_url: defaults.base_url || DEFAULT_MODEL.base_url, model_name: defaults.model_name || DEFAULT_MODEL.model_name } as ModelConfig
      setConfig(next)
      if (next.api_key) { setActiveModelConfig(next); onChange(next) }
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [onChange])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  function update(next: Partial<ModelConfig>) { setConfig(value => ({ ...value, ...next })); setError(''); setTestResult('') }
  function validate(): string {
    if (!config.api_key.trim()) return '请填写 API Key'
    if (!/^https:\/\/[^\s/?#]+(?:\/v1)?\/?$/.test(config.base_url.trim())) return '请填写 HTTPS 接口地址'
    if (!config.model_name.trim()) return '请填写模型名称'
    return ''
  }
  function save() {
    const issue = validate()
    if (issue) { setError(issue); return }
    const next = { ...config, api_key: config.api_key.trim(), base_url: config.base_url.trim().replace(/\/$/, ''), model_name: config.model_name.trim() }
    setActiveModelConfig(next, true); onChange(next); setOpen(false)
  }
  async function test() {
    const issue = validate()
    if (issue) { setError(issue); return }
    setTesting(true); setTestResult(''); setError('')
    try {
      const response = await fetch('/api/model/test', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Myatom-Model-Config': JSON.stringify(config) } })
      if (!response.ok) { const detail = await response.json(); throw new Error(detail.detail || '连接失败') }
      setTestResult('连接成功')
    } catch (reason) { setError((reason as Error).message) }
    finally { setTesting(false) }
  }
  function clearKey() {
    const cleared = { ...config, api_key: '' }
    setActiveModelConfig(cleared, true); onChange(cleared); update({ api_key: '' })
  }

  const saved = currentModelConfig()
  return <>
    <button type="button" className="model-trigger" onClick={() => { setConfig(saved || config); setOpen(true) }} aria-label="打开模型设置">
      <span aria-hidden="true">⚿</span> {saved?.api_key ? `${saved.provider === 'deepseek' ? 'DeepSeek' : 'OpenAI 兼容'} · ${saved.model_name}` : '设置模型'}
    </button>
    {open && <div className="model-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setOpen(false) }}>
      <div className="model-dialog" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title">
        <div className="model-dialog-head"><h2 id="model-dialog-title">模型设置</h2><button type="button" onClick={() => setOpen(false)} aria-label="关闭模型设置">×</button></div>
        <p>使用自己的 API Key 调用模型。Key 只保存在当前浏览器的 localStorage；运行时发送给后端，不写入项目或日志。共用电脑请在结束后清除 Key。</p>
        <label>服务类型</label><div className="model-provider-tabs">
          <button type="button" className={config.provider === 'deepseek' ? 'active' : ''} onClick={() => update({ provider: 'deepseek', base_url: 'https://api.deepseek.com', model_name: 'deepseek-chat' })}>DeepSeek</button>
          <button type="button" className={config.provider === 'openai_compatible' ? 'active' : ''} onClick={() => update({ provider: 'openai_compatible', base_url: 'https://api.openai.com/v1', model_name: 'gpt-4.1-mini' })}>OpenAI 兼容</button>
        </div>
        <label htmlFor="model-api-key">API Key</label><div className="model-key-field"><input id="model-api-key" type={visible ? 'text' : 'password'} value={config.api_key} onChange={event => update({ api_key: event.target.value })} autoComplete="off" /><button type="button" onClick={() => setVisible(value => !value)} aria-label={visible ? '隐藏 Key' : '显示 Key'}>{visible ? '隐藏' : '显示'}</button></div>
        <label htmlFor="model-base-url">接口地址（Base URL）</label><input id="model-base-url" value={config.base_url} onChange={event => update({ base_url: event.target.value })} />
        <small>一般保持默认即可。</small>
        <label htmlFor="model-name">模型名称</label><input id="model-name" value={config.model_name} onChange={event => update({ model_name: event.target.value })} />
        {config.provider === 'deepseek' && <div className="model-quick-options"><button type="button" onClick={() => update({ model_name: 'deepseek-chat' })}>deepseek-chat</button><button type="button" onClick={() => update({ model_name: 'deepseek-reasoner' })}>deepseek-reasoner</button></div>}
        {(error || testResult) && <p role="status" className={error ? 'model-error' : 'model-success'}>{error || testResult}</p>}
        <div className="model-dialog-actions"><button type="button" onClick={clearKey}>清除 Key</button><span /><button type="button" onClick={test} disabled={testing}>{testing ? '测试中…' : '测试连接'}</button><button type="button" className="model-save" onClick={save}>保存</button></div>
      </div>
    </div>}
  </>
}
