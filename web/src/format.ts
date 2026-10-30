export const pct = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? 'n/a' : `${(x * 100).toFixed(d)}%`)
export const num = (x: number) => x.toLocaleString('en-US')
export const ngn = (x: number) => (x >= 1e9 ? `N${(x / 1e9).toFixed(2)}bn` : x >= 1e6 ? `N${(x / 1e6).toFixed(1)}m` : `N${num(Math.round(x))}`)
export const usd = (x: number) => `US$${num(Math.round(x))}`
export const hh = (h: number) => `${String(Math.floor(h) % 24).padStart(2, '0')}:00`
/** Percent with a decimal for small non-zero shares, so 0.2% does not read as 0%. */
export const pctFine = (x: number | null | undefined) => (x === null || x === undefined ? 'n/a' : x > 0 && x < 0.01 ? `${(x * 100).toFixed(1)}%` : `${Math.round(x * 100)}%`)
