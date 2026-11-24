/**
 * The Review tab's summary band (DamIT Desk UI, 2026-11-21): the dam, the class badge from the actual damit:classify
 * result (Not classified / Out of date / Partial shown as such), the key figures, and a sortable table of the
 * criteria hits the run scored, from the result's structured fields (lib/crest/review-summary.ts).
 */
import { useMemo, useState } from "react";
import { rulingFlag } from "@/lib/crest/classify-list";
import { hazardStatus } from "@/lib/crest/classify-receptors";
import {
  classBadge,
  hitRows,
  sortHits,
  suggestedDisclaimer,
  summaryTiles,
  type HitSortKey,
} from "@/lib/crest/review-summary";
import type { Analysis, DamRecord } from "@/lib/crest/types";
import { useClassifyAlg } from "./use-classify-alg";

const BADGE: Record<string, string> = {
  none: "border-line bg-card text-muted",
  stale: "border-line bg-sand text-muted",
  partial: "border-amber bg-sand text-amber",
};

function badgeTone(state: string, ordinal: number | null): string {
  if (BADGE[state]) return BADGE[state];
  if (ordinal != null && ordinal >= 3) return "border-flag-red bg-red-bg text-flag-red";
  if (ordinal === 2) return "border-amber bg-sand text-amber";
  return "border-water bg-card text-water";
}

const COLS: { key: HitSortKey; label: string; cls?: string }[] = [
  { key: "type", label: "Type" },
  { key: "receptor", label: "Receptor (id)" },
  { key: "criterion", label: "Criterion" },
  { key: "finding", label: "Value / finding", cls: "min-w-[16rem]" },
  { key: "strength", label: "Rule" },
  { key: "class", label: "Class implication" },
];

const PAGE = 50;

export function ReviewSummary({ dam, result, where }: { dam: DamRecord; result: Pick<Analysis, "flood" | "breach">; where: "review" | "report" }) {
  const alg = useClassifyAlg(dam.hazardResult);
  const badge = useMemo(() => classBadge(dam, result, alg), [dam, result, alg]);
  const tiles = useMemo(() => summaryTiles(dam, result, alg), [dam, result, alg]);
  const st = useMemo(() => hazardStatus(dam, result), [dam, result]);
  const hits = useMemo(() => hitRows(st.state === "none" ? null : st.result), [st]);
  const ruling = useMemo(() => rulingFlag(st.state === "none" ? null : st.result), [st]);
  const [sort, setSort] = useState<{ key: HitSortKey; desc: boolean }>({ key: "class", desc: true });
  const [all, setAll] = useState(false);
  const rows = useMemo(() => sortHits(hits.rows, sort.key, sort.desc), [hits.rows, sort]);
  const shown = all ? rows : rows.slice(0, PAGE);
  const tid = `review-summary-${where}`;
  return (
    <section className="rounded-md border border-line bg-card p-4" aria-labelledby={`${tid}-title`} data-testid={tid}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs tracking-widest text-muted uppercase">Hazard classification summary</p>
          <h2 id={`${tid}-title`} className="truncate text-2xl">
            {dam.name} {dam.nid ? <span className="text-muted">({dam.nid})</span> : null}
          </h2>
          <p className="text-sm text-muted">{badge.jurisdiction}</p>
        </div>
        <div className="flex max-w-md flex-col items-end gap-1 text-right">
          <span
            className={"inline-flex items-center rounded-md border-2 px-3 py-1 text-lg font-semibold " + badgeTone(badge.state, badge.ordinal)}
            data-testid="class-badge"
            data-state={badge.state}
          >
            <span className="sr-only">Suggested hazard class: </span>
            {badge.text}
          </span>
          {ruling && st.state !== "none" ? (
            <span
              className="inline-flex items-center gap-1 rounded-sm border border-amber bg-sand px-2 py-0.5 text-xs font-semibold text-amber"
              title={ruling.text}
              data-testid="class-badge-ruling"
            >
              <span aria-hidden="true">⚑</span> {ruling.short}
              <span className="sr-only">: {ruling.text}</span>
            </span>
          ) : null}
          <p className="text-xs text-muted" data-testid="class-badge-note">
            {badge.note}
          </p>
          {ruling && st.state !== "none" ? (
            <p className="text-xs text-amber" data-testid="class-badge-ruling-text">
              {ruling.text}
            </p>
          ) : null}
        </div>
      </div>
      <p className="mt-2 text-xs text-muted" data-testid="class-disclaimer">
        {suggestedDisclaimer(alg)}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4" data-testid="summary-tiles">
        {tiles.map((t) => (
          <div key={t.key} className="rounded-sm border border-line bg-paper px-3 py-2" data-testid={`tile-${t.key}`}>
            <dt className="text-xs tracking-wide text-muted uppercase">{t.label}</dt>
            <dd className="font-mono text-lg text-ink">{t.value}</dd>
            <dd className="text-xs text-muted">{t.note}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-4">
        <h3 className="text-sm font-medium" id={`${tid}-hits`}>
          Criteria hits
          {hits.source === "hits"
            ? ` (${hits.rows.length.toLocaleString("en-US")}${hits.total > hits.rows.length ? ` of ${hits.total.toLocaleString("en-US")}` : ""})`
            : ""}
        </h3>
        {hits.source === "none" ? (
          <p className="mt-1 text-sm text-muted" data-testid="hits-none">
            {st.state === "none" ? `No ${alg} result yet: run Classify… on the Export & Hand-off tab to list the hits.` : "This result lists no criteria hits."}
          </p>
        ) : (
          <>
            <p className="mt-1 text-xs text-muted">
              {hits.source === "driving"
                ? "This result is from before the desk kept every hit: these are the hits that set the class."
                : `From the run report's hit list, strongest class first${hits.total > hits.rows.length ? "; the rest are in the run report" : ""}.`}
              {st.state === "stale" ? " From the out-of-date result." : ""} Choose a column heading to sort.
            </p>
            <div className="mt-2 max-h-[28rem] overflow-auto rounded-sm border border-line" tabIndex={0} role="region" aria-labelledby={`${tid}-hits`}>
              <table className="sticky-first w-full border-collapse text-left text-sm" data-testid="hits-table">
                <thead className="sticky top-0 bg-sand">
                  <tr>
                    {COLS.map((c) => {
                      const on = sort.key === c.key;
                      return (
                        <th key={c.key} scope="col" className={"px-2 py-1.5 font-medium " + (c.cls ?? "")} aria-sort={on ? (sort.desc ? "descending" : "ascending") : "none"}>
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 text-ink hover:underline"
                            onClick={() => setSort({ key: c.key, desc: on ? !sort.desc : c.key === "class" })}
                            data-testid={`sort-${c.key}`}
                          >
                            {c.label}
                            <span aria-hidden="true" className="text-muted">
                              {on ? (sort.desc ? "▼" : "▲") : "↕"}
                            </span>
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.id} className="border-t border-line align-top">
                      <td className="px-2 py-1.5">{r.type}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.receptor}</td>
                      <td className="px-2 py-1.5 font-mono text-xs">{r.criterion}</td>
                      <td className="px-2 py-1.5 text-xs">{r.finding}</td>
                      <td className="px-2 py-1.5 text-xs">{r.strength}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        {r.label || "—"}
                        {r.ordinal != null ? <span className="text-muted"> ({r.ordinal})</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length > PAGE ? (
              <button type="button" className="mt-2 text-sm text-water underline" onClick={() => setAll((v) => !v)} data-testid="hits-show-all">
                {all ? `Show the first ${PAGE}` : `Show all ${rows.length.toLocaleString("en-US")} rows…`}
              </button>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
