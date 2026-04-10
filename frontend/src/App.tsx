import { useState, useEffect, useCallback, useRef } from 'react'
import { MapContainer, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'
import ControlPanel from './ControlPanel'
import GpsView from './GpsView'
import './App.css'

const API = '/api'
const POLL_SLOW = 10_000
const POLL_LIVE = 3_000

/** Dev : Carto (CDN). Build prod / Pi : tuiles PNG locales via l’API — fonctionne sans Internet (hotspot). */
const MAP_TILE_URL = import.meta.env.DEV
  ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
  : `${API}/tiles/{z}/{x}/{y}.png`
const MAP_ATTRIBUTION = import.meta.env.DEV
  ? '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
  : 'Fond carte local (sans Internet)'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Network {
  ssid: string
  bssid: string
  samples: number
  avg_rssi: number
  max_rssi: number
  min_rssi: number
  channel: number | null
  encryption: string
  last_seen: number
}

interface Stats {
  total_points: number
  unique_networks: number
  bounds: { min_lat: number; max_lat: number; min_lng: number; max_lng: number } | null
}

type HeatPoint = [number, number, number] // lat, lng, intensity

interface ApLocation {
  bssid: string
  ssid: string
  encryption: string
  lat: number
  lng: number
  method: string
  points_used: number
  best_rssi: number
  confidence: number
  centroid_lat?: number
  centroid_lng?: number
  /** Présent si la trilatération a été évitée ou rejetée (GPS / modèle RSSI). */
  trilat_skipped?: string
  sample_spread_m?: number
}

// ─── AP Location Markers ──────────────────────────────────────────────────────

function encryptionColor(enc: string): string {
  if (enc === 'OPEN') return '#ff4d6a'
  if (enc.includes('WPA2')) return '#00d88a'
  return '#f0a030'
}

function ApMarkersLayer({ locations, selectedBssid }: {
  locations: ApLocation[]
  selectedBssid: string | null
}) {
  const map = useMap()
  const layerRef = useRef<L.LayerGroup | null>(null)

  useEffect(() => {
    if (layerRef.current) {
      layerRef.current.clearLayers()
    } else {
      layerRef.current = L.layerGroup().addTo(map)
    }

    locations.forEach(ap => {
      const isSelected = ap.bssid === selectedBssid
      const color = encryptionColor(ap.encryption)
      const size = isSelected ? 14 : 10
      const opacity = isSelected ? 1 : 0.75

      const icon = L.divIcon({
        className: '',
        html: `<div style="
          width:${size}px;height:${size}px;
          border-radius:50%;
          background:${color};
          border:${isSelected ? '3px solid white' : '2px solid rgba(255,255,255,0.5)'};
          box-shadow:0 0 ${isSelected ? '10px' : '4px'} ${color};
          opacity:${opacity};
          transform:translate(-50%,-50%);
        "></div>`,
        iconAnchor: [0, 0],
      })

      const confStr = `${Math.round(ap.confidence * 100)}%`
      const spreadLine = ap.sample_spread_m != null
        ? `Étendue échantillons : ~${ap.sample_spread_m} m<br/>`
        : ''
      const skipLine = ap.trilat_skipped
        ? `<span style="color:#888">Trilat. : ${ap.trilat_skipped}</span><br/>`
        : ''
      const popup = `
        <div style="font-family:monospace;font-size:12px;min-width:200px">
          <b style="color:${color}">${ap.ssid || '<hidden>'}</b><br/>
          <span style="color:#999">${ap.bssid}</span><br/>
          <span style="color:#ccc">${ap.encryption}</span><br/>
          <br/>
          <b>Position estimée</b><br/>
          ${ap.lat.toFixed(6)}, ${ap.lng.toFixed(6)}<br/>
          Méthode : ${ap.method}<br/>
          RSSI max : ${ap.best_rssi} dBm<br/>
          Points distincts : ${ap.points_used}<br/>
          Confiance : ${confStr}<br/>
          ${spreadLine}${skipLine}
        </div>
      `

      L.marker([ap.lat, ap.lng], { icon })
        .bindPopup(popup)
        .addTo(layerRef.current!)
    })

    return () => {
      layerRef.current?.clearLayers()
    }
  }, [locations, selectedBssid, map])

  return null
}

// ─── Locate Me Button ─────────────────────────────────────────────────────────

type LocateState = 'idle' | 'loading' | 'active' | 'error'

function LocateButton() {
  const map = useMap()
  const markerRef = useRef<L.CircleMarker | null>(null)
  const circleRef = useRef<L.Circle | null>(null)
  const watchRef = useRef<number | null>(null)
  const [state, setState] = useState<LocateState>('idle')

  const stop = () => {
    if (watchRef.current !== null) {
      navigator.geolocation.clearWatch(watchRef.current)
      watchRef.current = null
    }
    markerRef.current?.remove(); markerRef.current = null
    circleRef.current?.remove(); circleRef.current = null
  }

  const updateMarker = useCallback((pos: GeolocationPosition) => {
    const { latitude: lat, longitude: lng, accuracy } = pos.coords
    setState('active')

    if (!markerRef.current) {
      markerRef.current = L.circleMarker([lat, lng], {
        radius: 8, color: '#fff', fillColor: '#4a9eff', fillOpacity: 1, weight: 2,
      }).addTo(map)
    } else {
      markerRef.current.setLatLng([lat, lng])
    }

    if (!circleRef.current) {
      circleRef.current = L.circle([lat, lng], {
        radius: accuracy, color: '#4a9eff', fillColor: '#4a9eff', fillOpacity: 0.08, weight: 1,
      }).addTo(map)
    } else {
      circleRef.current.setLatLng([lat, lng]).setRadius(accuracy)
    }
  }, [map])

  const onClick = () => {
    if (state === 'active' || state === 'error') {
      stop()
      setState('idle')
      return
    }
    if (!navigator.geolocation) {
      setState('error')
      return
    }
    setState('loading')
    navigator.geolocation.getCurrentPosition(
      pos => {
        updateMarker(pos)
        map.flyTo([pos.coords.latitude, pos.coords.longitude], Math.max(map.getZoom(), 17), {
          duration: 1.2,
        })
        watchRef.current = navigator.geolocation.watchPosition(updateMarker, () => {}, {
          enableHighAccuracy: true, maximumAge: 2000,
        })
      },
      () => setState('error'),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  useEffect(() => () => stop(), [])

  const icon  = state === 'idle' ? '◎' : state === 'loading' ? '…' : state === 'active' ? '◉' : '✕'
  const color = state === 'idle' ? 'var(--text)' : state === 'loading' ? 'var(--text-muted)' : state === 'active' ? 'var(--blue)' : 'var(--red)'
  const title = state === 'idle' ? 'Me localiser' : state === 'loading' ? 'Localisation…' : state === 'active' ? 'Arrêter la localisation' : 'Erreur GPS — cliquer pour réessayer'

  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="map-btn map-btn--locate"
      style={{ color }}
    >
      {icon}
    </button>
  )
}

// ─── Heatmap Layer ────────────────────────────────────────────────────────────

interface HeatmapLayerProps {
  bssid: string | null
  bounds: Stats['bounds']
  pollInterval: number
  /** Si faux, la carte ne se recentre plus sur les données (évite le « focus » permanent au re-poll). */
  autoFitData: boolean
}

type HeatLayerFactory = (points: HeatPoint[], opts: object) => L.Layer

/** Enregistré dans main.tsx via leaflet-heat-setup + import leaflet.heat (même L que react-leaflet). */
function heatLayer(points: HeatPoint[], opts: object): L.Layer {
  const fn = (L as unknown as { heatLayer?: HeatLayerFactory }).heatLayer
  if (typeof fn !== 'function') {
    throw new Error('leaflet.heat non chargé : vérifier main.tsx (imports leaflet-heat-setup puis leaflet-heat)')
  }
  return fn(points, opts)
}

function HeatmapLayer({ bssid, bounds, pollInterval, autoFitData }: HeatmapLayerProps) {
  const map = useMap()
  /** Dernière combinaison (filtre) pour laquelle on a fait un fitBounds — pas à chaque poll ni chaque bounds. */
  const lastFitKeyRef = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (!autoFitData) lastFitKeyRef.current = undefined
  }, [autoFitData])

  const loadHeatmap = useCallback(async () => {
    const url = bssid ? `${API}/heatmap?bssid=${encodeURIComponent(bssid)}` : `${API}/heatmap`
    const data: HeatPoint[] = await fetch(url).then(r => r.json())

    // Retirer l'ancienne couche heatmap
    map.eachLayer(layer => {
      if ((layer as any)._isHeatLayer) map.removeLayer(layer)
    })

    if (data.length === 0) return

    const heat = heatLayer(data, {
      radius: 35,
      blur: 25,
      maxZoom: 18,
      max: 1.0,
      gradient: {
        0.0: '#0000ff',
        0.3: '#00aaff',
        0.5: '#00d88a',
        0.7: '#f0a030',
        1.0: '#ff4d6a',
      },
    }) as unknown as L.Layer & { _isHeatLayer: boolean }
    heat._isHeatLayer = true
    heat.addTo(map)
  }, [bssid, map])

  useEffect(() => {
    loadHeatmap()
    const interval = setInterval(loadHeatmap, pollInterval)
    return () => clearInterval(interval)
  }, [loadHeatmap, pollInterval])

  // Centrage sur les données : uniquement quand autoFitData est actif et à chaque changement de filtre (pas à chaque rafraîchissement des stats).
  useEffect(() => {
    if (!autoFitData || !bounds) return
    const key = bssid ?? '__all__'
    if (lastFitKeyRef.current === key) return
    lastFitKeyRef.current = key
    map.fitBounds(
      [
        [bounds.min_lat, bounds.min_lng],
        [bounds.max_lat, bounds.max_lng],
      ],
      { padding: [40, 40] },
    )
  }, [autoFitData, bssid, bounds, map])

  return null
}

// ─── Composants UI ────────────────────────────────────────────────────────────

function rssiColor(rssi: number): string {
  if (rssi >= -55) return 'var(--green)'
  if (rssi >= -70) return 'var(--amber)'
  return 'var(--red)'
}

function rssiLabel(rssi: number): string {
  if (rssi >= -55) return 'Excellent'
  if (rssi >= -65) return 'Bon'
  if (rssi >= -75) return 'Moyen'
  return 'Faible'
}

function encryptionBadge(enc: string) {
  const color =
    enc === 'OPEN' ? 'var(--red)' :
    enc.includes('WPA2') ? 'var(--green)' :
    'var(--amber)'
  return (
    <span style={{
      fontSize: 10,
      padding: '1px 5px',
      borderRadius: 3,
      border: `1px solid ${color}`,
      color,
      fontFamily: 'JetBrains Mono, monospace',
    }}>
      {enc}
    </span>
  )
}

function NetworkCard({
  network,
  selected,
  onClick,
}: {
  network: Network
  selected: boolean
  onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '10px 12px',
        marginBottom: 4,
        borderRadius: 8,
        cursor: 'pointer',
        background: selected ? 'var(--bg-surface)' : 'transparent',
        border: `1px solid ${selected ? 'var(--blue)' : 'var(--border)'}`,
        transition: 'border-color 0.15s, background 0.15s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13, wordBreak: 'break-all' }}>
          {network.ssid}
        </span>
        {encryptionBadge(network.encryption)}
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, fontFamily: 'JetBrains Mono, monospace', marginTop: 2 }}>
        {network.bssid}
      </div>
      <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 12 }}>
        <span style={{ color: rssiColor(network.avg_rssi) }}>
          ⌀ {network.avg_rssi} dBm
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          {network.samples} pts
        </span>
        {network.channel && (
          <span style={{ color: 'var(--text-muted)' }}>
            Ch {network.channel}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [view, setView] = useState<'heatmap' | 'control' | 'gps'>('heatmap')
  const [liveHeatmap, setLiveHeatmap] = useState(true)
  /** Recentrer la carte sur l’emprise des données seulement au changement de filtre (pas en boucle). */
  const [autoFitDataBounds, setAutoFitDataBounds] = useState(true)
  const [showApMarkers, setShowApMarkers] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [networks, setNetworks] = useState<Network[]>([])
  const [stats, setStats] = useState<Stats>({ total_points: 0, unique_networks: 0, bounds: null })
  const [apLocations, setApLocations] = useState<ApLocation[]>([])
  const [selectedBssid, setSelectedBssid] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'samples' | 'rssi'>('samples')

  const pollMs = view === 'heatmap' && liveHeatmap ? POLL_LIVE : POLL_SLOW

  const fetchData = useCallback(async () => {
    const [nets, st, locs] = await Promise.all([
      fetch(`${API}/networks`).then(r => r.json()),
      fetch(`${API}/stats`).then(r => r.json()),
      fetch(`${API}/networks/locate?min_points=3`).then(r => r.ok ? r.json() : []),
    ])
    setNetworks(nets)
    setStats(st)
    setApLocations(locs as ApLocation[])
  }, [])

  useEffect(() => {
    if (view !== 'heatmap') return
    fetchData()
    const interval = setInterval(fetchData, pollMs)
    return () => clearInterval(interval)
  }, [fetchData, pollMs, view])

  const filtered = networks
    .filter(n =>
      n.ssid.toLowerCase().includes(search.toLowerCase()) ||
      n.bssid.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) =>
      sortBy === 'samples' ? b.samples - a.samples : b.avg_rssi - a.avg_rssi
    )

  const selectedNetwork = networks.find(n => n.bssid === selectedBssid)

  const navBar = (active: 'heatmap' | 'control' | 'gps') => (
    <nav className="app-nav">
      <button type="button" className={`nav-tab${active === 'heatmap'  ? ' nav-tab--active' : ''}`} onClick={() => setView('heatmap')}>Heatmap</button>
      <button type="button" className={`nav-tab${active === 'gps'     ? ' nav-tab--active' : ''}`} onClick={() => setView('gps')}>GPS</button>
      <button type="button" className={`nav-tab${active === 'control' ? ' nav-tab--active' : ''}`} onClick={() => setView('control')}>Contrôle</button>
    </nav>
  )

  if (view === 'control') {
    return (
      <div className="app-shell">
        {navBar('control')}
        <div className="control-scroll">
          <ControlPanel />
        </div>
      </div>
    )
  }

  if (view === 'gps') {
    return (
      <div className="app-shell">
        {navBar('gps')}
        <GpsView />
      </div>
    )
  }

  return (
    <div className="app-shell">
      {navBar('heatmap')}
      <div className="app-nav app-nav--sub">

        <label className="nav-live">
          <input type="checkbox" checked={liveHeatmap} onChange={e => setLiveHeatmap(e.target.checked)} />
          Temps réel (~3s)
        </label>
        <label className="nav-live" title="Décoche pour déplacer la carte sans qu’elle revienne sur les données à chaque mise à jour">
          <input type="checkbox" checked={autoFitDataBounds} onChange={e => setAutoFitDataBounds(e.target.checked)} />
          Vue auto (données)
        </label>
        <label className="nav-live">
          <input type="checkbox" checked={showApMarkers} onChange={e => setShowApMarkers(e.target.checked)} />
          Positions AP
        </label>
        {apLocations.length > 0 && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>
            {apLocations.length} AP localisé{apLocations.length > 1 ? 's' : ''}
          </span>
        )}
      </div>
      <div className="app-layout">
      {/* ── Sidebar / drawer ── */}
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      )}
      <aside className={`sidebar${sidebarOpen ? ' sidebar--open' : ''}`}>
        {/* Header */}
        <div className="sidebar-header">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <h1 style={{ fontSize: 18, fontWeight: 600, color: 'var(--green)' }}>WiFi Heatmap</h1>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>2.4GHz</span>
          </div>
          <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            <span><b style={{ color: 'var(--text)' }}>{stats.total_points.toLocaleString()}</b> points</span>
            <span><b style={{ color: 'var(--text)' }}>{stats.unique_networks}</b> réseaux</span>
          </div>
        </div>

        {/* Search + sort */}
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>
          <input
            type="text"
            placeholder="Rechercher SSID / BSSID..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="search-input"
          />
          <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
            {(['samples', 'rssi'] as const).map(s => (
              <button
                key={s}
                onClick={() => setSortBy(s)}
                className={`sort-btn ${sortBy === s ? 'active' : ''}`}
              >
                {s === 'samples' ? 'Points' : 'Signal'}
              </button>
            ))}
          </div>
        </div>

        {/* Tous les réseaux */}
        <div style={{ padding: '8px 12px' }}>
          <div
            onClick={() => setSelectedBssid(null)}
            style={{
              padding: '8px 12px',
              marginBottom: 4,
              borderRadius: 8,
              cursor: 'pointer',
              background: selectedBssid === null ? 'var(--bg-surface)' : 'transparent',
              border: `1px solid ${selectedBssid === null ? 'var(--green)' : 'var(--border)'}`,
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            Tous les réseaux
          </div>
        </div>

        {/* Liste des réseaux */}
        <div className="network-list">
          {filtered.map(n => (
            <NetworkCard
              key={n.bssid}
              network={n}
              selected={selectedBssid === n.bssid}
              onClick={() => setSelectedBssid(n.bssid === selectedBssid ? null : n.bssid)}
            />
          ))}
          {filtered.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: '16px 12px', textAlign: 'center' }}>
              Aucun réseau trouvé
            </div>
          )}
        </div>

        {/* Info réseau sélectionné */}
        {selectedNetwork && (
          <div className="selected-info">
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>RÉSEAU SÉLECTIONNÉ</div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{selectedNetwork.ssid}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>RSSI max</span>
              <span style={{ color: rssiColor(selectedNetwork.max_rssi) }}>
                {selectedNetwork.max_rssi} dBm ({rssiLabel(selectedNetwork.max_rssi)})
              </span>
              <span style={{ color: 'var(--text-muted)' }}>RSSI min</span>
              <span style={{ color: rssiColor(selectedNetwork.min_rssi) }}>
                {selectedNetwork.min_rssi} dBm
              </span>
              <span style={{ color: 'var(--text-muted)' }}>Canal</span>
              <span>{selectedNetwork.channel ?? '?'}</span>
            </div>
          </div>
        )}
      </aside>

      {/* ── Map ── */}
      <main className="map-container">
        <MapContainer
          center={[48.8566, 2.3522]}
          zoom={15}
          style={{ height: '100%', width: '100%' }}
          zoomControl={true}
        >
          <TileLayer
            url={MAP_TILE_URL}
            attribution={MAP_ATTRIBUTION}
            maxZoom={19}
          />
          <HeatmapLayer
            bssid={selectedBssid}
            bounds={stats.bounds}
            pollInterval={pollMs}
            autoFitData={autoFitDataBounds}
          />
          {showApMarkers && (
            <ApMarkersLayer
              locations={selectedBssid ? apLocations.filter(a => a.bssid === selectedBssid) : apLocations}
              selectedBssid={selectedBssid}
            />
          )}
          <LocateButton />
        {/* Bouton toggle sidebar (visible uniquement mobile) */}
        <button
          type="button"
          className="map-btn map-btn--networks"
          onClick={() => setSidebarOpen(o => !o)}
          title="Réseaux"
        >
          ☰
        </button>
        </MapContainer>

        {/* Légende */}
        <div className="legend">
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>SIGNAL</div>
          <div style={{
            height: 8,
            borderRadius: 4,
            background: 'linear-gradient(to right, #0000ff, #00aaff, #00d88a, #f0a030, #ff4d6a)',
            marginBottom: 4,
          }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)' }}>
            <span>Faible</span>
            <span>Excellent</span>
          </div>
        </div>
      </main>
      </div>
    </div>
  )
}
