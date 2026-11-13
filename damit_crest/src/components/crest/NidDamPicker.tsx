/**
 * NID dam picker (State -> County -> Dam) and the NID panel on the Record step.
 *
 * The dam inventory is the USACE National Inventory of Dams only. North Dakota's extract ships with the app as an
 * offline example; any state (and the latest North Dakota) is downloaded by the desktop server from the NID's bulk
 * CSV for that state and cached in the settings folder (nid-state.ts). A proposed dam that is not in the NID yet is a
 * blank record with "New dam" ticked and no NID ID.
 */
import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  confirmText,
  countyOptions,
  damOptionLabel,
  demElevationsPatch,
  elevationNote,
  fieldTag,
  heightWarningOnElevations,
  heightWarningOnPick,
  newRecordPatch,
  type NidDam,
  type NidData,
  nidHazardLine,
  prefillPatch,
  revertPatch,
  searchDams,
  storageFor,
  unlinkPatch,
} from "@/lib/crest/nid-dams";
import { EXAMPLE_STATE, isNidState, loadNidState, NID_STATES, rememberedState, rememberState, stateName } from "@/lib/crest/nid-state";
import { deskBundles, staleBundleBanner } from "@/lib/crest/data-provenance";
import { blankDam } from "@/lib/crest/samples";
import { applyDefaults } from "@/lib/crest/settings";
import { sharedNow } from "@/lib/crest/settings-store";
import { useDesk } from "@/lib/crest/store";
import type { DamRecord } from "@/lib/crest/types";

const MAX_OPTIONS = 60;

/**
 * Amber line when an inventory bundle is past BUNDLE_STALE_DAYS (data-provenance.ts). `now` is read once per mount, in
 * an effect, so the server render and the first client render agree (no banner), as use-online.ts does for the clock.
 */
export function StaleBundleBanner({ data, className = "mt-2" }: { data: NidData | null; className?: string }) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => setNow(new Date()), []);
  if (!data || !now) return null;
  const text = staleBundleBanner(deskBundles({ nidFetchedUtc: data.nidSource.fetchedUtc, state: data.state }), now);
  if (!text) return null;
  return (
    <p className={`${className} rounded-sm border border-amber bg-amber/10 p-2 text-xs text-amber`} role="status" data-testid="bundle-stale">
      {text}
    </p>
  );
}

// ---------------------------------------------------------------- the chosen state (shared by the panels)

const listeners = new Set<() => void>();
let selectedState = EXAMPLE_STATE;
let restored = false;
function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function selectNidState(code: string): void {
  if (!isNidState(code) || code === selectedState) return;
  selectedState = code;
  rememberState(code);
  listeners.forEach((l) => l());
}
/** The state the picker shows; the last choice in this browser profile, else the bundled example (North Dakota). */
export function useSelectedNidState(): string {
  const v = useSyncExternalStore(subscribe, () => selectedState, () => EXAMPLE_STATE);
  useEffect(() => {
    if (restored) return;
    restored = true;
    const r = rememberedState();
    if (r !== selectedState) {
      selectedState = r;
      listeners.forEach((l) => l());
    }
  }, []);
  return v;
}

/**
 * One state's NID extract, loaded on first use: the chosen state, or `state` when given (a record's own state, from
 * its NID ID). `reload()` asks the desktop server for the latest download.
 */
export function useNidData(
  enabled = true,
  state?: string,
): { data: NidData | null; error: string | null; loading: boolean; reload: () => void } {
  const chosen = useSelectedNidState();
  const want = state && isNidState(state) ? state : chosen;
  const [data, setData] = useState<NidData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setError(null);
    setLoading(true);
    setData((d) => (d && d.state === want ? d : null));
    loadNidState(want, { refresh: refresh > 0 }).then(
      (d) => {
        if (!live) return;
        setData(d);
        setLoading(false);
      },
      (e: unknown) => {
        if (!live) return;
        setError(`Could not load the NID dams for ${stateName(want)}: ${(e as Error).message}`);
        setLoading(false);
      },
    );
    return () => {
      live = false;
    };
  }, [enabled, want, refresh]);
  return { data, error, loading, reload: () => setRefresh((n) => n + 1) };
}

export function NidDamPicker({ dam }: { dam: DamRecord }) {
  const state = useSelectedNidState();
  const { data, error, loading, reload } = useNidData();
  const update = useDesk((s) => s.update);
  const addDam = useDesk((s) => s.addDam);
  const [county, setCounty] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<NidDam | null>(null);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  const counties = useMemo(() => (data ? countyOptions(data.dams) : []), [data]);
  const results = useMemo(() => (data ? searchDams(data.dams, query, county) : []), [data, query, county]);
  const shown = results.slice(0, MAX_OPTIONS);
  const confirm = useMemo(() => (picked && data ? prefillPatch(picked, data, dam) : null), [picked, data, dam]);

  const choose = (d: NidDam) => {
    setPicked(d);
    setOpen(false);
    setQuery(d.name ?? d.otherNames ?? d.nid);
  };
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, shown.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && shown[active]) {
      e.preventDefault();
      choose(shown[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="rounded-md border border-line bg-paper p-3">
      <p className="text-sm font-medium">Fill from the NID (National Inventory of Dams)</p>
      {error ? <p className="mt-1 text-sm text-amber">{error}</p> : null}
      <div className="mt-2 grid gap-3 sm:grid-cols-[180px_200px_1fr]">
        <label className="block text-sm">
          <span className="text-muted">State</span>
          <select
            value={state}
            data-testid="nid-state"
            onChange={(e) => {
              selectNidState(e.target.value);
              setCounty("");
              setQuery("");
              setPicked(null);
            }}
            className="mt-1 h-11 w-full rounded-sm border border-line bg-card px-3 text-ink"
          >
            {NID_STATES.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
                {code === EXAMPLE_STATE ? " (bundled example)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-muted">County</span>
          <select
            value={county}
            disabled={!data}
            onChange={(e) => {
              setCounty(e.target.value);
              setActive(0);
            }}
            className="mt-1 h-11 w-full rounded-sm border border-line bg-card px-3 text-ink"
          >
            <option value="">All counties ({data?.dams.length ?? "…"})</option>
            {counties.map((c) => (
              <option key={c.county} value={c.county}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <div className="relative text-sm">
          <label htmlFor={`${listId}-input`} className="text-muted">
            Dam (name, other name or NID ID)
          </label>
          <input
            id={`${listId}-input`}
            ref={inputRef}
            role="combobox"
            aria-expanded={open && shown.length > 0}
            aria-controls={`${listId}-list`}
            aria-autocomplete="list"
            aria-activedescendant={open && shown[active] ? `${listId}-opt-${active}` : undefined}
            disabled={!data}
            value={query}
            placeholder={data ? `name, other name or NID ID (e.g. ${data.dams[0]?.nid ?? "ND00199"})` : loading ? `Loading the ${stateName(state)} NID dams…` : "No dam list loaded"}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setActive(0);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            onKeyDown={onKey}
            className="mt-1 h-11 w-full rounded-sm border border-line bg-card px-3 text-ink"
          />
          {open && data ? (
            <ul
              id={`${listId}-list`}
              role="listbox"
              aria-label="NID dams"
              className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-sm border border-line bg-card shadow"
            >
              {shown.map((d, i) => (
                <li
                  key={d.nid}
                  id={`${listId}-opt-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(d);
                  }}
                  onMouseEnter={() => setActive(i)}
                  className={"cursor-pointer px-3 py-2 " + (i === active ? "bg-sand" : "")}
                >
                  {damOptionLabel(d)}
                </li>
              ))}
              {results.length === 0 ? <li className="px-3 py-2 text-muted">No dam matches.</li> : null}
              {results.length > shown.length ? (
                <li className="px-3 py-2 text-muted">{results.length - shown.length} more; type more to narrow.</li>
              ) : null}
            </ul>
          ) : null}
        </div>
      </div>
      {picked && confirm && data ? (
        <div role="alertdialog" aria-label="Fill from the NID" className="mt-3 rounded-sm border border-line bg-card p-3 text-sm">
          <p>{confirmText(confirm.replaced)}</p>
          <p className="mt-1 text-muted">
            {damOptionLabel(picked)}. {elevationNote(confirm.replaced)}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              className="h-10 rounded-sm border border-water bg-water px-3 text-card"
              onClick={() => {
                update(confirm.patch);
                setPicked(null);
              }}
            >
              Apply to this record
            </button>
            <button
              type="button"
              className="h-10 rounded-sm border border-line bg-paper px-3"
              onClick={() => {
                const patch = newRecordPatch(picked, data, dam);
                const base = applyDefaults(blankDam(), sharedNow().values);
                addDam({ ...base, ...patch, id: `nid-${picked.nid.toLowerCase()}-${base.id.slice(5)}` });
                setPicked(null);
              }}
            >
              New record from NID
            </button>
            <button type="button" className="h-10 rounded-sm px-3 text-muted" onClick={() => setPicked(null)}>
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      <StaleBundleBanner data={data} />
      <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>
          {data ? `${data.dams.length} NID dams, ${stateName(data.state || state)}. ${data.nidSource.attribution}` : "Dam inventory data: U.S. Army Corps of Engineers, National Inventory of Dams."}
        </span>
        <button type="button" className="underline" disabled={loading} onClick={reload} data-testid="nid-refresh">
          {loading ? "Downloading…" : "Download latest from the NID"}
        </button>
      </p>
      <p className="mt-1 text-xs text-muted">
        A proposed dam that is not in the NID yet: add a new dam, tick New dam and leave the NID field empty.
      </p>
    </div>
  );
}

/** "from NID" / "edited (NID: x)" + revert / "not in NID: enter a value". */
export function FieldTag({ dam, field }: { dam: DamRecord; field: string }) {
  const update = useDesk((s) => s.update);
  const t = fieldTag(dam, field);
  if (!t) return null;
  const cls =
    t.kind === "missing"
      ? "text-red-700"
      : t.kind === "edited"
        ? "text-amber"
        : "text-muted";
  return (
    <span className={`mt-1 flex flex-wrap items-center gap-2 text-xs ${cls}`}>
      {t.text}
      {t.kind === "edited" ? (
        <button type="button" className="underline" onClick={() => update(revertPatch(dam, field))}>
          revert
        </button>
      ) : null}
    </span>
  );
}

export function NidHazardLine({ dam }: { dam: DamRecord }) {
  const line = nidHazardLine(dam.nidHazard);
  if (!line) return null;
  return (
    <p className="mt-2 inline-block rounded-sm border border-line bg-paper px-2 py-1 text-xs text-muted" data-testid="nid-hazard">
      {line}. Not used by the desk screen.
    </p>
  );
}

/** Banners, the NID facts box and "unlink NID" for a record filled from the NID. */
export function NidRecordPanel({ dam }: { dam: DamRecord }) {
  // The record's own state (from its NID ID), not necessarily the one the picker shows.
  const { data } = useNidData(Boolean(dam.nidId), dam.nidId?.slice(0, 2).toUpperCase());
  const update = useDesk((s) => s.update);
  const [demCrest, setDemCrest] = useState("");
  const [demBed, setDemBed] = useState("");
  if (!dam.nidId) return null;
  const nd = data?.byNid.get(dam.nidId);
  const elevMissing = !Number.isFinite(dam.crestFt) || !Number.isFinite(dam.streambedFt) || !dam.statedDatum;
  const w1 = nd ? heightWarningOnPick(nd) : null;
  const w2 = heightWarningOnElevations(dam);
  const storage = nd ? storageFor(nd) : null;
  const r = dam.nidRef;
  const fmt = (v: number | null | undefined, u = "") => (v == null ? "—" : `${v.toLocaleString("en-US")}${u}`);
  const demOk = demCrest !== "" && demBed !== "" && Number.isFinite(Number(demCrest)) && Number.isFinite(Number(demBed));
  // Typed values only reach the record on the button; say so while they differ from what the record holds.
  const demPending =
    (demCrest !== "" && Number(demCrest) !== dam.crestFt) || (demBed !== "" && Number(demBed) !== dam.streambedFt);

  return (
    <div className="space-y-3">
      {elevMissing ? (
        <div className="rounded-sm border border-amber bg-amber/10 p-3 text-sm" role="status" data-testid="elev-banner">
          <p className="font-medium text-amber">Elevations are not in the NID.</p>
          <p className="mt-1">
            Enter the crest (top of dam) and breach bottom and choose their datum before going on. Next stays off until
            they are in; the engine shows Review (elevations missing) and runs no flood.
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <label className="block">
              <span className="text-muted">Crest typed from a DEM (ft NAVD88)</span>
              <input
                type="number"
                step={0.01}
                value={demCrest}
                onChange={(e) => setDemCrest(e.target.value)}
                className="mt-1 h-10 w-full rounded-sm border border-line bg-paper px-2 tabular-nums"
              />
            </label>
            <label className="block">
              <span className="text-muted">Breach bottom typed from a DEM (ft NAVD88)</span>
              <input
                type="number"
                step={0.01}
                value={demBed}
                onChange={(e) => setDemBed(e.target.value)}
                className="mt-1 h-10 w-full rounded-sm border border-line bg-paper px-2 tabular-nums"
              />
            </label>
            <button
              type="button"
              disabled={!demOk}
              onClick={() => update(demElevationsPatch(dam, Number(demCrest), Number(demBed)))}
              className="h-10 rounded-sm border border-line bg-card px-3 disabled:opacity-50"
            >
              Use typed DEM values
            </button>
          </div>
          {demPending ? (
            <p className="mt-1 text-xs text-amber" data-testid="dem-typed-pending">
              Not applied yet. Click Use typed DEM values to put these in the record; until then the record keeps its current
              crest and breach bottom.
            </p>
          ) : null}
          <p className="mt-1 text-xs text-muted">
            Values you read off a DEM and type here; DamIT Crest does not sample the DEM, and the DEM crest check is left as is.
            Or type them in the Crest, Streambed and datum fields below.
          </p>
        </div>
      ) : null}

      {nd?.countyNote ? (
        <p className="rounded-sm border border-line bg-paper px-2 py-1 text-xs" data-testid="county-note">
          ⓘ {nd.countyNote}.
        </p>
      ) : null}
      {storage?.warning ? <p className="text-sm text-amber">{storage.warning}</p> : null}
      {storage?.rangeNote ? <p className="text-sm text-amber">{storage.rangeNote}</p> : null}
      {[w1, w2].filter(Boolean).map((w) => (
        <div key={w!.id} className="rounded-sm border border-line bg-sand p-2 text-sm">
          <span className="font-medium">{w!.id}:</span> {w!.text}
          {w!.useHeightFt != null && w!.useHeightFt !== dam.heightFt ? (
            <button type="button" className="ml-2 underline" onClick={() => update({ heightFt: w!.useHeightFt })}>
              Use {w!.id === "W-H1" ? "dam height" : "crest minus breach bottom"} {w!.useHeightFt} ft
            </button>
          ) : null}
        </div>
      ))}

      {r ? (
        <details className="rounded-md border border-line bg-card p-3 text-sm" data-testid="nid-facts">
          <summary className="cursor-pointer font-medium">NID facts (reference, not used by the engine)</summary>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
            {(
              [
                ["River", r.river],
                ["City", r.city],
                ["Purpose", r.purpose],
                ["Dam type", r.damType],
                ["NID Height", fmt(r.nidHeightFt, " ft")],
                ["Dam height", fmt(r.damHeightFt, " ft")],
                ["Structural height", fmt(r.structuralHeightFt, " ft")],
                ["Hydraulic height", fmt(r.hydraulicHeightFt, " ft")],
                ["Max storage", fmt(r.maxStorageAcFt, " ac-ft")],
                ["Normal storage", fmt(r.normalStorageAcFt, " ac-ft")],
                ["Normal-pool surface area (not filled)", fmt(r.surfaceAreaNormalAc, " ac")],
                ["NID updated", r.nidUpdated],
                ["Last inspection", r.lastInspection],
                ["EAP", r.eap],
                ["NID downloaded", r.downloaded],
              ] as [string, string | null][]
            ).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted">{k}</dt>
                <dd>{v ?? "—"}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-xs text-muted">{r.attribution}</p>
        </details>
      ) : null}
      <button type="button" className="text-sm text-muted underline" onClick={() => update(unlinkPatch())}>
        Unlink NID (keep the values, drop the tags and NID reference)
      </button>
    </div>
  );
}

/** About text: what Crest is and where its dam data come from. */
export function AboutData() {
  const [open, setOpen] = useState(false);
  const { data } = useNidData(open);
  return (
    <details className="mt-8 text-xs text-muted" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer">About DamIT Crest and its data sources</summary>
      <p className="mt-2">
        DamIT Crest is a desk screen for dam-breach studies. It does not assign an official hazard class. Its dam inventory
        is the USACE National Inventory of Dams, loaded one state at a time (North Dakota ships as an offline example;
        other states are downloaded from the NID by the desktop app). No state dam-safety or other inventory is used.
      </p>
      <StaleBundleBanner data={data} className="mt-1" />
      <p className="mt-1">{data?.nidSource.attribution ?? "Dam inventory data: U.S. Army Corps of Engineers, National Inventory of Dams."}</p>
    </details>
  );
}
