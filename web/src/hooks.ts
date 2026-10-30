import { useEffect, useState } from 'react'

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data?: T; error?: Error; loading: boolean } {
  const [s, set] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true })
  useEffect(() => {
    let live = true
    set((p) => ({ ...p, loading: true }))
    fn().then((data) => live && set({ data, loading: false }), (error: Error) => live && set({ error, loading: false }))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return s
}

export function useMedia(q: string) {
  const [m, setM] = useState(() => typeof matchMedia !== 'undefined' && matchMedia(q).matches)
  useEffect(() => {
    const mq = matchMedia(q)
    const f = () => setM(mq.matches)
    mq.addEventListener('change', f)
    return () => mq.removeEventListener('change', f)
  }, [q])
  return m
}

export const useReducedMotion = () => useMedia('(prefers-reduced-motion: reduce)')

let webgl: boolean | undefined
export function hasWebGL(): boolean {
  if (webgl !== undefined) return webgl
  try {
    if (new URLSearchParams(location.search).has('nowebgl')) return (webgl = false)
    const c = document.createElement('canvas')
    webgl = !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch { webgl = false }
  return webgl
}

export function useTheme(): ['light' | 'dark', () => void] {
  const sys = useMedia('(prefers-color-scheme: dark)')
  const [t, setT] = useState<string | null>(() => document.documentElement.getAttribute('data-theme'))
  const eff: 'light' | 'dark' = t === 'light' || t === 'dark' ? t : sys ? 'dark' : 'light'
  const toggle = () => {
    const next = eff === 'dark' ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', next)
    try { localStorage.setItem('wl-theme', next) } catch { /* storage blocked */ }
    setT(next)
    window.dispatchEvent(new Event('wl-theme'))
  }
  return [eff, toggle]
}

/** Effective theme for canvases that cannot read CSS variables live. */
export function useEffectiveTheme(): 'light' | 'dark' {
  const sys = useMedia('(prefers-color-scheme: dark)')
  const [, force] = useState(0)
  useEffect(() => { const f = () => force((n) => n + 1); window.addEventListener('wl-theme', f); return () => window.removeEventListener('wl-theme', f) }, [])
  const t = document.documentElement.getAttribute('data-theme')
  return t === 'light' || t === 'dark' ? t : sys ? 'dark' : 'light'
}
