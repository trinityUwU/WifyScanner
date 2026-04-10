/**
 * leaflet-heat (dist) attend une variable globale `L`. L'app importe Leaflet via npm ;
 * on expose la même instance avant d'importer le plugin (ordre des imports dans main.tsx).
 */
import L from 'leaflet'

;(globalThis as unknown as { L: typeof L }).L = L
