import { useState } from 'react'
import { api, MODE } from '../api/client'
import type { FacilityRecord } from '../api/types'
import { SampleBadge } from './ui'

/** Fixture mode only: the reply composed in the browser. Live, the API's own SMS route answers. */
export function smsReply(r: FacilityRecord): string {
  const f = r.facility
  const name = f.name.length > 28 ? f.name.slice(0, 27) + '.' : f.name
  const code = f.code ?? f.id
  if (r.refused || !r.brief_metric) return `${code} ${name}\nNo supply figure: no feeder evidence.${MODE === 'fixture' ? '\nSAMPLE DATA' : ''}`
  const b = r.brief_metric
  const fix = r.fix ? { pqs_icelined: 'PQS ice-lined fridge', pqs_sdd: 'PQS solar fridge', solar_clinic: 'PQS solar fridge + clinic system' }[r.fix.category] : 'see sheet'
  return `${code} ${name}\nFridge 2-8C: ${Math.round(b.uptime_today.p * 100)}% of days now, ${Math.round(b.uptime_with_system.p * 100)}% with fix\nFix: ${fix}${MODE === 'fixture' ? '\nSAMPLE DATA' : ''}`
}

const MAX = 5 // facility codes run to 61,009

export function FeaturePhone({ defaultCode = '' }: { defaultCode?: string }) {
  const [code, setCode] = useState(defaultCode.slice(0, MAX))
  const [screen, setScreen] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const press = (k: string) => { setScreen(null); setCode((c) => (c + k).replace(/\D/g, '').slice(0, MAX)) }
  const send = async () => {
    const digits = code.replace(/\D/g, '')
    if (!digits) { setScreen('Enter a facility code, 1 to 5 digits'); return }
    setBusy(true)
    try {
      if (MODE === 'live') setScreen((await api.sms(digits))?.reply ?? 'No reply')
      else setScreen(smsReply(await api.facility(`WL-${digits.padStart(4, '0').slice(-4)}`)))
    } catch { setScreen(`${digits}: not found.\nCheck the code on the facility sheet.`) }
    setBusy(false)
  }
  const len = screen?.length ?? 0
  return (
    <div className="card stack">
      <div className="row between"><h3 style={{ margin: 0 }}>SMS lookup</h3><span className="tag s-sun">Sandbox demo</span></div>
      <p className="small muted" style={{ margin: 0 }}>
        A clinic officer with a basic phone sends a facility code and gets the fridge figure back.
        {MODE === 'live' ? ' This panel calls the same SMS route Africa\'s Talking calls; in the sandbox the reply comes back here and no SMS is sent.' : ' This panel composes the reply in the browser from sample data.'}
      </p>
      <div className="phone" aria-label="Feature phone simulator">
        <div className="screen" role="log" aria-live="polite" aria-label="Phone screen">
          <div className="bar"><span>WARDLIGHT</span><span>sandbox</span></div>
          {busy ? 'Sending…' : screen ?? `Send facility code:\n> ${code}_`}
        </div>
        <div className="keys">
          {['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'].map((k) => (
            <button key={k} type="button" onClick={() => press(k)} aria-label={`Key ${k}`}>{k}</button>
          ))}
          <div className="wide">
            <button type="button" className="clr" onClick={() => { setScreen(null); setCode('') }}>CLR</button>
            <button type="button" onClick={() => { setScreen(null); setCode((c) => c.slice(0, -1)) }} aria-label="Delete last digit">DEL</button>
            <button type="button" className="send" onClick={send}>SEND</button>
          </div>
        </div>
      </div>
      <label className="field small">Or type a code (up to 5 digits)
        <input type="text" inputMode="numeric" value={code} onChange={(e) => { setScreen(null); setCode(e.target.value.replace(/\D/g, '').slice(0, MAX)) }} onKeyDown={(e) => { if (e.key === 'Enter') send() }} aria-describedby="sms-help" />
      </label>
      <p id="sms-help" className="small muted" style={{ margin: 0 }}>
        {screen ? <>Reply: <span className="mono">{len}</span> characters, {len <= 160 ? 'one SMS' : `${Math.ceil(len / 153)} SMS parts`}. </> : null}{MODE === 'fixture' && <SampleBadge />}
      </p>
    </div>
  )
}
