import { useCallback, useEffect, useState } from 'react'

const API = '/api'

interface Status {
  project_root: string
  db_path: string
  venv_python: string
  venv_ready: boolean
  frontend_node_modules: boolean
  collector: { running: boolean; pid: number | null }
  gpsd_active: boolean | null
  sudo_collector: boolean
  control_token_set: boolean
}

interface Preflight {
  missing_commands: string[]
  hints: string[]
  interfaces: { name: string; type?: string; mode?: string; addr?: string }[]
}

interface TaskResult {
  ok?: boolean
  returncode?: number
  output?: string
  step?: string
  detail?: string
}

interface GpsStatus {
  serial_devices: string[]
  etc_default_gpsd_devices_line: string | null
  devices_config_empty: boolean
  gpsd_active: boolean | null
  tpv_sample: { mode: number; lat: number | null; lon: number | null } | null
  fix_ok: boolean
  gpspipe_error: string | null
  configure_gpsd_command: string | null
  hints?: string[]
}

const TOKEN_KEY = 'cyberalpha_control_token'

function authHeaders(): HeadersInit {
  const t = localStorage.getItem(TOKEN_KEY)?.trim()
  if (!t) return {}
  return { Authorization: `Bearer ${t}` }
}

export default function ControlPanel() {
  const [status, setStatus] = useState<Status | null>(null)
  const [preflight, setPreflight] = useState<Preflight | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [iface, setIface] = useState('')
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) ?? '')
  const [busy, setBusy] = useState<string | null>(null)
  const [lastTask, setLastTask] = useState<TaskResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [gpsStatus, setGpsStatus] = useState<GpsStatus | null>(null)
  const [gpsLoading, setGpsLoading] = useState(false)

  const saveToken = () => {
    if (token.trim()) localStorage.setItem(TOKEN_KEY, token.trim())
    else localStorage.removeItem(TOKEN_KEY)
  }

  const refresh = useCallback(async () => {
    setErr(null)
    try {
      const [s, p, l] = await Promise.all([
        fetch(`${API}/control/status`).then(r => (r.ok ? r.json() : Promise.reject(new Error(`status ${r.status}`)))),
        fetch(`${API}/control/preflight`).then(r => (r.ok ? r.json() : Promise.reject(new Error(`preflight ${r.status}`)))),
        fetch(`${API}/control/collector/logs?tail=300`).then(r => (r.ok ? r.json() : { lines: [] })),
      ])
      setStatus(s as Status)
      setPreflight(p as Preflight)
      setLogs((l as { lines: string[] }).lines ?? [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erreur réseau')
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, status?.collector.running ? 2000 : 5000)
    return () => clearInterval(id)
  }, [refresh, status?.collector.running])

  const postTask = async (path: string, label: string) => {
    setBusy(label)
    setLastTask(null)
    setErr(null)
    saveToken()
    try {
      const r = await fetch(`${API}${path}`, { method: 'POST', headers: { ...authHeaders() } })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setErr(typeof data.detail === 'string' ? data.detail : r.statusText)
        setLastTask(data)
        return
      }
      setLastTask(data)
      await refresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setBusy(null)
    }
  }

  const startCollector = async () => {
    if (!iface.trim()) {
      setErr('Indiquez une interface monitor (ex. wlan0mon)')
      return
    }
    setBusy('Démarrage collecteur')
    setErr(null)
    saveToken()
    try {
      const r = await fetch(`${API}/control/collector/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ interface: iface.trim() }),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setErr(typeof data.detail === 'string' ? data.detail : r.statusText)
        return
      }
      await refresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setBusy(null)
    }
  }

  const stopCollector = () => postTask('/control/collector/stop', 'Arrêt collecteur')

  const fetchGpsStatus = async () => {
    setGpsLoading(true)
    setErr(null)
    try {
      const r = await fetch(`${API}/control/gps/status`)
      if (!r.ok) throw new Error(`gps/status ${r.status}`)
      setGpsStatus(await r.json() as GpsStatus)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Erreur GPS')
    } finally {
      setGpsLoading(false)
    }
  }

  const clearLogs = async () => {
    setBusy('Effacement logs')
    saveToken()
    try {
      await fetch(`${API}/control/collector/logs/clear`, { method: 'POST', headers: { ...authHeaders() } })
      await refresh()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="control-panel">
      <header className="control-header">
        <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--blue)' }}>Contrôle</h1>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.45 }}>
          Installe les dépendances <strong>projet</strong> (pip / npm), vérifie le système et pilote le collecteur.
          Les paquets système (<code>pacman</code>, gpsd, noyau) restent à installer sur la machine (voir README).
        </p>
      </header>

      {err && (
        <div className="control-banner control-banner--err">{err}</div>
      )}

      {status && (
        <section className="control-section">
          <h2>État</h2>
          <ul className="control-kv">
            <li><span>venv Python</span><span>{status.venv_ready ? '✓' : '✗'}</span></li>
            <li><span>node_modules</span><span>{status.frontend_node_modules ? '✓' : '✗'}</span></li>
            <li><span>gpsd (systemd)</span><span>{status.gpsd_active === null ? '?' : status.gpsd_active ? 'actif' : 'inactif'}</span></li>
            <li><span>Collecteur</span><span>{status.collector.running ? `PID ${status.collector.pid}` : 'arrêté'}</span></li>
            <li><span>sudo collecteur</span><span>{status.sudo_collector ? 'oui (CYBERALPHA_SUDO_COLLECTOR)' : 'non'}</span></li>
            <li><span>Jeton POST</span><span>{status.control_token_set ? 'requis' : 'désactivé'}</span></li>
          </ul>
        </section>
      )}

      {(status?.control_token_set || preflight?.missing_commands.length) && (
        <section className="control-section">
          <h2>Accès API</h2>
          {status?.control_token_set && (
            <label className="control-label">
              Jeton (Bearer) pour les actions POST
              <input
                type="password"
                className="search-input"
                style={{ marginTop: 6 }}
                value={token}
                onChange={e => setToken(e.target.value)}
                placeholder="CYBERALPHA_CONTROL_TOKEN"
              />
            </label>
          )}
          {preflight && preflight.missing_commands.length > 0 && (
            <div className="control-banner control-banner--warn" style={{ marginTop: 10 }}>
              Commandes manquantes : {preflight.missing_commands.join(', ')}
              {preflight.hints.map(h => (
                <div key={h} style={{ marginTop: 6, fontSize: 11 }}>{h}</div>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="control-section">
        <h2>Clé GPS (gpsd)</h2>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          Vérifie les ports USB série, la ligne <code>DEVICES</code> dans <code>/etc/default/gpsd</code> (Arch), et un échantillon de position via <code>gpspipe</code>.
        </p>
        <div className="control-actions">
          <button type="button" className="sort-btn active" disabled={gpsLoading} onClick={fetchGpsStatus}>
            {gpsLoading ? 'Analyse…' : 'Analyser le GPS'}
          </button>
        </div>
        {gpsStatus && (
          <div style={{ marginTop: 12, fontSize: 12 }}>
            <ul className="control-kv" style={{ marginBottom: 10 }}>
              <li><span>Ports série</span><span>{gpsStatus.serial_devices.length ? gpsStatus.serial_devices.join(', ') : '—'}</span></li>
              <li><span>gpsd (systemd)</span><span>{gpsStatus.gpsd_active === null ? '?' : gpsStatus.gpsd_active ? 'actif' : 'inactif'}</span></li>
              <li><span>DEVICES vide ?</span><span>{gpsStatus.devices_config_empty ? 'oui (à corriger)' : 'non'}</span></li>
              <li><span>Fix position</span><span style={{ color: gpsStatus.fix_ok ? 'var(--green)' : 'var(--amber)' }}>{gpsStatus.fix_ok ? 'oui (mode ≥2)' : 'non encore'}</span></li>
            </ul>
            {gpsStatus.etc_default_gpsd_devices_line && (
              <pre className="control-pre" style={{ maxHeight: 80 }}>{gpsStatus.etc_default_gpsd_devices_line}</pre>
            )}
            {gpsStatus.tpv_sample && (
              <pre className="control-pre" style={{ maxHeight: 100 }}>
                {JSON.stringify(gpsStatus.tpv_sample, null, 0)}
              </pre>
            )}
            {gpsStatus.gpspipe_error && (
              <div className="control-banner control-banner--warn">{gpsStatus.gpspipe_error}</div>
            )}
            {gpsStatus.hints && gpsStatus.hints.length > 0 && (
              <ul style={{ marginTop: 10, paddingLeft: 18, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {gpsStatus.hints.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            )}
            {gpsStatus.configure_gpsd_command && gpsStatus.devices_config_empty && (
              <p style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: 11 }}>
                Dans un terminal :{' '}
                <code style={{ wordBreak: 'break-all', color: 'var(--blue)' }}>{gpsStatus.configure_gpsd_command}</code>
              </p>
            )}
          </div>
        )}
      </section>

      <section className="control-section">
        <h2>Dépendances projet</h2>
        <div className="control-actions">
          <button type="button" className="sort-btn active" disabled={!!busy} onClick={() => postTask('/control/tasks/python-deps', 'pip')}>
            {busy === 'pip' ? '…' : 'Installer Python (pip)'}
          </button>
          <button type="button" className="sort-btn active" disabled={!!busy} onClick={() => postTask('/control/tasks/frontend-deps', 'npm')}>
            {busy === 'npm' ? '…' : 'Installer frontend (npm)'}
          </button>
        </div>
        {lastTask?.output != null && (
          <pre className="control-pre">{lastTask.output}</pre>
        )}
      </section>

      <section className="control-section">
        <h2>Interfaces sans fil</h2>
        {preflight && preflight.interfaces.length > 0 ? (
          <ul className="control-ifaces">
            {preflight.interfaces.map(i => (
              <li key={i.name}>
                <button type="button" className="iface-pill" onClick={() => setIface(i.name)}>
                  {i.name}
                </button>
                <span className="iface-meta">{i.type || '—'}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>Aucune interface (iw dev) ou erreur.</p>
        )}
      </section>

      <section className="control-section">
        <h2>Collecteur WiFi</h2>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          Passez l’interface en <strong>mode monitor</strong> avant (airmon-ng ou iw). Le collecteur nécessite un <strong>fix GPS</strong>.
        </p>
        <label className="control-label">
          Interface monitor
          <input
            className="search-input"
            style={{ marginTop: 6 }}
            value={iface}
            onChange={e => setIface(e.target.value)}
            placeholder="wlan0mon"
          />
        </label>
        <div className="control-actions" style={{ marginTop: 10 }}>
          <button type="button" className="sort-btn active" disabled={!!busy || status?.collector.running} onClick={startCollector}>
            Démarrer
          </button>
          <button type="button" className="sort-btn" disabled={!!busy || !status?.collector.running} onClick={stopCollector}>
            Arrêter
          </button>
          <button type="button" className="sort-btn" disabled={!!busy} onClick={clearLogs}>
            Vider les logs
          </button>
        </div>
      </section>

      <section className="control-section control-section--grow">
        <h2>Journaux collecteur</h2>
        <pre className="control-log">{logs.join('\n') || '—'}</pre>
      </section>
    </div>
  )
}
