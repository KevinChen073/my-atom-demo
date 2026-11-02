import { useEffect, useRef, useState } from 'react'
import { currentModelConfig, DEFAULT_MODEL, setActiveModelConfig } from './modelConfigStore'
import type { ModelConfig } from './modelConfigStore'
import { canSubmitInviteCode } from './inviteCode'
import './model-settings.css'

type Defaults = ModelConfig
export type InviteSession = { invited: boolean; platform_model_available: boolean; invite_required: boolean }

export function ModelSettings({ onChange, session, onInviteChange, platformModel, onModeChange }: {
  onChange: (config: ModelConfig | null) => void
  session: InviteSession | null
  onInviteChange: (session: InviteSession) => void
  platformModel: boolean
  onModeChange: (useInvite: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'own' | 'invite'>('own')
  const [config, setConfig] = useState<ModelConfig>(currentModelConfig() || DEFAULT_MODEL)
  const [inviteCode, setInviteCode] = useState('')
  const [inviteBusy, setInviteBusy] = useState(false)
  const [inviteError, setInviteError] = useState('')
  const inviteChangedLocally = useRef(false)
  const [visible, setVisible] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch('/api/auth/session', { credentials: 'same-origin' }).then(async response => {
      if (!response.ok) return
      const current = await response.json() as InviteSession
      if (!cancelled && !inviteChangedLocally.current) onInviteChange(current)
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (currentModelConfig()) return
    let cancelled = false
    fetch('/api/model/defaults', { credentials: 'same-origin' }).then(async response => {
      if (!response.ok) return
      const defaults = await response.json() as Defaults
      if (cancelled || currentModelConfig()) return
      const next = { provider: defaults.provider || 'deepseek', api_key: '',
        base_url: defaults.base_url || DEFAULT_MODEL.base_url, model_name: defaults.model_name || DEFAULT_MODEL.model_name } as ModelConfig
      setConfig(next)
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
    if (!setActiveModelConfig(next, true)) { setError('浏览器无法保存 Key。请检查站点存储权限或可用空间。'); return }
    onChange(next); onModeChange(false); setOpen(false)
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
    if (!setActiveModelConfig(null, true)) { setError('浏览器无法清除已保存的 Key。请检查站点存储权限。'); return }
    onChange(null); update({ api_key: '' })
  }

  async function authenticateInvite() {
    if (inviteBusy || !canSubmitInviteCode(inviteCode)) return
    setInviteBusy(true); setInviteError('')
    try {
      const response = await fetch('/api/auth/invite', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: inviteCode.trim() }) })
      if (!response.ok) { const result = await response.json(); throw new Error(result.detail || '邀请码验证失败') }
      const next = await response.json() as InviteSession
      inviteChangedLocally.current = true
      onInviteChange(next)
      setInviteCode('')
      if (next.platform_model_available) { onModeChange(true); setOpen(false) }
      else { setMode('own'); setTestResult('邀请码已验证；请填写自己的 API Key。') }
    } catch (reason) { setInviteError((reason as Error).message) }
    finally { setInviteBusy(false) }
  }

  async function logoutInvite() {
    if (inviteBusy) return
    setInviteBusy(true); setInviteError('')
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) throw new Error('退出测试身份失败')
      inviteChangedLocally.current = true
      onInviteChange(await response.json() as InviteSession)
      onModeChange(false)
      setMode('own')
    } catch (reason) { setInviteError((reason as Error).message) }
    finally { setInviteBusy(false) }
  }

  const saved = currentModelConfig()
  function openSettings() {
    setConfig(saved || config)
    setMode(platformModel ? 'invite' : 'own')
    setError(''); setInviteError(''); setTestResult('')
    setOpen(true)
  }
  return <>
    <button type="button" className="model-trigger" onClick={openSettings} aria-label="打开模型设置">
      <span aria-hidden="true">⚿</span> {platformModel && session?.invited ? '测试邀请码 ✓' : saved?.api_key ? `${saved.provider === 'deepseek' ? 'DeepSeek' : 'OpenAI 兼容'} · ${saved.model_name}` : '设置模型'}
    </button>
    {open && <div className="model-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setOpen(false) }}>
      <div className="model-dialog" role="dialog" aria-modal="true" aria-labelledby="model-dialog-title">
        <div className="model-dialog-head"><h2 id="model-dialog-title">模型设置</h2><button type="button" onClick={() => setOpen(false)} aria-label="关闭模型设置">×</button></div>
        <p>选择自己的 API Key，或使用测试邀请码。邀请码仅用于验证，不会保存在浏览器。</p>
        <div className="model-source-tabs" role="group" aria-label="模型使用方式">
          <button type="button" className={mode === 'own' ? 'active' : ''} aria-pressed={mode === 'own'} onClick={() => setMode('own')}>使用自己的 API Key</button>
          <button type="button" className={mode === 'invite' ? 'active' : ''} aria-pressed={mode === 'invite'} onClick={() => setMode('invite')}>使用测试邀请码</button>
        </div>
        {mode === 'invite' ? <div className="model-invite-section">
          {session?.invited ? <>
            <p className="model-invite-status" role="status">邀请码已验证{session.platform_model_available ? '，可以使用测试模型。' : '，当前未提供测试模型，请使用自己的 API Key。'}</p>
            <div className="model-dialog-actions"><button type="button" onClick={logoutInvite} disabled={inviteBusy}>退出测试身份</button><span />{session.platform_model_available && <button type="button" className="model-save" onClick={() => { onModeChange(true); setOpen(false) }}>使用测试模型</button>}</div>
          </> : <form className="model-invite-form" onSubmit={event => { event.preventDefault(); void authenticateInvite() }}>
            <label htmlFor="invite-code">邀请码</label><input id="invite-code" type="password" value={inviteCode} autoComplete="off" onChange={event => setInviteCode(event.target.value)} />
            {inviteError && <p role="alert" className="model-error">{inviteError}</p>}
            <button type="submit" className="model-save" disabled={inviteBusy || !canSubmitInviteCode(inviteCode)}>{inviteBusy ? '验证中…' : '验证并使用'}</button>
          </form>}
        </div> : <div className="model-own-section">
        {session?.invite_required && !session.invited && <p className="model-access-note">创建和预览项目还需要验证邀请码。</p>}
        <p>点击保存后，API Key 会存入当前浏览器，刷新后恢复。生成应用与工作台同源，预览脚本可能读取它；结束后可清除 Key。</p>
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
        </div>}
      </div>
    </div>}
  </>
}
