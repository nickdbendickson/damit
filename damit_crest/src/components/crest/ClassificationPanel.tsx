/**
 * Report step: the jurisdiction context the hand-off sends to damit:classify (preset mode or custom mode, Appendix A).
 * Thresholds are not shown or edited here; they live in the hazard catalog data file the plugin reads.
 */
import { useMemo } from "react";
import {
  CATALOG,
  customOptions,
  damChoice,
  defaultPresetFor,
  enabledIds,
  presetIds,
  resolveChoice,
  screenAgainstChoice,
  type ClassificationChoice,
} from "@/lib/crest/jurisdiction";
import type { DamRecord, ScreenLevel } from "@/lib/crest/types";

const SECTION_LABEL = {
  scenarios: "Scenarios (S)",
  domains: "Domain cutoffs (D)",
  methods: "Consequence methods (M)",
  modifiers: "Modifier rules (R)",
} as const;

export function ClassificationPanel({
  dam,
  level,
  update,
}: {
  dam: DamRecord;
  level: ScreenLevel;
  update: (patch: Partial<DamRecord>) => void;
}) {
  // No choice yet: the record's state preset (ND00199 -> North Dakota REG_05.2026), else FEMA 333.
  const choice = damChoice(dam);
  const set = (next: ClassificationChoice) => update({ classification: resolveChoice(next, defaultPresetFor(dam)) });
  const options = useMemo(() => customOptions(), []);
  const enabled = new Set(enabledIds(choice));
  const p = choice.mode === "preset" ? CATALOG.presets[choice.preset ?? ""] : undefined;
  const field = "mt-1 h-10 w-full rounded-sm border border-line bg-paper px-3 text-sm";
  return (
    <div className="rounded-md border border-line bg-card p-4" data-testid="classification-panel">
      <h3 className="text-lg">Jurisdiction and classification methods</h3>
      <p className="mt-1 text-sm text-muted">
        DamIT is multi-jurisdiction and consequence-based. Pick a state or agency preset, or switch to custom mode and
        tick method ids. The choice is written into dam.json and sent to damit:classify; the thresholds come from the
        hazard catalog data file, not from this desk. {CATALOG.disclaimer}
      </p>
      <div className="mt-3 flex flex-wrap gap-4 text-sm" role="radiogroup" aria-label="Classification mode">
        <label className="inline-flex items-center gap-2">
          <input
            type="radio"
            name="classification-mode"
            checked={choice.mode === "preset"}
            onChange={() => set({ mode: "preset", preset: choice.preset, advisory: choice.advisory })}
          />
          Preset mode
        </label>
        <label className="inline-flex items-center gap-2">
          <input
            type="radio"
            name="classification-mode"
            checked={choice.mode === "custom"}
            onChange={() => set({ mode: "custom", methods: [...enabled], advisory: choice.advisory })}
          />
          Custom mode (method ids, no jurisdiction names)
        </label>
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={choice.advisory === true}
            onChange={(e) => set({ ...choice, advisory: e.target.checked })}
          />
          Apply advisory-strength results
        </label>
      </div>
      {choice.mode === "preset" ? (
        <div className="mt-3">
          <label className="text-xs text-muted">
            Preset
            <select className={field} value={choice.preset} onChange={(e) => set({ mode: "preset", preset: e.target.value, advisory: choice.advisory })}>
              {presetIds().map((id) => (
                <option key={id} value={id}>
                  {CATALOG.presets[id].label}
                  {CATALOG.presets[id].verification !== "verified" ? ` (${CATALOG.presets[id].verification})` : ""}
                </option>
              ))}
            </select>
          </label>
          {p ? (
            <dl className="mt-2 grid gap-1 text-xs text-muted sm:grid-cols-2">
              <div>
                <dt className="inline font-medium">Scenarios: </dt>
                <dd className="inline">{p.scenarios.join(", ") || "none confirmed (M13 and engineering judgment)"}</dd>
              </div>
              <div>
                <dt className="inline font-medium">Methods: </dt>
                <dd className="inline">
                  {p.methods.map((m) => (p.advisoryMethods.includes(m) ? `${m} (advisory)` : m)).join(", ")}
                </dd>
              </div>
              <div>
                <dt className="inline font-medium">Modifiers: </dt>
                <dd className="inline">{p.modifiers.join(", ") || "none"}</dd>
              </div>
              <div>
                <dt className="inline font-medium">Labels: </dt>
                <dd className="inline">
                  {Object.entries(p.labels)
                    .map(([ord, label]) => `${ord} ${label}`)
                    .join(" / ")}
                </dd>
              </div>
            </dl>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2" data-testid="custom-methods">
          {(Object.keys(SECTION_LABEL) as (keyof typeof SECTION_LABEL)[]).map((section) => (
            <fieldset key={section} className="text-xs">
              <legend className="font-medium">{SECTION_LABEL[section]}</legend>
              {options
                .filter((o) => o.section === section)
                .map((o) => (
                  <label key={o.id} className="mt-1 flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={enabled.has(o.id)}
                      onChange={(e) => {
                        const next = new Set(enabled);
                        if (e.target.checked) next.add(o.id);
                        else next.delete(o.id);
                        set({ mode: "custom", methods: [...next], advisory: choice.advisory });
                      }}
                    />
                    <span>
                      <span className="font-mono">{o.id}</span> {o.name}
                    </span>
                  </label>
                ))}
            </fieldset>
          ))}
        </div>
      )}
      <p className="mt-3 text-xs text-muted">{screenAgainstChoice(level, choice)}</p>
      <p className="mt-1 text-xs text-muted">
        Catalog {CATALOG.catalogVersion}: {CATALOG.sourceDocument}.
      </p>
    </div>
  );
}
