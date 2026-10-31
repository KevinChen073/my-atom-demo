import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent } from 'react'

type Column = 'sidebar' | 'chat'
type Layout = { sidebar: number; chat: number }
type Drag = { column: Column; pointerId: number; startX: number; start: Layout; previous: Layout | null; target: HTMLElement }

const STORAGE_KEY = 'myatom.column-layout.v1'
const DESKTOP_WIDTH = 1280
const SIDEBAR_DEFAULT = 208
const SIDEBAR_MIN = 180
const SIDEBAR_MAX = 300
const CHAT_MIN = 440
const CHAT_MAX = 680
const PREVIEW_MIN = 560

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

function readLayout(): Layout | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null || !('sidebar' in value) || !('chat' in value)) return null
    const sidebar = value.sidebar
    const chat = value.chat
    if (typeof sidebar !== 'number' || !Number.isFinite(sidebar) || sidebar < SIDEBAR_MIN || sidebar > SIDEBAR_MAX) return null
    if (typeof chat !== 'number' || !Number.isFinite(chat) || chat < CHAT_MIN || chat > CHAT_MAX) return null
    return { sidebar, chat }
  } catch { return null }
}

function bounds(width: number, sidebar: number) {
  const available = Math.max(DESKTOP_WIDTH, width)
  return {
    sidebarMin: SIDEBAR_MIN,
    sidebarMax: Math.min(SIDEBAR_MAX, available - CHAT_MIN - PREVIEW_MIN),
    chatMin: CHAT_MIN,
    chatMax: Math.min(CHAT_MAX, available - sidebar - PREVIEW_MIN),
  }
}

function resolveLayout(saved: Layout | null, width: number): Layout {
  const sidebar = clamp(saved?.sidebar ?? SIDEBAR_DEFAULT, SIDEBAR_MIN, bounds(width, SIDEBAR_DEFAULT).sidebarMax)
  const chatDefault = width <= DESKTOP_WIDTH ? 440 : width < 1400 ? 520 : 600
  const chat = clamp(saved?.chat ?? chatDefault, CHAT_MIN, bounds(width, sidebar).chatMax)
  return { sidebar, chat }
}

export function useColumnLayout() {
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth)
  const [saved, setSaved] = useState<Layout | null>(readLayout)
  const [dragging, setDragging] = useState<Column | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const savedRef = useRef(saved)
  const dragRef = useRef<Drag | null>(null)
  const current = resolveLayout(saved, viewportWidth)
  const range = bounds(viewportWidth, current.sidebar)
  const enabled = viewportWidth >= DESKTOP_WIDTH

  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  function update(next: Layout) {
    savedRef.current = next
    setSaved(next)
  }

  function persist(next: Layout) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      setAnnouncement(`布局已保存：导航 ${Math.round(next.sidebar)} 像素，对话 ${Math.round(next.chat)} 像素。`)
    } catch { setAnnouncement('浏览器未允许保存布局；本次页面内的调整仍可使用。') }
  }

  function start(column: Column, event: PointerEvent<HTMLElement>) {
    if (!enabled || event.button !== 0) return
    event.preventDefault()
    const target = event.currentTarget
    target.setPointerCapture(event.pointerId)
    dragRef.current = {
      column, pointerId: event.pointerId, startX: event.clientX,
      start: resolveLayout(savedRef.current, window.innerWidth), previous: savedRef.current, target,
    }
    setDragging(column)
  }

  function move(event: PointerEvent<HTMLElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const width = window.innerWidth
    const delta = event.clientX - drag.startX
    if (drag.column === 'sidebar') {
      const sidebar = clamp(drag.start.sidebar + delta, SIDEBAR_MIN, bounds(width, drag.start.sidebar).sidebarMax)
      update({ sidebar, chat: clamp(drag.start.chat - (sidebar - drag.start.sidebar), CHAT_MIN, bounds(width, sidebar).chatMax) })
    } else {
      update({ sidebar: drag.start.sidebar, chat: clamp(drag.start.chat + delta, CHAT_MIN, bounds(width, drag.start.sidebar).chatMax) })
    }
  }

  function finish(event: PointerEvent<HTMLElement>) {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    dragRef.current = null
    setDragging(null)
    if (drag.target.hasPointerCapture(drag.pointerId)) drag.target.releasePointerCapture(drag.pointerId)
    persist(savedRef.current || drag.start)
  }

  function cancel() {
    const drag = dragRef.current
    if (!drag) return
    dragRef.current = null
    savedRef.current = drag.previous
    setSaved(drag.previous)
    setDragging(null)
    if (drag.target.hasPointerCapture(drag.pointerId)) drag.target.releasePointerCapture(drag.pointerId)
    setAnnouncement('已取消布局调整。')
  }

  useEffect(() => {
    if (!dragging) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); cancel() }
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('blur', cancel)
    return () => { window.removeEventListener('keydown', onKeyDown); window.removeEventListener('blur', cancel) }
  }, [dragging])

  function key(column: Column, event: ReactKeyboardEvent<HTMLElement>) {
    if (!enabled) return
    const old = resolveLayout(savedRef.current, window.innerWidth)
    const limits = bounds(window.innerWidth, old.sidebar)
    const min = column === 'sidebar' ? limits.sidebarMin : limits.chatMin
    const max = column === 'sidebar' ? limits.sidebarMax : limits.chatMax
    let value: number
    if (event.key === 'Home') value = min
    else if (event.key === 'End') value = max
    else if (event.key === 'ArrowLeft') value = old[column] - (event.shiftKey ? 48 : 16)
    else if (event.key === 'ArrowRight') value = old[column] + (event.shiftKey ? 48 : 16)
    else return
    event.preventDefault()
    const nextValue = clamp(value, min, max)
    const next = column === 'sidebar'
      ? { sidebar: nextValue, chat: clamp(old.chat - (nextValue - old.sidebar), CHAT_MIN, bounds(window.innerWidth, nextValue).chatMax) }
      : { sidebar: old.sidebar, chat: nextValue }
    update(next)
    persist(next)
  }

  function reset() {
    cancel()
    savedRef.current = null
    setSaved(null)
    try { window.localStorage.removeItem(STORAGE_KEY) } catch { /* usable without storage */ }
    setAnnouncement('已恢复默认布局。')
  }

  return { current, range, enabled, dragging, announcement, start, move, finish, cancel, key, reset }
}
