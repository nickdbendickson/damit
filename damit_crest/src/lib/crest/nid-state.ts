/**
 * The NID dam inventory, one state at a time (USACE National Inventory of Dams; no other dam list is used).
 *
 * North Dakota ships as a small committed example extract (data/nid_ND.json) so the desk and the tests work offline.
 * Every state (North Dakota included, when the user asks for the latest) is downloaded by the desktop server from the
 * NID's bulk CSV for that state, `https://nid.sec.usace.army.mil/api/query?sy=@stateKey:<XX>&out=csv`, converted to
 * the same bundle format and cached in the app's settings folder (GET /api/nid/state?state=XX[&refresh=1]). No
 * per-dam NID API calls; "Owner Names" are never read.
 */
import { crestApiHeaders } from "./desktop-server.ts";
import { loadNidData, makeNidData, type NidBundle, type NidData } from "./nid-dams.ts";

/** State / territory codes the NID uses (stateKey), with names. */
export const NID_STATES: ReadonlyArray<readonly [string, string]> = [
  ["AL", "Alabama"], ["AK", "Alaska"], ["AZ", "Arizona"], ["AR", "Arkansas"], ["CA", "California"],
  ["CO", "Colorado"], ["CT", "Connecticut"], ["DE", "Delaware"], ["DC", "District of Columbia"], ["FL", "Florida"],
  ["GA", "Georgia"], ["HI", "Hawaii"], ["ID", "Idaho"], ["IL", "Illinois"], ["IN", "Indiana"], ["IA", "Iowa"],
  ["KS", "Kansas"], ["KY", "Kentucky"], ["LA", "Louisiana"], ["ME", "Maine"], ["MD", "Maryland"],
  ["MA", "Massachusetts"], ["MI", "Michigan"], ["MN", "Minnesota"], ["MS", "Mississippi"], ["MO", "Missouri"],
  ["MT", "Montana"], ["NE", "Nebraska"], ["NV", "Nevada"], ["NH", "New Hampshire"], ["NJ", "New Jersey"],
  ["NM", "New Mexico"], ["NY", "New York"], ["NC", "North Carolina"], ["ND", "North Dakota"], ["OH", "Ohio"],
  ["OK", "Oklahoma"], ["OR", "Oregon"], ["PA", "Pennsylvania"], ["RI", "Rhode Island"], ["SC", "South Carolina"],
  ["SD", "South Dakota"], ["TN", "Tennessee"], ["TX", "Texas"], ["UT", "Utah"], ["VT", "Vermont"],
  ["VA", "Virginia"], ["WA", "Washington"], ["WV", "West Virginia"], ["WI", "Wisconsin"], ["WY", "Wyoming"],
  ["PR", "Puerto Rico"], ["GU", "Guam"], ["VI", "U.S. Virgin Islands"], ["AS", "American Samoa"],
  ["MP", "Northern Mariana Islands"],
];

/** The state whose extract is committed (offline example). */
export const EXAMPLE_STATE = "ND";

export function isNidState(code: unknown): code is string {
  return typeof code === "string" && NID_STATES.some(([c]) => c === code);
}

export function stateName(code: string): string {
  return NID_STATES.find(([c]) => c === code)?.[1] ?? code;
}

const cache = new Map<string, Promise<NidData>>();

export type LoadStateOptions = { refresh?: boolean; fetchImpl?: typeof fetch };

/**
 * One state's NID dams. The example state comes from the committed extract unless `refresh` asks the server for the
 * latest; every other state comes from the desktop server (which downloads and caches it). Rejects with a message
 * when there is no server or the NID download fails.
 */
export function loadNidState(code: string, opts: LoadStateOptions = {}): Promise<NidData> {
  const state = String(code || "").toUpperCase();
  if (!isNidState(state)) return Promise.reject(new Error(`${code} is not an NID state or territory code.`));
  const key = state;
  const hit = cache.get(key);
  if (hit && !opts.refresh) return hit;
  // The example state is the committed extract until "Download latest" fetches a fresh copy (then that one is kept).
  if (state === EXAMPLE_STATE && !opts.refresh) return loadNidData();
  const f = opts.fetchImpl ?? fetch;
  const p = (async () => {
    let res: Response;
    try {
      res = await f(`/api/nid/state?state=${state}${opts.refresh ? "&refresh=1" : ""}`, { headers: crestApiHeaders() });
    } catch {
      throw new Error(
        `The ${stateName(state)} NID extract needs the DamIT Crest desktop server (python run.py), which downloads it from the NID.`,
      );
    }
    const body = (await res.json().catch(() => null)) as (NidBundle & { error?: string }) | null;
    if (!res.ok || !body || !Array.isArray(body.rows)) throw new Error(body?.error ?? `NID download for ${state} failed (HTTP ${res.status}).`);
    return makeNidData(body);
  })();
  cache.set(key, p);
  p.catch(() => cache.delete(key));
  return p;
}

/** Remembered choice (local to this browser profile). */
const KEY = "damit-nid-state";
export function rememberedState(): string {
  try {
    const v = typeof localStorage === "undefined" ? null : localStorage.getItem(KEY);
    return isNidState(v) ? v : EXAMPLE_STATE;
  } catch {
    return EXAMPLE_STATE;
  }
}
export function rememberState(code: string): void {
  try {
    if (isNidState(code) && typeof localStorage !== "undefined") localStorage.setItem(KEY, code);
  } catch {
    // private mode: not remembered
  }
}
