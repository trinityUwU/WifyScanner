import { useState, useEffect, useCallback } from 'react'

const API = '/api'
const POLL_MS = 2_000

// ─── Types ────────────────────────────────────────────────────────────────────

interface TpvData {
  mode: number
  time: string | null
  lat: number | null
  lon: number | null
  altHAE: number | null
  altMSL: number | null
  speed: number | null
  track: number | null
  climb: number | null
  epx: number | null
  epy: number | null
  epv: number | null
  eph: number | null
  sep: number | null
  leapseconds: number | null
}

interface SkyData {
  nSat: number | null
  uSat: number | null
  hdop: number | null
  vdop: number | null
  pdop: number | null
  tdop: number | null
  xdop: number | null
  ydop: number | null
  gdop: number | null
}

interface Satellite {
  constellation: string
  prn: number | null
  el: number | null
  az: number | null
  ss: number | null
  used: boolean
}

interface GpsLive {
  tpv: TpvData | null
  sky: SkyData | null
  satellites: Satellite[]
  error: string | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, decimals = 1, unit = ''): string {
  if (v == null) return '—'
  return `${v.toFixed(decimals)}${unit ? ' ' + unit : ''}`
}

function fmtLatLng(v: number | null | undefined, pos: string, neg: string): string {
  if (v == null) return '—'
  const dir = v >= 0 ? pos : neg
  return `${Math.abs(v).toFixed(8)} ${dir}`
}

function modeLabel(mode: number | null | undefined): { text: string; color: string } {
  if (mode === 3) return { text: '3D FIX', color: 'var(--green)' }
  if (mode === 2) return { text: '2D FIX', color: 'var(--amber)' }
  return { text: 'NO FIX', color: 'var(--red)' }
}

function snrColor(ss: number | null): string {
  if (ss == null || ss === 0) return 'var(--text-muted)'
  if (ss >= 30) return 'var(--green)'
  if (ss >= 20) return 'var(--amber)'
  return 'var(--red)'
}

function SnrBar({ ss }: { ss: number | null }) {
  const pct = ss == null ? 0 : Math.min(100, (ss / 45) * 100)
  return (
    <span className="gps-snr-bar" title={ss != null ? `${ss} dBHz` : '—'}>
      <span className="gps-snr-fill" style={{ width: `${pct}%`, background: snrColor(ss) }} />
    </span>
  )
}

// ─── Composants ───────────────────────────────────────────────────────────────

function InfoRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <li className="gps-kv-row">
      <span className="gps-kv-label">{label}</span>
      <span className={`gps-kv-value${mono ? ' gps-mono' : ''}`}>{value}</span>
    </li>
  )
}

function TpvPanel({ tpv, sky }: { tpv: TpvData | null; sky: SkyData | null }) {
  const mode = modeLabel(tpv?.mode)

  return (
    <div className="gps-panel">
      <div className="gps-panel-title">
        Position
        <span className="gps-badge" style={{ color: mode.color, borderColor: mode.color }}>
          {mode.text}
        </span>
        {sky && (
          <span className="gps-badge gps-badge--sats">
            {sky.uSat ?? '?'}/{sky.nSat ?? '?'} sat
          </span>
        )}
      </div>

      <ul className="gps-kv">
        <InfoRow label="Latitude"  value={fmtLatLng(tpv?.lat, 'N', 'S')} mono />
        <InfoRow label="Longitude" value={fmtLatLng(tpv?.lon, 'E', 'W')} mono />
        <InfoRow label="Alt (HAE / MSL)" value={
          tpv?.altHAE != null && tpv?.altMSL != null
            ? `${tpv.altHAE.toFixed(3)} / ${tpv.altMSL.toFixed(3)} m`
            : '—'
        } mono />
        <InfoRow label="Vitesse"   value={fmt(tpv?.speed != null ? tpv.speed * 3.6 : null, 2, 'km/h')} mono />
        <InfoRow label="Cap (vrai)" value={fmt(tpv?.track, 1, '°')} mono />
        <InfoRow label="Montée"    value={fmt(tpv?.climb != null ? tpv.climb * 60 : null, 2, 'm/min')} mono />
        <InfoRow label="Heure UTC" value={tpv?.time ?? '—'} mono />
      </ul>

      <div className="gps-panel-title gps-panel-title--sub">Précision</div>
      <ul className="gps-kv">
        <InfoRow label="Long (XDOP / EPX)" value={
          `${fmt(sky?.xdop, 2)} / ±${fmt(tpv?.epx, 1)} m`
        } mono />
        <InfoRow label="Lat  (YDOP / EPY)" value={
          `${fmt(sky?.ydop, 2)} / ±${fmt(tpv?.epy, 1)} m`
        } mono />
        <InfoRow label="Alt  (VDOP / EPV)" value={
          `${fmt(sky?.vdop, 2)} / ±${fmt(tpv?.epv, 1)} m`
        } mono />
        <InfoRow label="2D   (HDOP / CEP)" value={
          `${fmt(sky?.hdop, 2)} / ±${fmt(tpv?.eph, 1)} m`
        } mono />
        <InfoRow label="3D   (PDOP / SEP)" value={
          `${fmt(sky?.pdop, 2)} / ±${fmt(tpv?.sep, 1)} m`
        } mono />
        <InfoRow label="Temps (TDOP)"      value={fmt(sky?.tdop, 2)} mono />
        <InfoRow label="Géo   (GDOP)"      value={fmt(sky?.gdop, 2)} mono />
      </ul>
    </div>
  )
}

function SatPanel({ satellites, sky }: { satellites: Satellite[]; sky: SkyData | null }) {
  return (
    <div className="gps-panel">
      <div className="gps-panel-title">
        Satellites
        {sky && (
          <span className="gps-badge gps-badge--sats">
            Visible {sky.nSat ?? '?'} / Utilisé {sky.uSat ?? '?'}
          </span>
        )}
      </div>
      {satellites.length === 0 ? (
        <p className="gps-empty">Aucune donnée satellite</p>
      ) : (
        <table className="gps-sat-table">
          <thead>
            <tr>
              <th>Sys</th>
              <th>PRN</th>
              <th>Elév</th>
              <th>Azim</th>
              <th title="Signal strength (dBHz)">SNR</th>
              <th></th>
              <th>Utilisé</th>
            </tr>
          </thead>
          <tbody>
            {satellites.map((s, i) => (
              <tr key={i} className={s.used ? 'gps-sat--used' : 'gps-sat--idle'}>
                <td className="gps-mono">{s.constellation}</td>
                <td className="gps-mono">{s.prn ?? '—'}</td>
                <td className="gps-mono">{fmt(s.el, 1, '°')}</td>
                <td className="gps-mono">{fmt(s.az, 1, '°')}</td>
                <td className="gps-mono" style={{ color: snrColor(s.ss) }}>
                  {fmt(s.ss, 1)}
                </td>
                <td><SnrBar ss={s.ss} /></td>
                <td style={{ textAlign: 'center', color: s.used ? 'var(--green)' : 'var(--text-muted)' }}>
                  {s.used ? '●' : '○'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ─── Vue principale ───────────────────────────────────────────────────────────

export default function GpsView() {
  const [data, setData] = useState<GpsLive | null>(null)
  const [lastOk, setLastOk] = useState<string | null>(null)
  const [stale, setStale] = useState(false)

  const poll = useCallback(async () => {
    try {
      const res = await fetch(`${API}/control/gps/live`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: GpsLive = await res.json()
      setData(json)
      setStale(false)
      if (json.tpv?.time) setLastOk(json.tpv.time)
    } catch {
      setStale(true)
    }
  }, [])

  useEffect(() => {
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => clearInterval(id)
  }, [poll])

  return (
    <div className="gps-view">
      <div className="gps-header">
        <span className="gps-header-title">GPS Live</span>
        <span
          className="gps-header-dot"
          style={{ background: stale ? 'var(--red)' : data?.tpv ? 'var(--green)' : 'var(--amber)' }}
          title={stale ? 'API injoignable' : data?.error ? data.error : 'OK'}
        />
        {lastOk && (
          <span className="gps-header-time">{new Date(lastOk).toLocaleTimeString()}</span>
        )}
        {data?.error && (
          <span className="gps-header-err">{data.error}</span>
        )}
      </div>

      {!data && !stale && (
        <div className="gps-loading">Chargement…</div>
      )}
      {stale && !data && (
        <div className="gps-loading gps-loading--err">API injoignable</div>
      )}

      {data && (
        <div className="gps-panels">
          <TpvPanel tpv={data.tpv} sky={data.sky} />
          <SatPanel satellites={data.satellites} sky={data.sky} />
        </div>
      )}
    </div>
  )
}
