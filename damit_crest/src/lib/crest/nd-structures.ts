/**
 * The North Dakota profile's structure list (profile.ts): the NID main dams with their DWR values (nd-dams.ts), plus
 * every other DWR dam, every DWR dugout and the DWR Unknown Structures from data/nd_structures.json (built in
 * dwr_crest by scripts/build-nd-structures.mjs; carried here unchanged). Brought over from dwr_crest's batch.ts when
 * damit-desk became the one desk (Nick, 2026-11-22); the US batch (batch.ts) lists NID dams only and never loads this.
 *
 * ndInventory() gives batch.ts the two hooks it needs for these rows (InventoryHooks): the record (NID prefill with the
 * DWR values, or the DWR numbers with "DWR" provenance), and the crest from DWR's NAVD 88 elevations where the bundle
 * offers them (dwrElevationOffer), else the terrain as for any NID dam.
 */
import { blankDam } from "./samples.ts";
import { loadBundle } from "./data-bundle.ts";
import { applyDwrElevationsPatch, dwrElevationOffer, heightFor, loadNdData, prefillPatch, storageFor, type NdData } from "./nd-dams.ts";
import type { InventoryHooks, Structure } from "./batch.ts";
import type { DamRecord, Provenance } from "./types.ts";

type Table = { cols: string[]; rows: unknown[][] };
export type StructuresBundle = Table & { source: Record<string, unknown>; nidHuc: Table };

const decode = <T>(b: Table): T[] => b.rows.map((r) => Object.fromEntries(b.cols.map((c, i) => [c, r[i] ?? null])) as T);

/** DWR statuses that have (or may have) an embankment standing to breach; the rest are listed but off by default.
 *  "Unknown" is the status of most DWR Unknown Structures (blank in DWR's table). */
export const ND_DEFAULT_STATUSES = ["NID", "Intact", "Dugout", "Pending", "Under Construction", "Unknown"] as const;
export const ND_KINDS = ["nid", "dam", "dugout", "unknown"] as const;

/**
 * One list from the NID bundle (main dams; the picker's DWR-only entries are replaced by the full DWR list) and the
 * structures bundle (every other DWR dam, every dugout, the unknown structures).
 */
export function makeNdStructures(nd: Pick<NdData, "dams" | "dwr">, bundle: StructuresBundle): Structure[] {
  const huc = new Map(decode<{ nid: string; huc8: string | null; alias?: string | null }>(bundle.nidHuc).map((h) => [h.nid, h]));
  const nid: Structure[] = nd.dams
    .filter((d) => d.source !== "DWR")
    .map((d) => {
      const dwr = nd.dwr.get(d.nid);
      const h = heightFor(d, dwr);
      const v = storageFor(d);
      const w = huc.get(d.nid);
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
        areaAc: dwr?.maxPoolAreaAc ?? null,
        lengthFt: d.lengthFt,
        year: d.yearCompleted,
        hazard: d.nidHazard ?? null,
        purpose: d.purpose,
        huc8: w?.huc8 ?? null,
        alias: w?.alias ?? null,
      } satisfies Structure;
    });
  type Row = Omit<Structure, "label" | "kind"> & { kind: "dam" | "dugout" | "unknown" };
  const rest: Structure[] = decode<Row>(bundle).map((r) => {
    const also = [r.nid, ...(r.alias ? r.alias.split(" ") : [])].filter(Boolean);
    return { ...r, label: `${r.id}${also.length ? ` (${also.join(", ")})` : ""}` };
  });
  return [...nid, ...rest];
}

export type LoadedNdStructures = { nd: NdData; structures: Structure[]; source: Record<string, unknown> };
let cache: Promise<LoadedNdStructures> | null = null;
/** Load the bundles once (separate chunks, never part of the first paint; packed inside the one-file DamIT.html). */
export function loadNdStructures(): Promise<LoadedNdStructures> {
  cache ??= Promise.all([loadNdData(), loadBundle<StructuresBundle>("nd_structures")]).then(([nd, bundle]) => ({
    nd,
    structures: makeNdStructures(nd, bundle),
    source: bundle.source,
  }));
  cache.catch(() => (cache = null));
  return cache;
}

/**
 * The record's inventory fields for a structure, elevations left blank (as the NID picker leaves them): the NID dam's
 * own prefill with its DWR values, or the DWR numbers with "DWR" provenance.
 */
export function ndStructureRecord(s: Structure, nd: Pick<NdData, "byNid" | "dwr" | "nidSource" | "dwrSource"> | undefined, id = `batch-${s.id.toLowerCase()}`): DamRecord {
  const asOf = new Date().toISOString().slice(0, 10);
  const base = blankDam();
  let dam: DamRecord;
  const ndDam = s.kind === "nid" ? nd?.byNid.get(s.id) : undefined;
  if (ndDam && nd) {
    const { patch } = prefillPatch(ndDam, nd);
    dam = { ...base, ...patch, id };
  } else {
    const prov = (field: string, value: number | string | null): Provenance => ({
      src: "DWR",
      field,
      value,
      asOf,
      note: s.kind === "dugout" ? "DWR Dugouts layer" : s.kind === "unknown" ? "DWR Unknown Structures (DWR export)" : "DWR Dams layer",
    });
    const provenance: Record<string, Provenance> = {
      heightFt: prov(s.kind === "dugout" ? "max_height" : s.kind === "unknown" ? "max_dam_height" : "max_dam_he", s.heightFt),
      storageAcFt: prov(s.kind === "dugout" ? "max_storag" : s.kind === "unknown" ? "max_pool_vol" : "max_pool_v", s.storageAcFt),
    };
    dam = {
      ...base,
      id,
      name: s.label,
      nid: s.id,
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
      receptorSource: "nd911",
      judgmentAsProbable: false,
      provenance,
    };
  }
  if (s.areaAc != null && dam.surfaceAreaAc == null) dam.surfaceAreaAc = s.areaAc;
  return dam;
}

/** The batch hooks for the ND list: the record above, and the crest from DWR NAVD 88 where the bundle offers it. */
export function ndInventory(nd: Pick<NdData, "byNid" | "dwr" | "nidSource" | "dwrSource">): InventoryHooks {
  return {
    record: (s, id) => ndStructureRecord(s, nd, id),
    crest: (s, dam, asOf) => {
      const dwr = nd.dwr.get(s.id);
      if (!dwr || !dwrElevationOffer(dwr).ok) return null;
      return { ...dam, ...applyDwrElevationsPatch(dam, dwr, asOf) };
    },
  };
}
