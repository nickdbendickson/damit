import type { Bbox } from "./plss.ts";
import { padBbox, stripBbox } from "./plss.ts";
import type { FloodStrip } from "./floodstrip.ts";
import type { DamRecord } from "./types.ts";
import type { Nd911Cache, Nd911Point } from "./nd911.ts";

/**
 * USACE National Structure Inventory (NSI) structures near the flood strip: the receptor source for every dam outside
 * North Dakota (nid-dams.ts sets receptorSource "nsi" for them; ND dams keep the ND NG911 address points).
 *
 * Source: the public NSI API (https://nsi.sec.usace.army.mil/nsiapi/structures), queried on request by the strip's
 * padded bounding box, GeoJSON out. The structures come back as points and are saved on the dam record in the same
 * cache shape as the 911 points (dam.nd911), so the list, the map, "Add for review", the pads and the exports all work
 * the same way and offline afterwards. Nothing national is bundled.
 *
 * Kept per structure: its NSI id, occupancy type and damage category, building type, stories, year built,
 * foundation height and type, and the NSI's day / night population estimates (under and over 65), shown in the list
 * as "about N people at night". The NSI has no address, owner or occupant name, so nothing personal is kept.
 * NSI values are modelled estimates (USACE), not a survey: the desk shows them for review, never as a count of
 * record.
 */

export const NSI_API = "https://nsi.sec.usace.army.mil/nsiapi/structures";
export const NSI_ATTRIBUTION =
  "Structures: USACE National Structure Inventory (NSI), nsi.sec.usace.army.mil. Public data; occupancy, foundation height and population are modelled estimates, not a survey.";
export const NSI_ATTRIBUTION_SHORT = "Structures: USACE NSI";
export const NSI_OFFLINE =
  "NSI structures need a connection: look them up once while online (USACE National Structure Inventory), and they are saved with this dam for offline use.";
/** Id prefix that marks a cached point as an NSI structure (its nguid). */
export const NSI_ID_PREFIX = "NSI-";
/** One request covers at most this many square degrees (the API refuses very large boxes). */
export const NSI_MAX_DEG2 = 1.0;
/** Pad around the strip's box, m (same as the 911 lookup). */
export const NSI_PAD_M = 250;

/** Properties read from each NSI feature (anything else the API sends is ignored). */
export const NSI_FIELDS = [
  "fd_id",
  "occtype",
  "st_damcat",
  "bldgtype",
  "num_story",
  "med_yr_blt",
  "found_ht",
  "found_type",
  "pop2amu65",
  "pop2amo65",
  "pop2pmu65",
  "pop2pmo65",
  "source",
] as const;

const BLDG: Record<string, string> = { W: "wood", M: "masonry", C: "concrete", S: "steel", H: "manufactured" };
const DAMCAT: Record<string, string> = { RES: "residential", COM: "commercial", IND: "industrial", PUB: "public" };

type Fetch = (url: string, init?: { signal?: AbortSignal }) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;
type NsiFeature = { properties?: Record<string, unknown> | null; geometry?: { type: string; coordinates: unknown } | null };

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : undefined);
const str = (v: unknown) => (v == null ? "" : String(v).trim());
const r6 = (n: number) => Math.round(n * 1e6) / 1e6;

/** The API's bbox parameter: the box as a closed ring of lon,lat pairs. */
export function nsiQueryUrl(bbox: Bbox): string {
  const [x0, y0, x1, y1] = bbox.map((v) => Math.round(v * 1e6) / 1e6);
  const ring = [x0, y0, x1, y0, x1, y1, x0, y1, x0, y0].join(",");
  return `${NSI_API}?bbox=${ring}&fmt=fc`;
}

/** A short description of one structure for the list: "residential (RES1-1SWB), wood, 1 story, about 2 people at night". */
export function nsiLabel(p: Pick<Nd911Point, "placeType" | "placement" | "stories" | "building" | "popNight" | "popDay">): string {
  const parts = [`${DAMCAT[p.placement] ?? (p.placement.toLowerCase() || "structure")}${p.placeType ? ` (${p.placeType})` : ""}`];
  if (p.building) parts.push(p.building);
  if (p.stories) parts.push(`${p.stories} stor${p.stories === 1 ? "y" : "ies"}`);
  if (p.popNight != null || p.popDay != null) {
    const night = p.popNight ?? 0;
    const day = p.popDay ?? 0;
    parts.push(`about ${night} ${night === 1 ? "person" : "people"} at night, ${day} by day`);
  }
  return parts.join(", ");
}

/** NSI features to cached points (the 911 cache shape, so the rest of the desk is unchanged). */
export function readNsiPoints(features: NsiFeature[]): Nd911Point[] {
  const out: Nd911Point[] = [];
  for (const f of features) {
    const g = f.geometry;
    if (!g || g.type !== "Point" || !Array.isArray(g.coordinates)) continue;
    const [lon, lat] = g.coordinates as number[];
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const p = f.properties ?? {};
    const id = str(p.fd_id);
    const stories = num(p.num_story);
    const popNight = (num(p.pop2amu65) ?? 0) + (num(p.pop2amo65) ?? 0);
    const popDay = (num(p.pop2pmu65) ?? 0) + (num(p.pop2pmo65) ?? 0);
    const havePop = [p.pop2amu65, p.pop2amo65, p.pop2pmu65, p.pop2pmo65].some((v) => num(v) != null);
    const pt: Nd911Point = {
      nguid: `${NSI_ID_PREFIX}${id || `${r6(lon)}_${r6(lat)}`}`,
      address: "",
      street: "",
      unit: "",
      community: "",
      state: "",
      zip: "",
      county: "",
      municipality: "",
      msagCommunity: "",
      placeType: str(p.occtype),
      placement: str(p.st_damcat).toUpperCase(),
      milePost: "",
      agency: "USACE NSI",
      source: str(p.source),
      accuracy: "",
      updated: "",
      lon: r6(lon),
      lat: r6(lat),
      building: BLDG[str(p.bldgtype).toUpperCase()] ?? "",
      stories: stories != null && stories > 0 ? Math.round(stories) : undefined,
      yearBuilt: num(p.med_yr_blt),
      foundHtFt: num(p.found_ht),
      foundType: str(p.found_type),
      popDay: havePop ? Math.round(popDay) : undefined,
      popNight: havePop ? Math.round(popNight) : undefined,
    };
    pt.address = `${nsiLabel(pt)} (NSI ${id || "no id"})`;
    out.push(pt);
  }
  return out;
}

/** Box a lookup covers for `area`: its box grown by NSI_PAD_M. */
export const nsiBbox = (area: FloodStrip): Bbox => padBbox(stripBbox(area), NSI_PAD_M);

/** One on-request lookup: every NSI structure in the box. Throws with a readable message. */
export async function fetchNsi(
  area: FloodStrip | Bbox,
  fetchFn: Fetch = fetch as unknown as Fetch,
  now = new Date(),
): Promise<Nd911Cache> {
  const bbox = Array.isArray(area) ? area : nsiBbox(area);
  const deg2 = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]);
  if (deg2 > NSI_MAX_DEG2) {
    throw new Error(`NSI structure lookup refused: the box is ${deg2.toFixed(2)} square degrees (at most ${NSI_MAX_DEG2}); draw a smaller area.`);
  }
  const ctl = typeof AbortController === "undefined" ? null : new AbortController();
  const timer = ctl ? setTimeout(() => ctl.abort(), 60_000) : null;
  let body: { features?: NsiFeature[]; error?: string | { message?: string } } | null;
  try {
    const res = await fetchFn(nsiQueryUrl(bbox), ctl ? { signal: ctl.signal } : undefined);
    if (!res.ok) throw new Error(`the NSI service answered HTTP ${res.status}`);
    body = (await res.json()) as typeof body;
  } catch (e) {
    const msg = (e as Error).name === "AbortError" ? "the NSI service did not answer in 60 s" : (e as Error).message;
    throw new Error(`NSI structure lookup failed: ${msg}. ${NSI_OFFLINE}`);
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (body && body.error) {
    const m = typeof body.error === "string" ? body.error : body.error.message ?? "service error";
    throw new Error(`NSI structure lookup failed: ${m}.`);
  }
  const seen = new Set<string>();
  const points = readNsiPoints(body?.features ?? []).filter((p) => (seen.has(p.nguid) ? false : (seen.add(p.nguid), true)));
  return { source: NSI_API, attribution: NSI_ATTRIBUTION, fetchedAt: now.toISOString(), bbox, fields: [...NSI_FIELDS], points };
}

/** "nsi" when this dam's structures come from the NSI (its receptor source, or the saved lookup), else "nd911". */
export function structureSource(dam: Pick<DamRecord, "receptorSource" | "nd911">): "nsi" | "nd911" {
  if (dam.nd911?.source === NSI_API) return "nsi";
  return dam.receptorSource === "nsi" ? "nsi" : "nd911";
}
