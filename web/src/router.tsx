import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from 'react'

// A small history router: six routes do not need a dependency.
const listeners = new Set<() => void>()
export function navigate(to: string, replace = false, scroll = true) {
  if (replace) history.replaceState(null, '', to)
  else history.pushState(null, '', to)
  listeners.forEach((l) => l())
  if (scroll) window.scrollTo(0, 0)
}
if (typeof window !== 'undefined') window.addEventListener('popstate', () => listeners.forEach((l) => l()))

export function useLocation() {
  const [loc, setLoc] = useState(() => ({ path: location.pathname, search: location.search }))
  useEffect(() => {
    const f = () => setLoc({ path: location.pathname, search: location.search })
    listeners.add(f)
    return () => { listeners.delete(f) }
  }, [])
  return loc
}

export function match(pattern: string, path: string): Record<string, string> | null {
  const a = pattern.split('/').filter(Boolean), b = path.split('/').filter(Boolean)
  if (a.length !== b.length) return null
  const out: Record<string, string> = {}
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(':')) out[a[i].slice(1)] = decodeURIComponent(b[i])
    else if (a[i] !== b[i]) return null
  }
  return out
}

export function Link({ to, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    rest.onClick?.(e)
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    navigate(to)
  }
  return <a href={to} {...rest} onClick={onClick} />
}
