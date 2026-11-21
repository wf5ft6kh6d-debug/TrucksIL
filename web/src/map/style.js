// Minimal self-contained MapLibre style for an OpenMapTiles-schema vector tileset (planetiler
// `--profile openmaptiles` output) served as PMTiles from the same origin. Written for TrucksIL:
// road hierarchy readable for a truck driver, labels in the UI language. Pure (no DOM).
// Licence of the data: © OpenStreetMap contributors (ODbL), schema © OpenMapTiles (CC-BY 4.0).

export const PMTILES_PATH = '/tiles/israel.pmtiles';
export const GLYPHS_PATH = '/tiles/fonts/{fontstack}/{range}.pbf';
export const FONT = ['Noto Sans Regular'];
const ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, © <a href="https://openmaptiles.org/">OpenMapTiles</a>';

/** Label expression: name:<lang>, then the local name. */
export function nameExpr(lang) {
  return ['coalesce', ['get', `name:${lang}`], ['get', 'name']];
}

const ROADS = [
  // class, colour, width at z14
  ['motorway', '#e8892b', 5], ['trunk', '#f0a64a', 4.5], ['primary', '#f7c86b', 4],
  ['secondary', '#fbe39a', 3.5], ['tertiary', '#ffffff', 3], ['minor', '#ffffff', 2], ['service', '#ffffff', 1.2],
];

export function vectorStyle({ origin, lang = 'he' }) {
  const roadFilter = (cls) => ['all', ['==', ['get', 'class'], cls], ['!=', ['get', 'brunnel'], 'tunnel']];
  const w = (base) => ['interpolate', ['exponential', 1.5], ['zoom'], 6, base * 0.15, 14, base, 18, base * 4];
  const label = (id, layer, filter, size, extra = {}) => ({
    id, type: 'symbol', source: 'omt', 'source-layer': layer, filter,
    layout: { 'text-field': nameExpr(lang), 'text-font': FONT, 'text-size': size, ...extra.layout },
    paint: { 'text-color': '#333', 'text-halo-color': '#fff', 'text-halo-width': 1.4, ...extra.paint },
  });
  return {
    version: 8,
    name: 'TrucksIL OMT minimal',
    glyphs: `${origin}${GLYPHS_PATH}`,
    sources: { omt: { type: 'vector', url: `pmtiles://${origin}${PMTILES_PATH}`, attribution: ATTRIBUTION } },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#f4f1ea' } },
      { id: 'landcover', type: 'fill', source: 'omt', 'source-layer': 'landcover', paint: { 'fill-color': ['match', ['get', 'class'], 'wood', '#d6e8c8', 'grass', '#e3efd3', 'sand', '#f3e9c6', '#e6ecd9'], 'fill-opacity': 0.7 } },
      { id: 'landuse', type: 'fill', source: 'omt', 'source-layer': 'landuse', filter: ['in', ['get', 'class'], ['literal', ['residential', 'industrial', 'commercial']]], paint: { 'fill-color': ['match', ['get', 'class'], 'industrial', '#ebe3e8', '#ece8e1'] } },
      { id: 'park', type: 'fill', source: 'omt', 'source-layer': 'park', paint: { 'fill-color': '#d4e9c4', 'fill-opacity': 0.6 } },
      { id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water', paint: { 'fill-color': '#a9cbe8' } },
      { id: 'waterway', type: 'line', source: 'omt', 'source-layer': 'waterway', paint: { 'line-color': '#a9cbe8', 'line-width': 1 } },
      { id: 'building', type: 'fill', source: 'omt', 'source-layer': 'building', minzoom: 14, paint: { 'fill-color': '#ddd6cc' } },
      { id: 'boundary', type: 'line', source: 'omt', 'source-layer': 'boundary', filter: ['<=', ['get', 'admin_level'], 4], paint: { 'line-color': '#9e8aa6', 'line-width': 1, 'line-dasharray': [3, 2] } },
      { id: 'road-tunnel', type: 'line', source: 'omt', 'source-layer': 'transportation', filter: ['==', ['get', 'brunnel'], 'tunnel'], paint: { 'line-color': '#bbb', 'line-width': w(3), 'line-dasharray': [1, 1] } },
      ...ROADS.map(([cls, , width]) => ({ id: `road-${cls}-case`, type: 'line', source: 'omt', 'source-layer': 'transportation', filter: roadFilter(cls), layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#9a9a9a', 'line-width': w(width + 1.5) } })),
      ...ROADS.map(([cls, color, width]) => ({ id: `road-${cls}`, type: 'line', source: 'omt', 'source-layer': 'transportation', filter: roadFilter(cls), layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color, 'line-width': w(width) } })),
      { id: 'rail', type: 'line', source: 'omt', 'source-layer': 'transportation', filter: ['==', ['get', 'class'], 'rail'], paint: { 'line-color': '#888', 'line-width': 1.2, 'line-dasharray': [2, 2] } },
      { id: 'road-bridge-outline', type: 'line', source: 'omt', 'source-layer': 'transportation', minzoom: 13, filter: ['==', ['get', 'brunnel'], 'bridge'], paint: { 'line-color': '#555', 'line-width': w(1), 'line-gap-width': w(4) } },
      label('water-name', 'water_name', ['has', 'name'], 12, { paint: { 'text-color': '#3a6a95' } }),
      label('road-name', 'transportation_name', ['has', 'name'], 11, { layout: { 'symbol-placement': 'line' } }),
      { id: 'road-ref', type: 'symbol', source: 'omt', 'source-layer': 'transportation_name', filter: ['has', 'ref'], layout: { 'text-field': ['get', 'ref'], 'text-font': FONT, 'text-size': 10, 'symbol-placement': 'line' }, paint: { 'text-color': '#7a3d00', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } },
      label('place', 'place', ['in', ['get', 'class'], ['literal', ['city', 'town', 'village', 'suburb']]], ['match', ['get', 'class'], 'city', 16, 'town', 14, 12]),
    ],
  };
}

/** Prototype fallback: public OSM raster tiles (online only, never cached; dev use). */
export function rasterFallbackStyle() {
  return {
    version: 8,
    sources: {
      osm: {
        type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
  };
}

/** True when the first bytes are a PMTiles v3 header ("PMTiles" + version 3). */
export function isPmtilesHeader(bytes) {
  const magic = [0x50, 0x4d, 0x54, 0x69, 0x6c, 0x65, 0x73];
  if (!bytes || bytes.length < 8) return false;
  return magic.every((b, i) => bytes[i] === b) && bytes[7] === 3;
}
