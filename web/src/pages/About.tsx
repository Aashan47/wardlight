import { MODE } from '../api/client'
import { Link } from '../router'

export function About() {
  return (
    <article style={{ maxWidth: 820 }}>
      <p className="kicker">About</p>
      <h1>Wardlight</h1>
      <p>
        Built by Aashan Javed, working solo as team <strong>Two to Eight</strong>, from Pakistan, for the IAS Global Energy Hackathon 2026, brief 1,
        “Off-grid cold storage for clinics”, in the Digital Solutions and AI track.
      </p>
      <h2>Who it is for</h2>
      <p>
        The planner who decides which health facilities get solar next with a fixed budget, such as a State Primary Health Care Development Agency, a Rural Electrification Agency programme or a funder.
        And the officer in charge of one facility, who needs a page that makes the case for their own clinic.
      </p>
      <p>
        {MODE === 'fixture'
          ? 'This build is running on sample fixtures: facility numbers are synthetic placeholders and are labelled as such on every screen.'
          : 'This build is connected to the live API.'}
      </p>
      <h2>Open source</h2>
      <p>React, three.js, MapLibre GL JS, Vite and Workbox; IBM Plex Sans and Mono (SIL Open Font License). Basemap by OpenFreeMap from OpenStreetMap data.</p>
      <h2>Sources</h2>
      <p>Every source, with its licence and retrieval date, is on <Link to="/method">How it decides</Link>.</p>
    </article>
  )
}
