import { useEffect } from 'react'
import { MODE } from './api/client'
import { Icon, Logo, SampleBadge } from './components/ui'
import { useTheme } from './hooks'
import { Link, match, useLocation } from './router'
import { About } from './pages/About'
import { FacilityPage } from './pages/Facility'
import { FacilitySheet } from './pages/FacilitySheet'
import { FeederPage } from './pages/Feeder'
import { Method } from './pages/Method'
import { Overview } from './pages/Overview'
import { PlanPage } from './pages/Plan'
import { BriefPage } from './pages/Brief'
import { CityBriefPage } from './pages/CityBrief'
import { CityPage } from './pages/City'
import { SitePage } from './pages/Site'
import { CITIES, type CityId } from './api/brief13'

const NAV = [['/', 'City scoreboard'], ['/plan', 'Funder plan'], ['/method', 'How it decides'], ['/facilities', 'Health facilities'], ['/about', 'About']] as const

function route(path: string) {
  let m
  if (path === '/' || path === '') return { el: <CityPage city="maiduguri" />, title: 'Maiduguri', city: true }
  if ((m = match('/city/:city', path)) && CITIES.some((c) => c.id === m!.city)) return { el: <CityPage city={m.city as CityId} />, title: CITIES.find((c) => c.id === m!.city)!.name, city: true }
  if ((m = match('/site/:id', path))) return { el: <SitePage id={m.id} />, title: `Site ${m.id}`, city: true }
  if (path === '/facilities') return { el: <Overview />, title: 'Health facilities' }
  if ((m = match('/facility/:id/sheet', path))) return { el: <FacilitySheet id={m.id} />, title: `Facility sheet ${m.id}`, bare: true }
  if ((m = match('/facility/:id', path))) return { el: <FacilityPage id={m.id} />, title: `Facility ${m.id}` }
  if ((m = match('/feeder/:id', path))) return { el: <FeederPage id={m.id} />, title: `Feeder ${m.id}` }
  if (path === '/plan/brief') return { el: <CityBriefPage />, title: 'Investment brief', bare: true, city: true }
  if (path === '/facilities/brief') return { el: <BriefPage />, title: 'Health facilities brief', bare: true }
  if (path === '/plan') return { el: <PlanPage />, title: 'Funder plan', city: true }
  if (path === '/method') return { el: <Method />, title: 'How it decides' }
  if (path === '/about') return { el: <About />, title: 'About' }
  return { el: <div><h1>Page not found</h1><p><Link to="/">Back to the overview</Link></p></div>, title: 'Not found' }
}

export default function App() {
  const { path } = useLocation()
  const [theme, toggle] = useTheme()
  const r = route(path)
  useEffect(() => { document.title = `${r.title} · Wardlight` }, [r.title])
  const current = (to: string) => (to === '/' ? path === '/' || path.startsWith('/city/') || path.startsWith('/site/') : path.startsWith(to))
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <div className="wrap">
          <Link to="/" className="brand" aria-label="Wardlight, city scoreboard"><Logo /> Wardlight <small>critical power when the line is cut</small></Link>
          <nav className="nav" aria-label="Main">
            {NAV.map(([to, label]) => <Link key={to} to={to} aria-current={current(to) ? 'page' : undefined}>{label}</Link>)}
          </nav>
          <button className="icon-btn theme-btn" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title="Theme">
            <Icon name={theme === 'dark' ? 'light' : 'moon'} />
          </button>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <div className="wrap">
          {MODE === 'fixture' && !r.bare && !r.city && (
            <div className="banner no-print" style={{ marginBottom: 18 }}>
              <SampleBadge /> Fixture mode: health-facility records on this screen are synthetic samples (Edo State) and carry no engine results. City screens use recorded engine output. Quoted sources and the NERC row are real and linked.
            </div>
          )}
          {r.el}
        </div>
      </main>
      <footer className="site">
        <div className="wrap row between">
          <span>Wardlight, team Two to Eight. IAS Global Energy Hackathon 2026, brief 13, Power for a city the grid can't protect. English only.</span>
          <span className="mono">{MODE === 'fixture' ? 'fixture mode' : 'live API'}</span>
        </div>
      </footer>
    </>
  )
}
