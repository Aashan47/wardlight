import { MODE } from '../api/client'
import { Link } from '../router'

export function About() {
  return (
    <article style={{ maxWidth: 820 }}>
      <p className="kicker">About</p>
      <h1>Wardlight</h1>
      <p>
        Built by Aashan Javed, working solo as team <strong>Two to Eight</strong>, from Pakistan, for the IAS Global Energy Hackathon 2026, brief 13,
        “Power for a city the grid can't protect”, focus city Maiduguri, Borno State, in the Digital Solutions and AI track.
      </p>
      <h2>The problem</h2>
      <p>
        Maiduguri's hospitals, water pumps and markets depend on one long 330 kV line through insurgent-affected territory. When it is cut, repairs take weeks under escort,
        and critical services fall back on diesel at prices that nearly doubled in a year. Wardlight asks the brief's first question for every critical site in the city:
        if the line goes down for two months, what keeps running, and what would keep the rest running without diesel?
      </p>
      <h2>Who it is for</h2>
      <p>
        The funder, the state government or the distribution company deciding which critical sites get on-site solar and storage first with a fixed budget.
        The Funder plan turns a naira budget into a costed, ranked list of sites; the planner agent does the same from a plain question and shows every step.
        And the people at each site: the officer in charge, the borehole committee, the market association, who can confirm by SMS what the model can only assume.
      </p>
      <p>
        {MODE === 'fixture'
          ? 'This build is running on sample fixtures: facility numbers are synthetic placeholders and are labelled as such on every screen.'
          : 'This build is connected to the live API. Recorded agent sessions are labelled as recorded; the scripted planner says when no language model was called.'}
      </p>
      <h2>Open source</h2>
      <p>React, three.js, MapLibre GL JS, Vite and Workbox; IBM Plex Sans and Mono (SIL Open Font License). Basemap by OpenFreeMap from OpenStreetMap data.</p>
      <h2>Sources</h2>
      <p>Every source, with its licence and retrieval date, is on <Link to="/method">How it decides</Link>.</p>
    </article>
  )
}
