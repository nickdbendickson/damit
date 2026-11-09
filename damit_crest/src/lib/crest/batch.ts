/**
 * Batch screening (Nick, 2026-11-05): pick many dams (one by one, by county, or the whole state) from the NID main dams
 * of the chosen state (the dam inventory is the NID only; nid-state.ts), and run each one through the SAME path a single dam takes on
 * the desk: analyze() -> the inundation layer the gate picks (buildInundationReach) -> the 911 address points inside
 * it -> pads from 3DEP -> analyze() again -> triageDam(). Nothing here is a second engine.
 *
 * What the batch adds is the record. A structure from the inventories has a point, a height and a storage, but no
 * surveyed crest and no drawn dam line, so the record is AUTO-DERIVED the way the four-dam baseline's stand-ins were
 * (scripts/make-crest-layers.mjs):
 *   crest       the highest 3DEP cell within CREST_SNAP_M of the NID point (the point rarely sits exactly on the
 *               embankment top; the NID has no elevations)
 *   streambed   crest - height
 *   direction   toward the lowest 3DEP cell within DOWNHILL_R_M of the point; the dam line is synthesized across it
 *               and the reservoir point stepped upstream. Then (aimAlongChannel) the drainage trace is followed from
 *               the toe and the line is re-laid across the chord to the trace AIM_CHORD_M down the channel, so the
 *               straight schematic strip points down the valley the water takes, not the first few hundred metres of
 *               it (DWR-2662: downhill 46 deg, Buffalo Creek bends east, chord to 4 km 84 deg)
 * Every derived value is labelled on the record (provenance "DEM" / note), and the row says "auto-derived": it is a
 * screen to sort a worklist, never a class.
 *
 * Crest is a SCREENING tool: a batch answers "which of these need a Runner run first", and a row's "open in desk"
 * hands the derived record to the desk for a closer look.
 */
import { csvCell } from "./csv.ts";
import { bundleAgeLine, deskBundles } from "./data-provenance.ts";
import { analyze, ENGINE_VERSION } from "./engine.ts";
import { floodStrip } from "./floodstrip.ts";
import { buildInundationReach, type InundationResult } from "./inundation.ts";
import { makeInundationPool, type InundationPool } from "./inundation-client.ts";
import { fetchNd911, nd911AutoPatch, nd911State } from "./nd911.ts";
import { lookupPads } from "./nd911-pads.ts";
import { heightFor, prefillPatch, storageFor, type NidData } from "./nid-dams.ts";
import { demRequest, demSourceLabel, fetchDem, lookupArea, outlineInputs, outlineState, traceChannel, type DemGrid, type DemRequest } from "./outline.ts";
import { withoutOutline } from "./outline-store.ts";
import { blankDam } from "./samples.ts";
import { RECOMMENDATION_LABEL, RECOMMENDATION_ORDER, triageDam, type Triage } from "./triage.ts";
import type { DamRecord, GeoJSONFeature, Provenance, ScreenLevel } from "./types.ts";
import { CREST_VERSION } from "./version.ts";

// ---------------------------------------------------------------- the structure list

/** The one kind of structure a batch lists: an NID main dam. (No state dam-safety, dugout or other inventory.) */
export type StructureKind = "nid";
export const KIND_LABEL: Record<StructureKind, string> = { nid: "NID dam" };

export type Structure = {
  /** The NID ID (ND00199). */
  id: string;
  kind: StructureKind;
  label: string;
  /** The NID ID again (kept for the CSV and older callers). */
  nid: string | null;
  /** "NID". */
  status: string;
  county: string | null;
  lat: number | null;
  lon: number | null;
  heightFt: number | null;
  storageAcFt: number | null;
  areaAc: number | null;
  lengthFt: number | null;
  year: number | null;
  /** Hazard as reported to the NID (FEMA class); never used by the screen. */
  hazard: string | null;
  purpose: string | null;
  /** USGS WBD HUC8 watershed, "Name (code)", when a caller has it (the NID extract does not carry it). */
  huc8: string | null;
  /** Other ids the structure is searchable by (unused for NID dams). */
  alias?: string | null;
};

/** The batch list: every NID main dam of the loaded state's extract. */
export function makeStructures(nd: Pick<NidData, "dams">): Structure[] {
  return nd.dams.map((d) => {
    const h = heightFor(d);
    const v = storageFor(d);
    return {
      id: d.nid,
      kind: "nid",
      label: d.name ?? d.otherNames ?? `Unnamed dam ${d.nid}`,
      nid: d.nid,
      status: "NID",
      county: d.county || null,
      lat: d.lat,
      lon: d.lon,
      heightFt: Number.isFinite(h.value) && h.value > 0 ? h.value : null,
      storageAcFt: Number.isFinite(v.value) && v.value > 0 ? v.value : null,
      areaAc: null,
      lengthFt: d.lengthFt,
      year: d.yearCompleted,
      hazard: d.nidHazard ?? null,
      purpose: d.purpose,
      huc8: null,
      alias: null,
    } satisfies Structure;
  });
}

export type LoadedStructures = { nd: NidData; structures: Structure[]; source: Record<string, unknown> };
const cache = new Map<string, Promise<LoadedStructures>>();
/**
 * The NID dams of one state (default: the committed example extract). Other states come from the desktop server
 * (nid-state.ts loadNidState).
 */
export function loadStructures(state?: string): Promise<LoadedStructures> {
  const key = state ?? "";
  let p = cache.get(key);
  if (!p) {
    p = (state ? import("./nid-state.ts").then((m) => m.loadNidState(state)) : import("./nid-dams.ts").then((m) => m.loadNidData())).then((nd) => ({
      nd,
      structures: makeStructures(nd),
      source: nd.nidSource as unknown as Record<string, unknown>,
    }));
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}

// ---------------------------------------------------------------- selection

/** Every listed structure is an NID dam, status "NID". */
export const DEFAULT_STATUSES = ["NID"] as const;

export type Selection = {
  /** "pick": the ids ticked one by one; "county"/"watershed": every structure in the chosen ones; "state": all. */
  by: "pick" | "county" | "watershed" | "state";
  ids?: string[];
  counties?: string[];
  /** HUC8 sub-basin names. */
  watersheds?: string[];
  kinds: StructureKind[];
  statuses: string[];
};

export function selectStructures(all: Structure[], sel: Selection): Structure[] {
  const kinds = new Set(sel.kinds);
  const statuses = new Set(sel.statuses);
  const base = all.filter((s) => kinds.has(s.kind) && statuses.has(s.status));
  if (sel.by === "pick") {
    const ids = new Set(sel.ids ?? []);
    // A ticked structure stays in even when a filter would drop it: the user asked for it by name (or by its UNK- alias).
    return all.filter((s) => ids.has(s.id) || (s.alias ? s.alias.split(" ").some((a) => ids.has(a)) : false));
  }
  if (sel.by === "county") {
    const c = new Set(sel.counties ?? []);
    return base.filter((s) => s.county != null && c.has(s.county));
  }
  if (sel.by === "watershed") {
    // A watershed is named as listed ("Maple (09020205)") or by its 8-digit HUC code alone.
    const w = new Set(sel.watersheds ?? []);
    return base.filter((s) => s.huc8 != null && (w.has(s.huc8) || w.has(s.huc8.match(/\((\d{8})\)$/)?.[1] ?? "")));
  }
  return base;
}

export type Facet = { value: string; count: number };
/** County / watershed / status choices with how many structures each holds (for the pickers). */
export function facets(all: Structure[], key: "county" | "huc8" | "status"): Facet[] {
  const m = new Map<string, number>();
  for (const s of all) {
    const v = s[key];
    if (v) m.set(v, (m.get(v) ?? 0) + 1);
  }
  return [...m.entries()].map(([value, count]) => ({ value, count })).sort((a, b) => a.value.localeCompare(b.value));
}

/** Why a structure cannot be screened as listed (null when it can). */
export function missingData(s: Structure): string | null {
  const miss: string[] = [];
  if (s.lat == null || s.lon == null) miss.push("location");
  if (s.heightFt == null) miss.push("height");
  if (s.storageAcFt == null) miss.push("storage");
  return miss.length ? `No ${miss.length > 1 ? `${miss.slice(0, -1).join(", ")} or ${miss[miss.length - 1]}` : miss[0]} in the inventory.` : null;
}

/**
 * Seconds a structure takes, from the four-dam baseline timed with scripts/triage-dams.mjs (2026-11-05): 4 s for a
 * small pool (DWR-3034) to 25 s for a large flood (DWR-2801), mostly the 3DEP fetch. These are the PRIOR: once a run
 * has timed a few structures, `runningEstimate` replaces them with the measured mean. Used only for the estimate.
 */
export const ESTIMATE_PRIOR_S = { small: 8, large: 25, largeFromAcFt: 500 } as const;

/** Rows timed before the running mean takes over from the prior. */
export const ESTIMATE_MIN_ROWS = 3;

export function estimateSeconds(list: Structure[], perStructure: ((s: Structure) => number) | null = null): number {
  const prior = (s: Structure) => ((s.storageAcFt ?? 0) >= ESTIMATE_PRIOR_S.largeFromAcFt ? ESTIMATE_PRIOR_S.large : ESTIMATE_PRIOR_S.small);
  return list.reduce((t, s) => (missingData(s) ? t : t + (perStructure ?? prior)(s)), 0);
}

/**
 * The estimate for what is still to run, from the rows already timed: after ESTIMATE_MIN_ROWS finished rows (done or
 * failed; needs-data rows took no time and are left out) the mean of their `seconds` stands in for the prior, split
 * small/large the same way so a county of small ponds is not timed like a county of reservoirs when both have been seen.
 * Fewer rows than that, or a class with none timed, keep the prior. `lanes` structures run side by side.
 */
export function runningEstimate(rows: readonly BatchRow[], remaining: Structure[], lanes: number): { seconds: number; measured: boolean; perSmallS: number; perLargeS: number } {
  const timed = rows.filter((r) => r.status !== "needs-data" && Number.isFinite(r.seconds) && r.seconds > 0);
  const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const big = (r: { storageAcFt: number | null }) => (r.storageAcFt ?? 0) >= ESTIMATE_PRIOR_S.largeFromAcFt;
  const measured = timed.length >= ESTIMATE_MIN_ROWS;
  const small = timed.filter((r) => !big(r)).map((r) => r.seconds);
  const large = timed.filter(big).map((r) => r.seconds);
  // A class with no timed row borrows the overall mean scaled by the prior's ratio, so a first large dam is not
  // estimated at 8 s because only small ones have run.
  const all = measured ? mean(timed.map((r) => r.seconds)) : null;
  const perSmallS = measured ? (small.length ? mean(small) : all! * (ESTIMATE_PRIOR_S.small / ((ESTIMATE_PRIOR_S.small + ESTIMATE_PRIOR_S.large) / 2))) : ESTIMATE_PRIOR_S.small;
  const perLargeS = measured ? (large.length ? mean(large) : all! * (ESTIMATE_PRIOR_S.large / ((ESTIMATE_PRIOR_S.small + ESTIMATE_PRIOR_S.large) / 2))) : ESTIMATE_PRIOR_S.large;
  const seconds = estimateSeconds(remaining, (s) => (big(s) ? perLargeS : perSmallS)) / Math.max(1, lanes);
  return { seconds, measured, perSmallS, perLargeS };
}

/** Browser batches above this size get a warning and a pointer to scripts/batch-dams.mjs. */
export const BROWSER_BATCH_WARN = 300;

// ---------------------------------------------------------------- the auto-derived record

export const CREST_SNAP_M = 30;
export const DOWNHILL_R_M = 500;
const M_PER_DEG_LAT = 110574;
const FT_PER_M = 1 / 0.3048;
const kxOf = (lat: number) => 111320 * Math.cos((lat * Math.PI) / 180);

/** The small DEM around a point the record is derived from (1.2 km square at 10 m). */
export function nearRequest(lon: number, lat: number, halfKm = 0.6, cellM = 10): DemRequest {
  const dLat = (halfKm * 1000) / M_PER_DEG_LAT;
  const dLon = (halfKm * 1000) / kxOf(lat);
  const n = Math.max(16, Math.round((2 * halfKm * 1000) / cellM));
  return { bbox: [lon - dLon, lat - dLat, lon + dLon, lat + dLat], width: n, height: n, cellM };
}

type Cell = { e: number; n: number; z: number };
function cellsWithin(g: DemGrid, lon: number, lat: number, rM: number): Cell[] {
  const k = kxOf(lat);
  const out: Cell[] = [];
  for (let j = 0; j < g.height; j++) {
    const clat = g.bbox[3] - ((j + 0.5) / g.height) * (g.bbox[3] - g.bbox[1]);
    for (let i = 0; i < g.width; i++) {
      const clon = g.bbox[0] + ((i + 0.5) / g.width) * (g.bbox[2] - g.bbox[0]);
      const e = (clon - lon) * k;
      const n = (clat - lat) * M_PER_DEG_LAT;
      if (e * e + n * n > rM * rM) continue;
      const z = g.z[j * g.width + i];
      if (Number.isFinite(z) && z > -9000) out.push({ e, n, z });
    }
  }
  return out;
}

/** Where the crest came from: the 3DEP service, or a local DEM (batch command line, --dem). */
export type CrestFrom = "3DEP" | "local DEM";
export type Derived = { crestFt: number; crestFrom: CrestFrom; bearingDeg: number; u: [number, number] };

/** Crest (highest cell near the point, ft) and downstream unit vector (toward the lowest cell within 500 m). */
export function deriveFromDem(g: DemGrid, lon: number, lat: number): { crestFt: number; u: [number, number] } | null {
  const near = cellsWithin(g, lon, lat, CREST_SNAP_M);
  const wide = cellsWithin(g, lon, lat, DOWNHILL_R_M);
  if (!near.length || !wide.length) return null;
  const top = near.reduce((a, b) => (b.z > a.z ? b : a));
  const low = wide.reduce((a, b) => (b.z < a.z ? b : a));
  const L = Math.hypot(low.e, low.n);
  if (!(L > 0)) return null;
  return { crestFt: Math.round(top.z * FT_PER_M * 100) / 100, u: [low.e / L, low.n / L] };
}

const point = (c: number[]): GeoJSONFeature => ({ type: "Feature", properties: { source: "batch: synthesized" }, geometry: { type: "Point", coordinates: c } });

/** Synthesized dam line (across the downstream axis, the record's length) and reservoir point (150 m upstream). */
export function synthGeometry(lon: number, lat: number, u: [number, number], lengthFt: number) {
  const halfM = (Math.max(lengthFt, 100) * 0.3048) / 2;
  const toLL = (e: number, n: number) => [lon + e / kxOf(lat), lat + n / M_PER_DEG_LAT];
  const p: [number, number] = [-u[1], u[0]];
  return {
    damLine: {
      type: "Feature" as const,
      properties: { source: "batch: synthesized across the 3DEP downhill" },
      geometry: { type: "LineString" as const, coordinates: [toLL(p[0] * halfM, p[1] * halfM), toLL(-p[0] * halfM, -p[1] * halfM)] },
    },
    reservoirPoint: point(toLL(-u[0] * 150, -u[1] * 150)),
  };
}

/**
 * The record's inventory fields for an NID dam, elevations left blank (as the NID picker leaves them): the NID dam's
 * own prefill ("New record from NID"). Without the extract the listed numbers are used with NID provenance.
 */
export function structureRecord(s: Structure, nd?: Pick<NidData, "byNid" | "nidSource">, id = `batch-${s.id.toLowerCase()}`): DamRecord {
  const asOf = nd?.nidSource.fetchedUtc.slice(0, 10) ?? new Date().toISOString().slice(0, 10);
  const base = blankDam();
  const ndDam = nd?.byNid.get(s.id);
  if (ndDam && nd) {
    const { patch } = prefillPatch(ndDam, nd);
    const dam = { ...base, ...patch, id };
    if (s.areaAc != null && dam.surfaceAreaAc == null) dam.surfaceAreaAc = s.areaAc;
    return dam;
  }
  const prov = (field: string, value: number | string | null): Provenance => ({ src: "NID", field, value, asOf, note: "NID extract (batch list)" });
  return {
    ...base,
    id,
    name: s.label,
    nid: s.id,
    nidId: s.id,
    county: s.county ?? "",
    year: s.year ?? Number.NaN,
    heightFt: s.heightFt ?? Number.NaN,
    lengthFt: s.lengthFt ?? Number.NaN,
    storageAcFt: s.storageAcFt ?? Number.NaN,
    drainageMi2: Number.NaN,
    spillwayFt: Number.NaN,
    normalPoolFt: Number.NaN,
    lat: s.lat ?? undefined,
    lon: s.lon ?? undefined,
    crestFt: Number.NaN,
    streambedFt: Number.NaN,
    demCrestFt: Number.NaN,
    statedDatum: "",
    geometry: undefined,
    receptors: [],
    receptorSource: s.id.toUpperCase().startsWith("ND") ? "nd911" : undefined,
    judgmentAsProbable: false,
    provenance: { heightFt: prov("NID Height (Ft)", s.heightFt), storageAcFt: prov("NID Storage (Acre-Ft)", s.storageAcFt) },
    ...(s.areaAc != null ? { surfaceAreaAc: s.areaAc } : {}),
  };
}

/**
 * The desk record for an NID dam: the NID dam's own prefill (same as "New record from NID"), with the crest, streambed
 * and geometry derived from the terrain as the module note says. Null + reason when it cannot be built.
 */
export function deriveRecord(
  s: Structure,
  g: DemGrid,
  nd?: Pick<NidData, "byNid" | "nidSource">,
  demLabel: CrestFrom = "3DEP",
): { ok: true; dam: DamRecord; derived: Derived } | { ok: false; reason: string } {
  const miss = missingData(s);
  if (miss) return { ok: false, reason: miss };
  const lon = s.lon!;
  const lat = s.lat!;
  const d = deriveFromDem(g, lon, lat);
  if (!d) return { ok: false, reason: "No 3DEP terrain at the structure's point." };
  const asOf = new Date().toISOString().slice(0, 10);
  let dam = structureRecord(s, nd);
  const crestFrom: CrestFrom = demLabel;
  const p = (field: string, value: number): Provenance => ({
    src: "DEM",
    field,
    value,
    asOf,
    note: `batch: highest ${demLabel} cell within ${CREST_SNAP_M} m of the inventory point; streambed = crest - height`,
  });
  dam = {
    ...dam,
    crestFt: d.crestFt,
    streambedFt: Math.round((d.crestFt - dam.heightFt) * 100) / 100,
    statedDatum: "NAVD88",
    datumOffsetFt: undefined,
    provenance: { ...dam.provenance, crestFt: p(`crest (${demLabel}, batch)`, d.crestFt), streambedFt: p("streambed (crest - H, batch)", d.crestFt - dam.heightFt) },
  };
  dam.demCrestFt = d.crestFt;
  const len = Number.isFinite(dam.lengthFt) && dam.lengthFt > 0 ? dam.lengthFt : 600;
  dam.geometry = synthGeometry(lon, lat, d.u, len);
  const bearingDeg = Math.round((((Math.atan2(d.u[0], d.u[1]) * 180) / Math.PI + 360) % 360) * 10) / 10;
  dam.sampleNote = `Batch record (auto-derived ${asOf}): crest from ${demLabel} at the NID point ${dam.crestFt.toFixed(1)} ft, streambed ${dam.streambedFt.toFixed(1)} ft, downstream bearing ${bearingDeg}° from the ${demLabel} downhill, dam line synthesized. A stand-in for a surveyed record: check the point, the crest and the direction before relying on it.`;
  return { ok: true, dam, derived: { crestFt: d.crestFt, crestFrom, bearingDeg, u: d.u } };
}

/** Distance down the traced channel (m) the strip is aimed at by aimAlongChannel. */
export const AIM_CHORD_M = 4000;
/** Shortest trace (m) worth re-aiming on; a shorter one keeps the downhill. */
export const AIM_MIN_TRACE_M = 1000;
/** Smallest change (degrees) that re-lays the line; below it the downhill is kept. */
export const AIM_MIN_TURN_DEG = 5;

export type ChannelAim = { u: [number, number]; bearingDeg: number; chordM: number; fromDeg: number };

const bearingOf = (u: readonly [number, number] | readonly number[]) => Math.round((((Math.atan2(u[0], u[1]) * 180) / Math.PI + 360) % 360) * 10) / 10;

/**
 * The downstream direction along the drainage: the chord from the breach to the traced channel AIM_CHORD_M down it (or
 * its end when shorter). Null when the trace cannot be built, is under AIM_MIN_TRACE_M, or turns less than
 * AIM_MIN_TURN_DEG from `u` (the caller keeps the downhill). Pure on the trace; the DEM is the corridor the trace uses.
 */
export function channelAim(pts: { e: number; n: number; x: number }[], u: readonly [number, number]): ChannelAim | null {
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1];
  if (!(last.x >= AIM_MIN_TRACE_M)) return null;
  const p = pts.find((q) => q.x >= AIM_CHORD_M) ?? last;
  const L = Math.hypot(p.e, p.n);
  if (!(L > 0)) return null;
  const v: [number, number] = [p.e / L, p.n / L];
  const turn = (Math.acos(Math.max(-1, Math.min(1, v[0] * u[0] + v[1] * u[1]))) * 180) / Math.PI;
  if (turn < AIM_MIN_TURN_DEG) return null;
  return { u: v, bearingDeg: bearingOf(v), chordM: Math.round(Math.min(p.x, AIM_CHORD_M)), fromDeg: bearingOf(u) };
}

/**
 * Two-pass aim for an auto-derived record (synthesized dam line): trace the channel with the downhill line, then re-lay
 * the line across the chord channelAim gives. A drawn line is never touched (the caller only passes derived records).
 */
export async function aimAlongChannel(
  dam: DamRecord,
  u: [number, number],
  dem: (r: DemRequest) => Promise<DemGrid>,
): Promise<{ dam: DamRecord; aim: ChannelAim | null }> {
  const result = analyze(dam);
  const io = outlineInputs(dam, result);
  if (!io.ok || !Number.isFinite(dam.lon) || !Number.isFinite(dam.lat)) return { dam, aim: null };
  const tr = await traceChannel(dam, result, await dem(demRequest(io.inputs)));
  if (!tr.ok) return { dam, aim: null };
  const aim = channelAim(tr.centerline.pts, u);
  if (!aim) return { dam, aim: null };
  const len = Number.isFinite(dam.lengthFt) && dam.lengthFt > 0 ? dam.lengthFt : 600;
  const geometry = { ...dam.geometry, ...synthGeometry(dam.lon!, dam.lat!, aim.u, len) };
  const note = ` Re-aimed along the traced channel: bearing ${aim.bearingDeg}° (chord to ${(aim.chordM / 1000).toFixed(1)} km down the channel), from the ${aim.fromDeg}° downhill.`;
  return { dam: { ...dam, geometry, sampleNote: (dam.sampleNote ?? "") + note }, aim };
}

// ---------------------------------------------------------------- one structure

export type BatchStatus = "done" | "needs-data" | "failed";

export type BatchRow = {
  id: string;
  kind: StructureKind;
  label: string;
  county: string | null;
  huc8: string | null;
  status: BatchStatus;
  /** Why it did not run (needs-data / failed). */
  reason: string | null;
  heightFt: number | null;
  storageAcFt: number | null;
  crestFt: number | null;
  crestFrom: CrestFrom | null;
  bearingDeg: number | null;
  releasedAcFt: number | null;
  peakCfs: number | null;
  layer: "routed" | "outline" | null;
  floodedAc: number | null;
  screen: ScreenLevel | null;
  screenLabel: string | null;
  structuresInside: number | null;
  structuresFlooded: number | null;
  triage: Pick<Triage, "recommendation" | "label" | "confidence" | "edgeShiftM" | "summary"> | null;
  seconds: number;
};

export type BatchDeps = {
  fetchDem?: (req: DemRequest) => Promise<DemGrid>;
  fetchNd911?: typeof fetchNd911;
  nd?: Pick<NidData, "byNid" | "nidSource">;
  /**
   * Cell (m) of the small DEM the crest and the downhill are read from. 10 m on 3DEP (one request); a local 1 m mosaic
   * can afford 2 m, which puts the snap on the real embankment top instead of a 10 m average of it.
   */
  nearCellM?: number;
  /** "local DEM" when fetchDem reads a local raster; labels the crest source. */
  demLabel?: CrestFrom;
  onStatus?: (text: string) => void;
  yieldFn?: () => Promise<void>;
  /**
   * The inundation build (buildInundationReach in-thread by default). The browser batch hands each structure a worker
   * from its pool (inundation-client.ts), so the trace, routing, spread and polygonisation run off the main thread;
   * the record derivation, the 911 lookup and the pads stay here, as they are mostly waiting on the network.
   */
  build?: (dam: DamRecord, result: ReturnType<typeof analyze>, o: { onStatus: (t: string) => void }) => Promise<InundationResult>;
};

const emptyRow = (s: Structure, status: BatchStatus, reason: string | null, seconds = 0): BatchRow => ({
  id: s.id,
  kind: s.kind,
  label: s.label,
  county: s.county,
  huc8: s.huc8,
  status,
  reason,
  heightFt: s.heightFt,
  storageAcFt: s.storageAcFt,
  crestFt: null,
  crestFrom: null,
  bearingDeg: null,
  releasedAcFt: null,
  peakCfs: null,
  layer: null,
  floodedAc: null,
  screen: null,
  screenLabel: null,
  structuresInside: null,
  structuresFlooded: null,
  triage: null,
  seconds,
});

/**
 * The desk's 911 pads (nd911-pads.ts lookupPads: ground at the point minus the channel bed at its station) on the
 * batch's terrain source, so a local DEM serves the pads too. A failed terrain read gives "estimated" pads whose notes
 * say the request failed and why, as on the desk (never "no terrain at the point").
 */
async function padsFor(dam: DamRecord, result: ReturnType<typeof analyze>, dem: (r: DemRequest) => Promise<DemGrid>) {
  return (await lookupPads(dam, result, undefined, dem)) ?? dam.receptors;
}

/** Run one structure through the desk's own path. Returns the row and the finished record (for "open in desk"). */
export async function runStructure(s: Structure, deps: BatchDeps = {}): Promise<{ row: BatchRow; dam: DamRecord | null }> {
  const t0 = Date.now();
  const secs = () => Math.round((Date.now() - t0) / 100) / 10;
  const miss = missingData(s);
  if (miss) return { row: emptyRow(s, "needs-data", miss), dam: null };
  const dem = deps.fetchDem ?? ((r: DemRequest) => fetchDem(r));
  try {
    deps.onStatus?.(`${s.id}: reading the terrain at the point…`);
    // The desktop's local DEM (dem-source.ts) answers fetchDem when no fetch is passed: read it at 2 m, label it.
    const local = !deps.fetchDem && demSourceLabel() !== "3DEP";
    const near = await dem(nearRequest(s.lon!, s.lat!, 0.6, deps.nearCellM ?? (local ? 2 : 10)));
    const rec = deriveRecord(s, near, deps.nd, deps.demLabel ?? (local ? "local DEM" : "3DEP"));
    if (!rec.ok) return { row: emptyRow(s, "needs-data", rec.reason, secs()), dam: null };
    let dam = rec.dam;
    // Second pass: aim the synthesized line down the traced channel (aimAlongChannel).
    const aimed = await aimAlongChannel(dam, rec.derived.u, dem).catch(() => ({ dam, aim: null }));
    dam = aimed.dam;
    const bearingDeg = aimed.aim ? aimed.aim.bearingDeg : rec.derived.bearingDeg;
    let result = analyze(dam);
    if (result.screen.level === "Review" && !Number.isFinite(result.breach.peakCfs))
      return { row: { ...emptyRow(s, "failed", result.screen.reasons[0] ?? "The desk could not screen the record.", secs()) }, dam };

    deps.onStatus?.(`${s.id}: building the inundation layer…`);
    const onStatus = (t: string) => deps.onStatus?.(`${s.id}: ${t}`);
    const built = deps.build
      ? await deps.build(dam, result, { onStatus })
      : await buildInundationReach(dam, result, { fetch: dem, yieldFn: deps.yieldFn, onStatus });
    if (built.ok) dam = { ...dam, outline: built.cache };

    // 911 points inside the layer (or the strip when no layer could be built), added as receptors like a picked dam.
    const strip = floodStrip(dam, result).strip;
    const ol = outlineState(dam, result, true);
    const olGeo = ol.state === "ready" ? ol.outline : null;
    const area = olGeo ?? strip;
    // structuresInside stays null unless the 911 lookup succeeded: a failed lookup is "unknown", never 0.
    let inside: number | null = null;
    let lookupFailed: string | null = null;
    const notes: string[] = [];
    if (!built.ok) notes.push(`No terrain layer: ${built.reason}`);
    if (strip && area) {
      deps.onStatus?.(`${s.id}: looking up 911 address points…`);
      try {
        const cacheNd = await (deps.fetchNd911 ?? fetchNd911)(lookupArea(strip, olGeo));
        dam = { ...dam, nd911: cacheNd };
        const st = nd911State(dam, area, true, olGeo ? "terrain layer" : "flood strip");
        inside = st.state === "ready" ? st.table.rows.length : null;
        const p = nd911AutoPatch(dam, st, result);
        if (p) dam = { ...dam, ...p };
        if (inside) {
          dam = { ...dam, receptors: await padsFor(dam, result, dem) };
        }
        result = analyze(dam);
      } catch (e) {
        // No 911 points means nothing at stake is known: the triage then reads the dam as uncertain at best, never trivial.
        lookupFailed = (e as Error).message;
        notes.push(`911 lookup failed (${lookupFailed}); structures unknown.`);
      }
    }
    let tri = triageDam(dam, result, outlineState(dam, result, true));
    if (inside == null && tri.recommendation === "trivial") {
      // No 911 list (the lookup failed, or there was no area to look up in): nothing at stake is KNOWN, which is not
      // the same as nothing at stake. The screen and triage ran on zero receptors, so "clearly trivial" is never
      // allowed; the call is at least uncertain and says why.
      const why = lookupFailed
        ? `911 lookup failed (${lookupFailed}), so the structures in reach are unknown and the screen ran on none.`
        : "The 911 address points could not be looked up, so the structures in reach are unknown.";
      tri = { ...tri, recommendation: "uncertain", label: RECOMMENDATION_LABEL.uncertain, reasons: [why, ...tri.reasons], summary: `${RECOMMENDATION_LABEL.uncertain} (${tri.confidence} confidence). ${why}` };
    }
    const routedAc = built.ok ? (built.cache.routed?.floodedAc ?? built.cache.stats.outlineAc) : null;
    const flooded = result.flood.receptors.filter((r) => r.flooded && r.kind !== "road").length;
    return {
      row: {
        ...emptyRow(s, "done", notes.length ? notes.join(" ") : null, secs()),
        crestFt: dam.crestFt,
        crestFrom: rec.derived.crestFrom,
        bearingDeg,
        releasedAcFt: Number.isFinite(result.breach.volumeAcFt) ? Math.round(result.breach.volumeAcFt * 10) / 10 : null,
        peakCfs: Number.isFinite(result.breach.peakCfs) ? Math.round(result.breach.peakCfs) : null,
        layer: built.ok ? built.layer : null,
        floodedAc: routedAc != null ? Math.round(routedAc * 10) / 10 : null,
        screen: result.screen.level,
        screenLabel: result.screen.label,
        structuresInside: inside,
        // Flooded is unknown too when the points were never listed (the screen's receptors are the 911 seeds).
        structuresFlooded: inside == null && lookupFailed ? null : flooded,
        triage: { recommendation: tri.recommendation, label: tri.label, confidence: tri.confidence, edgeShiftM: tri.edgeShiftM, summary: tri.summary },
      },
      dam,
    };
  } catch (e) {
    return { row: emptyRow(s, "failed", (e as Error).message, secs()), dam: null };
  }
}

// ---------------------------------------------------------------- the queue

export type BatchOptions = BatchDeps & {
  /** Structures run side by side (each is mostly waiting on 3DEP). Default 2. */
  concurrency?: number;
  signal?: AbortSignal;
  /** Ids already done (resume): skipped. */
  skip?: Set<string>;
  onRow?: (row: BatchRow, dam: DamRecord | null, done: number, total: number) => void;
  /**
   * A pool of inundation workers to build on (the browser batch; see runBatchInBrowser). Each structure in flight
   * takes one worker for its build and gives it back; `concurrency` is then the pool's size.
   */
  pool?: InundationPool | null;
};

/** Run a list, `concurrency` at a time, in list order; stops taking new work once `signal` aborts. */
export async function runBatch(list: Structure[], opts: BatchOptions = {}): Promise<BatchRow[]> {
  const todo = list.filter((s) => !opts.skip?.has(s.id));
  const rows: BatchRow[] = [];
  let next = 0;
  let done = 0;
  const pool = opts.pool ?? null;
  // With a pool, each structure's build runs on a pooled worker; the page's fetch serves it a local DEM when one is in
  // use (the worker fetches 3DEP itself). A structure's own fetchDem (tests) also goes through the page.
  const deps: BatchDeps = pool
    ? {
        ...opts,
        build: async (dam, result, o) => {
          const w = await pool.acquire();
          try {
            return await w.build(dam, result, { onStatus: o.onStatus, signal: opts.signal, fetch: opts.fetchDem });
          } finally {
            pool.release(w);
          }
        },
      }
    : opts;
  const worker = async () => {
    while (next < todo.length && !opts.signal?.aborted) {
      const s = todo[next++];
      const { row, dam } = await runStructure(s, deps);
      if (opts.signal?.aborted && row.status === "failed" && /cancelled/.test(row.reason ?? "")) break;
      rows.push(row);
      done++;
      opts.onRow?.(row, dam, done, todo.length);
    }
  };
  const lanes = Math.max(1, Math.min(opts.concurrency ?? (pool ? pool.size : 2), todo.length || 1));
  await Promise.all(Array.from({ length: lanes }, worker));
  return rows;
}

/**
 * The browser batch: runBatch on a pool of inundation workers sized to the machine (inundation-client.ts poolSize:
 * one per spare core, at most 4), falling back to the in-thread two-lane batch where no worker can be made. The
 * finished records come back without their inundation layer (it is rebuilt on "Open in desk" in one click), so a
 * long batch does not keep 2–5 MB of GeoJSON per dam in memory.
 */
export async function runBatchInBrowser(list: Structure[], opts: Omit<BatchOptions, "pool"> = {}): Promise<BatchRow[]> {
  const pool = await makeInundationPool(undefined, opts.fetchDem);
  try {
    return await runBatch(list, {
      ...opts,
      pool,
      concurrency: opts.concurrency ?? (pool ? pool.size : 2),
      onRow: opts.onRow ? (row, dam, done, total) => opts.onRow!(row, dam ? withoutOutline(dam) : dam, done, total) : undefined,
    });
  } finally {
    pool?.terminateAll();
  }
}

// ---------------------------------------------------------------- sorting and CSV

const STATUS_ORDER: Record<BatchStatus, number> = { done: 0, "needs-data": 1, failed: 2 };
const SCREEN_ORDER: Record<ScreenLevel, number> = { High: 0, Medium: 1, Review: 2, Low: 3 };

/** The worklist comparator behind sortRows and insertRow. */
export function compareRows(a: BatchRow, b: BatchRow): number {
  return (
    STATUS_ORDER[a.status] - STATUS_ORDER[b.status] ||
    (a.triage && b.triage ? RECOMMENDATION_ORDER[a.triage.recommendation] - RECOMMENDATION_ORDER[b.triage.recommendation] : 0) ||
    (a.screen && b.screen ? SCREEN_ORDER[a.screen] - SCREEN_ORDER[b.screen] : 0) ||
    (b.releasedAcFt ?? -1) - (a.releasedAcFt ?? -1) ||
    a.id.localeCompare(b.id, "en", { numeric: true })
  );
}

/** Runner worklist order: needs-runner, uncertain, trivial; then screen level; then largest release. Not-run rows last. */
export function sortRows(rows: BatchRow[]): BatchRow[] {
  return [...rows].sort(compareRows);
}

/**
 * `sorted` (already in sortRows order) with `row` put in its place: a new array, one binary search and one splice, so
 * the batch screen keeps its running view ordered without re-sorting every row on every arrival. A row with the same
 * id already in the list (a retried dam) is replaced.
 */
export function insertRow(sorted: BatchRow[], row: BatchRow): BatchRow[] {
  const out = sorted.filter((r) => r.id !== row.id);
  let lo = 0;
  let hi = out.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (compareRows(out[mid], row) <= 0) lo = mid + 1;
    else hi = mid;
  }
  out.splice(lo, 0, row);
  return out;
}

export const BATCH_DISCLAIMER = "Screening estimate — not an official hazard classification. Batch records are auto-derived from the inventories and 3DEP.";

export const BATCH_CSV_HEAD = [
  "id",
  "kind",
  "name",
  "county",
  "huc8",
  "run_status",
  "height_ft",
  "storage_acft",
  "crest_ft_navd88",
  "crest_from",
  "bearing_deg",
  "released_acft",
  "peak_cfs",
  "layer",
  "flooded_ac",
  "screen",
  "structures_inside",
  "structures_flooded",
  "recommendation",
  "confidence",
  "edge_shift_m",
  "note",
];

/** What the CSV's comment rows say about the run: the NID extract's pull time and when the file was written. */
export type BatchCsvMeta = {
  /** Pull time of the NID extract the rows came from. */
  nidFetchedUtc?: string | null;
  /** Its state, for the label. */
  state?: string | null;
  /** "Now" for the inventory age (injected so the tests and a resumed run are reproducible). */
  now?: Date;
};

/** The CSV meta from what loadStructures() returns. */
export function batchCsvMeta(d: { nd: Pick<NidData, "nidSource"> & { state?: string } }, now?: Date): BatchCsvMeta {
  return { nidFetchedUtc: d.nd.nidSource?.fetchedUtc ?? null, state: d.nd.state ?? null, ...(now ? { now } : {}) };
}

/**
 * The worklist CSV. Comment rows first ("# ..."): the disclaimer, the Crest build and engine versions that made the
 * rows, and the age of each inventory bundle given in `meta`; then the header and one line per row.
 */
export function batchCsv(rows: BatchRow[], meta: BatchCsvMeta = {}): string {
  const now = meta.now ?? new Date();
  const ages = deskBundles({ nidFetchedUtc: meta.nidFetchedUtc, state: meta.state })
    .map((b) => bundleAgeLine(b, now))
    .filter((l): l is string => l != null);
  const head = [
    `# ${BATCH_DISCLAIMER}`,
    `# DamIT Crest ${CREST_VERSION}; ${ENGINE_VERSION}. Written ${now.toISOString().slice(0, 10)}.`,
    ...ages.map((l) => `# ${l}`),
  ];
  const lines = sortRows(rows).map((r) =>
    [
      r.id,
      KIND_LABEL[r.kind] ?? r.kind,
      r.label,
      r.county,
      r.huc8,
      r.status,
      r.heightFt,
      r.storageAcFt,
      r.crestFt,
      r.crestFrom,
      r.bearingDeg,
      r.releasedAcFt,
      r.peakCfs,
      r.layer,
      r.floodedAc,
      r.screenLabel,
      r.structuresInside,
      r.structuresFlooded,
      r.triage?.label,
      r.triage?.confidence,
      r.triage?.edgeShiftM == null ? null : Math.round(r.triage.edgeShiftM),
      r.reason ?? r.triage?.summary,
    ]
      .map(csvCell)
      .join(","),
  );
  return [...head, BATCH_CSV_HEAD.join(","), ...lines].join("\n") + "\n";
}
