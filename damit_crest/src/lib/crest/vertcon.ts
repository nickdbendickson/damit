/**
 * NOAA VERTCON NGVD29 → NAVD88 vertical offset for any US location.
 *
 * Strategy:
 * 1. The desktop server's /api/vertcon endpoint (pyproj, which ships with QGIS and has the full
 *    CONUS VERTCON grid built in). Covers all 50 states. Requires the desktop server to be running.
 * 2. The bundled North Dakota grid (vertcon_nd.ts): an offline fallback that covers ND without the
 *    server. This is the original crest/DamSafety behavior.
 * 3. null: the engine handles null by flagging the crest as unconverted and holding the screen at
 *    Review. The user can still enter a manual NGVD29 offset.
 *
 * The async path (fetchVertconShiftFt) is used by the desk to pre-fetch the shift when the dam's
 * location is known. The sync path (vertconShiftFt) uses the ND grid only (for the engine's
 * synchronous analyze() call, which cannot await).
 */
import { crestApiHeaders, hasDesktopServer } from "./desktop-server.ts";
import { vertconShiftFt as ndShiftFt, vertconShiftM as ndShiftM } from "./vertcon_nd.ts";

export { vertconShiftFt, vertconShiftM } from "./vertcon_nd.ts";

/** Cache of fetched shifts so repeated calls for the same point don't re-fetch. */
const cache = new Map<string, number | null>();

function cacheKey(lon: number, lat: number): string {
  return `${lon.toFixed(6)},${lat.toFixed(6)}`;
}

/**
 * Async VERTCON shift in feet: tries the desktop server (any CONUS point), then the bundled ND grid,
 * then null. Cache the result for the engine's synchronous path.
 */
export async function fetchVertconShiftFt(lon: number, lat: number): Promise<number | null> {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  const key = cacheKey(lon, lat);
  if (cache.has(key)) return cache.get(key)!;

  // Try the desktop server (pyproj, full CONUS)
  try {
    if (!hasDesktopServer()) throw new Error("no desktop server");
    const res = await fetch(`/api/vertcon?lat=${lat}&lon=${lon}`, { headers: crestApiHeaders() });
    if (res.ok) {
      const data = await res.json();
      if (typeof data.shift_ft === "number") {
        cache.set(key, data.shift_ft);
        return data.shift_ft;
      }
    }
  } catch {
    // Server not available — fall through to the bundled grid
  }

  // Fall back to the bundled ND grid (covers North Dakota offline)
  const ft = ndShiftFt(lon, lat);
  cache.set(key, ft);
  return ft;
}

/**
 * Async VERTCON shift in metres.
 */
export async function fetchVertconShiftM(lon: number, lat: number): Promise<number | null> {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  // Try server first
  try {
    if (!hasDesktopServer()) throw new Error("no desktop server");
    const res = await fetch(`/api/vertcon?lat=${lat}&lon=${lon}`, { headers: crestApiHeaders() });
    if (res.ok) {
      const data = await res.json();
      if (typeof data.shift_m === "number") return data.shift_m;
    }
  } catch {
    // Fall through
  }
  return ndShiftM(lon, lat);
}

/**
 * Pre-warm the cache for a location so the engine's synchronous vertconShiftFt call gets the
 * server's value. Call this when the dam's location is set (the Record step, the NID pick).
 */
export async function prefetchVertcon(lon: number, lat: number): Promise<void> {
  await fetchVertconShiftFt(lon, lat);
}

/** Read from the cache (for the engine's synchronous path after a prefetch). */
export function cachedVertconShiftFt(lon: number, lat: number): number | null {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  const key = cacheKey(lon, lat);
  if (cache.has(key)) return cache.get(key)!;
  // Not in cache — fall back to ND grid (sync-safe)
  return ndShiftFt(lon, lat);
}

export const VERTCON_SOURCE_SERVER = "pyproj VERTCON (PROJ-data us_noaa_vertconc.tif) via DamIT desktop server";
export { VERTCON_SOURCE as VERTCON_SOURCE_ND } from "./vertcon_nd.ts";
