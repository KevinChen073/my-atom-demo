import { useEffect, useRef, useState } from 'react'
import './invite-access.css'

export type InviteSession = { invited: boolean; platform_model_available: boolean; invite_required: boolean }

export function InviteAccess({ session, onChange }: {
  session: InviteSession | null
  onChange: (session: InviteSession) => void
}) {
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const changedLocally = useRef(false)

  useEffect(() => {
    let cancelled = false
    fetch('/api/auth/session', { credentials: 'same-origin' }).then(async response => {
      if (!response.ok) return
      const current = await response.json() as InviteSession
      if (!cancelled && !changedLocally.current) onChange(current)
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  async function authenticate() {
    if (busy) return
    setBusy(true); setError('')
    try {
      const response = await fetch('/api/auth/invite', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: code.trim() }) })
      if (!response.ok) { const result = await response.json(); throw new Error(result.detail || '邀请码验证失败') }
      changedLocally.current = true
      onChange(await response.json() as InviteSession)
      setCode(''); setOpen(false)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  async function logout() {
    if (busy) return
    setBusy(true); setError('')
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) throw new Error('退出测试身份失败')
      changedLocally.current = true
      onChange(await response.json() as InviteSession)
      setOpen(false)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  if (!session?.invite_required && !session?.invited) return null

  return <>
    <button type="button" className="invite-trigger" onClick={() => setOpen(true)}>
      {session?.invited ? '测试身份 ✓' : '输入邀请码'}
    </button>
    {open && <div className="invite-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setOpen(false) }}>
      <div className="invite-dialog" role="dialog" aria-modal="true" aria-labelledby="invite-title">
        <div className="invite-head"><h2 id="invite-title">{session?.invited ? '测试身份' : '使用邀请码'}</h2><button type="button" onClick={() => setOpen(false)} aria-label="关闭">×</button></div>
        {session?.invited ? <><p>你可以在不同设备输入同一个邀请码，继续访问对应的项目。</p><button type="button" onClick={logout} disabled={busy}>退出测试身份</button></>
          : <><p>持有邀请码即可进入对应的测试项目空间。邀请码仅用于验证，不会保存在浏览器。</p>
            <label htmlFor="invite-code">邀请码</label><input id="invite-code" type="password" value={code} autoComplete="off" onChange={event => setCode(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void authenticate() }} />
            <button type="button" onClick={authenticate} disabled={busy || code.trim().length < 24}>{busy ? '验证中…' : '验证并进入'}</button></>}
        {error && <p role="alert" className="invite-error">{error}</p>}
      </div>
    </div>}
  </>
}
