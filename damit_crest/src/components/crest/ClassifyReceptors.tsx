/**
 * The real receptors damit:classify judged (its GeoPackage, read by the desk server), with names, class, depth and
 * click-to-zoom, on the Dashboard and the Report (Absaraka desk test 2026-11-21). The desk's own 911 / mapped list stays
 * in its own table; this one is labelled as classify's.
 */
import { useEffect, useMemo, useState } from "react";
import {
  classColor,
  countsLine,
  filterClassify,
  LAYER_WORD,
  needsRuling,
  zoomBounds,
  type ClassifyReceptor,
  type LayerFilter,
} from "@/lib/crest/classify-list";
import { hazardStatus } from "@/lib/crest/classify-receptors";
import { hasDesktopServer } from "@/lib/crest/desktop-server";
import { useClassifyAlg } from "./use-classify-alg";
import { useClassifyReceptors } from "./use-classify-receptors";
import { useReceptorFocus } from "@/lib/crest/receptor-focus";
import { useDesk } from "@/lib/crest/store";
import type { Analysis, DamRecord } from "@/lib/crest/types";

const n = (v: number | null, d = 2) => (v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: d }));
const PAGE = 25;
const CHIPS: { id: LayerFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "STRUCTURES", label: "Structures" },
  { id: "ROADS", label: "Roads" },
  { id: "RAIL", label: "Rail" },
  { id: "ruling", label: "Needs ruling" },
];

/**
 * The table. where="dashboard" zooms the map beside it; where="report" opens the Dashboard and zooms there.
 */
export function ClassifyReceptorsPanel({ dam, result, where }: { dam: DamRecord; result: Pick<Analysis, "flood">; where: "dashboard" | "report" }) {
  const load = useClassifyReceptors(dam);
  const alg = useClassifyAlg(dam.hazardResult);
  const st = useMemo(() => hazardStatus(dam, result), [dam, result]);
  const zoomTo = useReceptorFocus((s) => s.zoomTo);
  const focused = useReceptorFocus((s) => s.focus?.rid);
  const [layer, setLayer] = useState<LayerFilter>("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const rows = useMemo(() => filterClassify(load.list?.receptors ?? [], layer, q), [load.list, layer, q]);
  useEffect(() => setPage(0), [layer, q, load.key]);
  const tid = `classify-receptors-${where}`;
  if (st.state === "none") return null;
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const pick = (r: ClassifyReceptor) => {
    const bounds = zoomBounds(r);
    if (!bounds) return;
    zoomTo({ rid: r.rid, name: r.name, bounds, at: r.at });
    if (where === "report") useDesk.getState().setStep("dashboard");
    else document.querySelector('[data-testid="dash-map"]')?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };
  return (
    <section className="classify-receptors rounded-md border border-line bg-card p-3" data-testid={tid} aria-labelledby={`${tid}-title`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 id={`${tid}-title`} className="text-sm font-medium">
          Receptors {alg} judged{st.state === "stale" ? " (out-of-date result)" : ""}
        </h4>
        {load.list ? <p className="text-xs text-muted" data-testid="classify-counts">{countsLine(load.list.counts)}</p> : null}
      </div>
      {load.state === "loading" ? <p className="mt-1 text-xs text-muted">Reading the classify GeoPackage…</p> : null}
      {load.state === "error" ? (
        <p className="mt-1 text-xs text-amber" role="status" data-testid="classify-receptors-error">
          Could not read the receptors: {load.error}
        </p>
      ) : null}
      {load.state === "none" ? (
        <p className="mt-1 text-xs text-muted">
          {hasDesktopServer() ? "This result has no GeoPackage path: run Classify… again to list its receptors." : "The receptor list needs the desk server (bin/damit-desk)."}
        </p>
      ) : null}
      {load.list ? (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-1" role="group" aria-label="Show receptors">
            {CHIPS.map((c) => (
              <button
                key={c.id}
                type="button"
                className="classify-chip"
                aria-pressed={layer === c.id}
                onClick={() => setLayer(c.id)}
                data-testid={`classify-chip-${c.id}`}
              >
                {c.label}
              </button>
            ))}
            <input
              className="ml-auto rounded-sm border border-line bg-paper px-2 py-0.5 text-xs"
              placeholder="Search name, id or class…"
              aria-label={`Search the receptors ${alg} judged`}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="mt-2 max-h-[22rem] overflow-auto rounded-sm border border-line" tabIndex={0} role="region" aria-label={`Receptors ${alg} judged`}>
            <table className="sticky-first w-full border-collapse text-left text-xs" data-testid="classify-receptors-table">
              <thead className="sticky top-0 z-[1] bg-sand">
                <tr>
                  <th scope="col" className="px-2 py-1 font-medium">Receptor</th>
                  <th scope="col" className="px-2 py-1 font-medium">Type</th>
                  <th scope="col" className="px-2 py-1 font-medium">Class</th>
                  <th scope="col" className="px-2 py-1 text-right font-medium">Depth ft</th>
                  <th scope="col" className="px-2 py-1 text-right font-medium">Vel ft/s</th>
                  <th scope="col" className="px-2 py-1 font-medium">Method</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.rid} className={"border-t border-line align-top " + (focused === r.rid ? "is-focused" : "")} data-rid={r.rid}>
                    <th scope="row" className="px-2 py-1 font-normal">
                      <button
                        type="button"
                        className="text-left text-water underline-offset-2 hover:underline disabled:text-ink disabled:no-underline"
                        onClick={() => pick(r)}
                        disabled={!r.at && !r.bbox}
                        title={where === "report" ? "Show it on the Dashboard map" : "Zoom the map to it"}
                        data-testid="classify-zoom"
                      >
                        {r.name}
                      </button>
                      <span className="block font-mono text-[11px] text-muted">{r.rid}</span>
                    </th>
                    <td className="px-2 py-1">{LAYER_WORD[r.layer]}</td>
                    <td className="px-2 py-1 whitespace-nowrap">
                      {r.ordinal != null ? (
                        <>
                          <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: classColor(r.ordinal) }} />
                          {r.label || r.ordinal}
                          {r.advisory ? <span className="text-muted"> (advisory)</span> : null}
                        </>
                      ) : (
                        <span className="text-muted">wet, no hit</span>
                      )}
                      {needsRuling(r) ? (
                        <span className="ml-1 rounded-sm border border-amber px-1 text-[11px] text-amber" title="trains per day from the rail lookup: not ruled yet" data-testid="receptor-needs-ruling">
                          needs ruling
                        </span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">{n(r.depthFt)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{n(r.velFps)}</td>
                    <td className="px-2 py-1 font-mono">{r.methods || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span>
              {rows.length.toLocaleString("en-US")} shown of {load.list.total.toLocaleString("en-US")} with a hit or water on them
              {load.list.truncated ? " (the strongest first; every one is in the GeoPackage)" : ""}.
            </span>
            {pages > 1 ? (
              <span className="flex items-center gap-1">
                <button type="button" className="classify-chip" disabled={page === 0} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">
                  ‹
                </button>
                {page + 1} / {pages}
                <button type="button" className="classify-chip" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)} aria-label="Next page">
                  ›
                </button>
              </span>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}
