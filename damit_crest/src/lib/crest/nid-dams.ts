/**
 * NID dam picker (State -> County -> Dam) logic, pure and shared by the web desk and the desktop window.
 *
 * The dam inventory is the USACE National Inventory of Dams (NID) and nothing else. One state's NID extract at a time:
 *   data/nid_ND.json   a small committed example extract (North Dakota, scripts/build-nid-dams.mjs), so the desk
 *                      and the tests work offline;
 *   any other state    downloaded on request by the desktop server from the NID bulk CSV for that state
 *                      (GET /api/nid/state?state=XX, cached in the app's settings folder; nid-state.ts).
 * No per-dam NID API calls, and "Owner Names" are never read.
 *
 * Rules:
 * - H = NID Height (whole ft, rounded). V = NID Storage (= max(Max, Normal)); chip says which. Surface area is never
 *   filled.
 * - Elevations are never filled from the NID (it has none); the user enters them or ties them to a DEM.
 * - NID hazard is shown as reported (FEMA class), never used by the screen and never the class of record.
 */
import type { DamRecord, NidHazard, NidRef, Provenance } from "./types.ts";
import { loadBundle } from "./data-bundle.ts";
import type { Warning } from "./warnings.ts";

export type NidDam = {
  nid: string;
  name: string | null;
  otherNames: string | null;
  county: string;
  countyNote: string | null;
  lat: number | null;
  lon: number | null;
  nidHeightFt: number | null;
  damHeightFt: number | null;
  structuralHeightFt: number | null;
  hydraulicHeightFt: number | null;
  nidStorageAcFt: number | null;
  maxStorageAcFt: number | null;
  normalStorageAcFt: number | null;
  surfaceAreaNormalAc: number | null;
  lengthFt: number | null;
  yearCompleted: number | null;
  drainageMi2: number | null;
  nidHazard: NidHazard | null;
  river: string | null;
  city: string | null;
  purpose: string | null;
  damType: string | null;
  nidUpdated: string | null;
  lastInspection: string | null;
  eap: string | null;
};

type Table = { cols: string[]; rows: unknown[][] };
export type NidBundle = Table & { source: Record<string, unknown> };

export type NidSource = { url: string; fetchedUtc: string; rows: number; attribution: string };
export type NidData = {
  dams: NidDam[];
  byNid: Map<string, NidDam>;
  nidSource: NidSource;
  /** Two-letter state / territory code of the extract (from source.state, else the NID IDs), "" when unknown. */
  state: string;
};

export function decode<T>(b: Table): T[] {
  return b.rows.map((r) => Object.fromEntries(b.cols.map((c, i) => [c, r[i] ?? null])) as T);
}

/** NID ID: a two-letter state / territory code and digits (ND00199, CA01234), upper case. */
export const NID_ID_RE = /^[A-Z]{2}\d{3,}$/;
export function isNidId(v: unknown): v is string {
  return typeof v === "string" && NID_ID_RE.test(v.trim().toUpperCase());
}

/** The built-in fictional desk examples (samples.ts). Their ids are not NID IDs. */
export const DESK_SAMPLE_IDS: ReadonlySet<string> = new Set(["SAMPLE-4031", "DESK-014"]);

/**
 * The ids a record goes out under (same rule as desktop/damit_desktop/handoff.py handoff_ids): dam_id is the NID ID
 * when the record has one (nidId, else nid), else the desk record's own id, never a made-up NID ID.
 */
export function handoffIds(dam: { id: string; nid?: string; nidId?: string; isNew?: boolean }): {
  damId: string;
  nidId: string | null;
  isNew: boolean;
  isSample: boolean;
} {
  const nid = [dam.nidId, dam.nid].map((v) => String(v ?? "").trim().toUpperCase()).find((v) => isNidId(v)) ?? null;
  return { damId: nid ?? dam.id, nidId: nid, isNew: dam.isNew === true, isSample: DESK_SAMPLE_IDS.has(String(dam.nid ?? "").trim().toUpperCase()) };
}

export function makeNidData(nid: NidBundle): NidData {
  const dams = decode<NidDam>(nid);
  const src = nid.source as Record<string, unknown>;
  const fromIds = dams.length ? dams[0].nid.slice(0, 2).toUpperCase() : "";
  const state = typeof src.state === "string" && /^[A-Z]{2}$/.test(src.state) ? src.state : fromIds;
  return { dams, byNid: new Map(dams.map((d) => [d.nid, d])), nidSource: nid.source as unknown as NidSource, state };
}

let cache: Promise<NidData> | null = null;
/**
 * The committed example extract (North Dakota), loaded once as its own chunk; never part of the first paint. Other
 * states come from loadNidState (nid-state.ts) through the desktop server.
 */
export function loadNidData(): Promise<NidData> {
  cache ??= loadBundle<NidBundle>("nid_example").then((n) => makeNidData(n));
  return cache;
}

// ---------------------------------------------------------------- search, labels, counties

/** Lower case, accents folded, punctuation -> space, collapsed. */
export function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");

/** Display name: Dam Name, else Other Names, else "(unnamed)". */
export function displayName(d: NidDam): string {
  return d.name ?? d.otherNames ?? "(unnamed)";
}

/** "name · NID ID · NID hazard · H ft · V ac-ft"; an unnamed dam reads "(unnamed) · ND00971 · ...", never an owner name. */
export function damOptionLabel(d: NidDam): string {
  const h = heightFor(d).value;
  const parts = [displayName(d), d.nid];
  parts.push(d.nidHazard ? `NID hazard ${d.nidHazard}` : "NID hazard n/a");
  parts.push(Number.isFinite(h) ? `${h} ft` : "H n/a");
  parts.push(d.nidStorageAcFt != null ? `${fmtInt(d.nidStorageAcFt)} ac-ft` : "V n/a");
  return parts.join(" · ");
}

/**
 * Case- and accent-insensitive match on name, other names and NID ID. Every query word must match; a number-only
 * query also matches the NID ID's digits ("199" -> ND00199, "nd00199"). county "" = all.
 */
export function searchDams(dams: NidDam[], query: string, county = ""): NidDam[] {
  const words = fold(query).split(" ").filter(Boolean);
  const list = county ? dams.filter((d) => d.county === county) : dams;
  if (!words.length) return list;
  return list.filter((d) => {
    const hay = fold(`${d.name ?? ""} ${d.otherNames ?? ""} ${d.nid}`);
    const digits = d.nid.replace(/^\D+0*/, "");
    return words.every((w) => hay.includes(w) || (/^\d+$/.test(w) && digits === w.replace(/^0+/, "")));
  });
}

export type CountyOption = { county: string; count: number; label: string };
/** County dropdown: "Cass (28)"; a county the build flagged gets "(see note)". */
export function countyOptions(dams: NidDam[]): CountyOption[] {
  const m = new Map<string, { count: number; note: boolean }>();
  for (const d of dams) {
    const e = m.get(d.county) ?? { count: 0, note: false };
    e.count++;
    if (d.countyNote) e.note = true;
    m.set(d.county, e);
  }
  return [...m.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([county, { count, note }]) => ({
      county,
      count,
      label: `${county} (${count})${note ? " (see note)" : ""}`,
    }));
}

// ---------------------------------------------------------------- field rules

export type HeightPick = { value: number; src: "NID"; field: string; rounded: boolean };
/** H = NID Height (whole ft). NaN when the NID reports none. */
export function heightFor(d: NidDam): HeightPick {
  if (d.nidHeightFt != null) return { value: d.nidHeightFt, src: "NID", field: "NID Height (Ft)", rounded: true };
  return { value: Number.NaN, src: "NID", field: "NID Height (Ft)", rounded: true };
}

export type StorageChip = { value: number; chip: string; warning: string | null; rangeNote: string | null };
/** Decision 2: V = NID Storage; chip says which value it is. */
export function storageFor(d: NidDam): StorageChip {
  const v = d.nidStorageAcFt ?? Number.NaN;
  const max = d.maxStorageAcFt;
  const normal = d.normalStorageAcFt;
  let chip = "NID Max Storage";
  let warning: string | null = null;
  if (max == null || (normal != null && max < normal)) {
    chip = "NID Normal Storage (no max reported)";
    warning =
      max == null
        ? "The NID reports no Max Storage for this dam, so V is the Normal Storage. Storage at the top of dam is likely larger; check the dam file."
        : `The NID's Max Storage (${fmtInt(max)} ac-ft) is below its Normal Storage, so V is the Normal Storage. Check the dam file.`;
  }
  const rangeNote =
    Number.isFinite(v) && v > 500_000
      ? "Over 500,000 ac-ft: well outside the range of the desk's empirical breach equations (fit to dams mostly under 50,000 ac-ft). Treat the result as indicative only."
      : null;
  return { value: v, chip, warning, rangeNote };
}

export const REQUIRED_FIELDS = ["heightFt", "storageAcFt", "lengthFt"] as const;
export const OPTIONAL_FIELDS = ["year", "drainageMi2"] as const;

/** Fields a filled record still needs before Next (required NID fields and the elevations). */
export function missingForNext(dam: DamRecord): string[] {
  const out: string[] = [];
  if (!Number.isFinite(dam.heightFt)) out.push("height");
  if (!Number.isFinite(dam.storageAcFt)) out.push("storage");
  if (!Number.isFinite(dam.lengthFt)) out.push("length");
  if (!Number.isFinite(dam.crestFt)) out.push("crest");
  if (!Number.isFinite(dam.streambedFt)) out.push("breach bottom");
  if (!dam.statedDatum) out.push("datum");
  return out;
}

export function nidRefFor(d: NidDam, src: NidSource): NidRef {
  return {
    nidHeightFt: d.nidHeightFt,
    damHeightFt: d.damHeightFt,
    structuralHeightFt: d.structuralHeightFt,
    hydraulicHeightFt: d.hydraulicHeightFt,
    nidStorageAcFt: d.nidStorageAcFt,
    maxStorageAcFt: d.maxStorageAcFt,
    normalStorageAcFt: d.normalStorageAcFt,
    surfaceAreaNormalAc: d.surfaceAreaNormalAc,
    river: d.river,
    city: d.city,
    purpose: d.purpose,
    damType: d.damType,
    nidUpdated: d.nidUpdated,
    lastInspection: d.lastInspection,
    eap: d.eap,
    countyNote: d.countyNote,
    downloaded: src.fetchedUtc.slice(0, 10),
    attribution: src.attribution,
  };
}

/** Labels for the confirm dialog, by DamRecord field. */
export const FIELD_LABEL: Record<string, string> = {
  name: "name",
  nid: "NID ID",
  county: "county",
  year: "year completed",
  lat: "latitude",
  lon: "longitude",
  heightFt: "dam height",
  lengthFt: "dam length",
  storageAcFt: "storage",
  drainageMi2: "drainage area",
  crestFt: "crest (cleared)",
  streambedFt: "breach bottom (cleared)",
  demCrestFt: "DEM crest (cleared)",
  statedDatum: "datum (cleared)",
  spillwayFt: "spillway crest (cleared)",
  normalPoolFt: "normal pool (cleared)",
  surfaceAreaAc: "surface area (cleared)",
  classOfRecord: "class of record (cleared)",
  isNew: "new dam flag (cleared)",
  geometry: "drawn dam, breach point and AOI (cleared)",
};

/**
 * Decision 6-8: the patch "Fill this record from the NID" applies, its provenance, and the replaced-field list.
 * Elevations are cleared (NaN, datum unset), never filled. When the record was a different dam, its drawn geometry,
 * class of record, notes and surface area are cleared too, so nothing from the previous dam carries over.
 */
export function prefillPatch(
  d: NidDam,
  data: Pick<NidData, "nidSource">,
  current?: DamRecord,
): { patch: Partial<DamRecord>; replaced: string[] } {
  const asOf = data.nidSource.fetchedUtc.slice(0, 10);
  const h = heightFor(d);
  const v = storageFor(d);
  const nan = Number.NaN;
  const prov: Record<string, Provenance> = {};
  const nidP = (field: string, value: number | string | null, note?: string): Provenance => ({ src: "NID", field, value, asOf, ...(note ? { note } : {}) });
  const name = d.name ?? d.otherNames ?? `Unnamed dam ${d.nid}`;
  prov.name = nidP(d.name ? "Dam Name" : d.otherNames ? "Other Names" : "Dam Name (blank)", name);
  prov.nid = nidP("NID ID", d.nid);
  prov.county = nidP("County", d.county);
  if (d.yearCompleted != null) prov.year = nidP("Year Completed", d.yearCompleted);
  if (d.lat != null) prov.lat = nidP("Latitude", d.lat);
  if (d.lon != null) prov.lon = nidP("Longitude", d.lon);
  if (Number.isFinite(h.value)) prov.heightFt = nidP("NID Height (Ft)", h.value, "NID Height (whole ft)");
  if (d.lengthFt != null) prov.lengthFt = nidP("Dam Length (Ft)", d.lengthFt);
  if (Number.isFinite(v.value)) prov.storageAcFt = nidP("NID Storage (Acre-Ft)", v.value, v.chip);
  if (d.drainageMi2 != null) prov.drainageMi2 = nidP("Drainage Area (Sq Miles)", d.drainageMi2);

  const patch: Partial<DamRecord> = {
    name,
    nid: d.nid,
    county: d.county,
    year: d.yearCompleted ?? nan,
    lat: d.lat ?? undefined,
    lon: d.lon ?? undefined,
    heightFt: h.value,
    lengthFt: d.lengthFt ?? nan,
    storageAcFt: v.value,
    drainageMi2: d.drainageMi2 ?? nan,
    crestFt: nan,
    streambedFt: nan,
    demCrestFt: nan,
    statedDatum: "",
    datumOffsetFt: undefined,
    datumNote: undefined,
    spillwayFt: nan,
    normalPoolFt: nan,
    nidId: d.nid,
    nidHazard: d.nidHazard ?? undefined,
    provenance: prov,
    nidRef: nidRefFor(d, data.nidSource),
  };
  const replaced = ["name", "nid", "county", "year", "lat", "lon", "heightFt", "lengthFt", "storageAcFt", "drainageMi2"];
  replaced.push("crestFt", "streambedFt", "demCrestFt", "statedDatum", "spillwayFt", "normalPoolFt");
  const otherDam = !current || (current.nidId ?? current.nid) !== d.nid;
  if (otherDam) {
    Object.assign(patch, {
      surfaceAreaAc: undefined,
      classOfRecord: undefined,
      // A different dam starts as an existing dam; "New dam" is never carried over or inferred.
      isNew: undefined,
      sampleNote: undefined,
      geometry: undefined,
      reachKm: undefined,
      // Real receptors (Nick 2026-10-31): a picked dam drops the generic demo seeds. In North Dakota it screens the
      // state's NG911 address points inside the flood strip (added automatically once looked up); elsewhere the user
      // adds receptors (the NID has no buildings).
      receptors: [],
      receptorSource: d.nid.toUpperCase().startsWith("ND") ? "nd911" : undefined,
      nd911AutoAdded: undefined,
      nd911: undefined,
      judgmentAsProbable: false,
      // A classify result belongs to the dam and receptors it was run on.
      hazardResult: undefined,
    } as Partial<DamRecord>);
    if (current?.surfaceAreaAc != null) replaced.push("surfaceAreaAc");
    if (current?.classOfRecord) replaced.push("classOfRecord");
    if (current?.isNew) replaced.push("isNew");
    if (current?.geometry) replaced.push("geometry");
  }
  return { patch, replaced };
}

/** The confirm dialog's text. */
export function confirmText(replaced: string[]): string {
  return `Fill this record from the NID? These fields will be replaced: ${replaced.map((f) => FIELD_LABEL[f] ?? f).join(", ")}.`;
}

// ---------------------------------------------------------------- provenance tags

export type FieldTag = { kind: "from" | "edited" | "missing" | "missing-optional"; text: string; original?: Provenance };
/** Tag for a field of a picked record: "from NID", "edited (NID: 28)", "not in NID: enter a value". */
export function fieldTag(dam: DamRecord, field: string): FieldTag | null {
  if (!dam.nidId) return null;
  const p = dam.provenance?.[field];
  const cur = (dam as unknown as Record<string, unknown>)[field];
  if (!p) {
    if ((REQUIRED_FIELDS as readonly string[]).includes(field) && !(typeof cur === "number" && Number.isFinite(cur)))
      return { kind: "missing", text: "not in NID: enter a value" };
    if ((OPTIONAL_FIELDS as readonly string[]).includes(field) && !(typeof cur === "number" && Number.isFinite(cur)))
      return { kind: "missing-optional", text: "not in NID" };
    return null;
  }
  const same = typeof p.value === "number" && typeof cur === "number" ? Math.abs(p.value - cur) < 1e-9 : p.value === cur;
  if (same) return { kind: "from", text: p.note ? `from ${p.src}: ${p.note}` : `from ${p.src}`, original: p };
  return { kind: "edited", text: `edited (${p.src}: ${p.value ?? "blank"})`, original: p };
}

/** Patch that restores a field to its source value. */
export function revertPatch(dam: DamRecord, field: string): Partial<DamRecord> {
  const p = dam.provenance?.[field];
  if (!p) return {};
  return { [field]: p.value ?? Number.NaN } as Partial<DamRecord>;
}

/** "Unlink NID": keep the values, drop the link, tags and NID reference. */
export function unlinkPatch(): Partial<DamRecord> {
  return { nidId: undefined, nidHazard: undefined, provenance: undefined, nidRef: undefined };
}

// ---------------------------------------------------------------- height warnings

/** W-H1 / W-H2 (warnings.ts catalogue): `id` is the code; `code`/`severity` make it a Warning too. */
export type HeightWarning = Warning & { id: "W-H1" | "W-H2"; code: "W-H1" | "W-H2"; useHeightFt?: number };

const heightWarning = (id: "W-H1" | "W-H2", text: string, useHeightFt?: number): HeightWarning =>
  useHeightFt == null ? { id, code: id, severity: "warn", text } : { id, code: id, severity: "warn", text, useHeightFt };

/**
 * W-H1, when the dam is picked: NID Height above the NID Dam Height by more than 0.5 ft -> offer "Use dam height Y";
 * NID Height equal to the structural height with no dam height -> H may be overstated.
 */
export function heightWarningOnPick(d: NidDam): HeightWarning | null {
  const nh = d.nidHeightFt;
  if (nh == null) return null;
  if (d.damHeightFt != null && nh - d.damHeightFt > 0.5)
    return heightWarning(
      "W-H1",
      `NID Height ${nh} ft is the largest of the NID's heights; the NID's Dam Height is ${d.damHeightFt} ft. H for breach is crest minus breach bottom, which may be closer to ${d.damHeightFt} ft.`,
      d.damHeightFt,
    );
  if (d.damHeightFt == null && d.structuralHeightFt != null && d.structuralHeightFt === nh)
    return heightWarning(
      "W-H1",
      `NID Height ${nh} ft equals the structural height and no dam height is reported; H may be overstated. Check it against the crest and breach bottom.`,
    );
  return null;
}

/**
 * W-H2, once crest and breach bottom are entered: D = crest - breach bottom vs H; warn when |D - H| > tol,
 * tol = max(1 ft, 5% of D), +0.5 ft when H is a rounded whole-foot NID value.
 */
export function heightWarningOnElevations(dam: DamRecord): HeightWarning | null {
  if (!dam.nidId || !Number.isFinite(dam.crestFt) || !Number.isFinite(dam.streambedFt) || !Number.isFinite(dam.heightFt))
    return null;
  const D = dam.crestFt - dam.streambedFt;
  const rounded = dam.provenance?.heightFt?.src === "NID" && dam.provenance.heightFt.value === dam.heightFt;
  const tol = Math.max(1, 0.05 * Math.abs(D)) + (rounded ? 0.5 : 0);
  if (Math.abs(D - dam.heightFt) <= tol) return null;
  return heightWarning(
    "W-H2",
    `Crest minus breach bottom is ${D.toFixed(2)} ft but H is ${dam.heightFt} ft (difference ${(D - dam.heightFt).toFixed(2)} ft, tolerance ${tol.toFixed(2)} ft). Check both; H drives the breach.`,
    Math.round(D * 100) / 100,
  );
}

// ---------------------------------------------------------------- elevations typed from a DEM

/**
 * "Typed from a DEM": crest and breach bottom the user read off a DEM (NAVD 88) and typed in, tagged "typed from DEM".
 * Nothing is sampled here, so the typed crest is NOT copied into demCrestFt: the engine's DEM-vs-crest check keeps
 * whatever DEM crest the record has and can still fire.
 */
export function demElevationsPatch(dam: DamRecord, crestFt: number, streambedFt: number, demName = "DEM"): Partial<DamRecord> {
  const asOf = new Date().toISOString().slice(0, 10);
  const p = (field: string, value: number): Provenance => ({ src: "DEM", field, value, asOf, note: `typed in (${demName})` });
  return {
    crestFt,
    streambedFt,
    statedDatum: "NAVD88",
    datumOffsetFt: undefined,
    provenance: {
      ...dam.provenance,
      crestFt: p("crest (typed from DEM)", crestFt),
      streambedFt: p("streambed (typed from DEM)", streambedFt),
    },
  };
}

export type DemTieOffer = {
  /** Patch to apply, or null when nothing should be written (no DEM crest, or a mismatch to review). */
  patch: Partial<DamRecord> | null;
  /** "local": 0-300 ft values shifted by the DEM crest offset; "as-is": values already look like NAVD 88. */
  mode: "local" | "as-is" | null;
  offsetFt: number | null;
  /** Set when the record crest and the DEM crest differ by more than 100 ft (after any local shift). */
  review: string | null;
  note: string;
};

/** Datum is blank or Local: the record elevations need a NAVD 88 tie before they mean anything absolute. */
export function needsDemTie(dam: DamRecord): boolean {
  return dam.statedDatum === "" || dam.statedDatum === "Local";
}

/**
 * Record-step DEM tie for a blank or local datum, the same rule as the Runner:
 * a crest of 0-300 ft is a local value and every elevation (crest, streambed, spillway, normal pool) is moved to
 * NAVD 88 by the offset DEM mid-crest minus record crest. A larger crest is taken as already NAVD 88-like; if it
 * is more than 100 ft from the DEM crest the tie is not offered and the record is flagged for review.
 */
export function demTieOffer(dam: DamRecord, demName = "DEM mid-crest"): DemTieOffer {
  const dem = dam.demCrestFt;
  const crest = dam.crestFt;
  if (!needsDemTie(dam)) return { patch: null, mode: null, offsetFt: null, review: null, note: "Datum is stated; no DEM tie needed." };
  if (!Number.isFinite(dem) || !Number.isFinite(crest))
    return { patch: null, mode: null, offsetFt: null, review: null, note: "Needs a record crest and a DEM crest to tie." };
  const round2 = (v: number) => Math.round(v * 100) / 100;
  const local = crest >= 0 && crest <= 300;
  const offsetFt = local ? round2(dem - crest) : 0;
  const tiedCrest = round2(crest + offsetFt);
  const mismatch = Math.abs(tiedCrest - dem);
  if (mismatch > 100) {
    return {
      patch: null,
      mode: "as-is",
      offsetFt: null,
      review: `Record crest ${crest} ft is ${round2(mismatch)} ft from the DEM crest ${dem} ft (over 100 ft): review the datum before tying.`,
      note: "Not tied.",
    };
  }
  const shift = (v: number) => (Number.isFinite(v) ? round2(v + offsetFt) : v);
  const base = demElevationsPatch(dam, tiedCrest, shift(dam.streambedFt), demName);
  const asOf = new Date().toISOString().slice(0, 10);
  const why = local
    ? `local ${dam.statedDatum === "" ? "(blank datum) " : ""}value + ${offsetFt} ft (DEM mid-crest ${dem} − record crest ${crest})`
    : `blank/local datum but value already NAVD 88-like (within ${round2(mismatch)} ft of the DEM crest)`;
  const prov = (field: string, value: number): Provenance => ({ src: "DEM", field, value, asOf, note: `DEM tie: ${why}` });
  const patch: Partial<DamRecord> = {
    ...base,
    spillwayFt: shift(dam.spillwayFt),
    normalPoolFt: shift(dam.normalPoolFt),
    provenance: {
      ...base.provenance,
      crestFt: prov("crest (DEM-tied)", tiedCrest),
      streambedFt: prov("streambed (DEM-tied)", shift(dam.streambedFt)),
    },
  };
  return { patch, mode: local ? "local" : "as-is", offsetFt, review: null, note: `Tie: ${why}.` };
}

/** NID hazard line on Record and Screen. Neutral; not used by the screen. */
export function nidHazardLine(h: NidHazard | undefined): string | null {
  return h ? `NID hazard (as reported to the NID, FEMA class): ${h}` : null;
}

export const NID_ATTRIBUTION_FALLBACK =
  "Dam inventory data: U.S. Army Corps of Engineers, National Inventory of Dams (nid.sec.usace.army.mil).";
