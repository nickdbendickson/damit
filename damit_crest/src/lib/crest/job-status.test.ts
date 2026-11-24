// The status bar's plugin state (job-status.ts) and the palette-to-panel job hand-off.
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { checkSummary, engineText, jobFinished, jobNoServer, jobStarted, requestJob, resetJobStarter, runText, setJobStarter, useJobStatus } from "./job-status.ts";

const reset = () => useJobStatus.setState({ busy: false, label: null, last: null, check: null, noServer: false });

describe("job status", () => {
  beforeEach(() => {
    reset();
    resetJobStarter();
  });

  it("starts idle and not checked; never claims QGIS without a check", () => {
    assert.equal(runText(useJobStatus.getState()), "Idle");
    assert.deepEqual(engineText(useJobStatus.getState(), true), { text: "QGIS hand-off: not checked yet", tone: "muted" });
    assert.equal(engineText(useJobStatus.getState(), false).tone, "warn");
  });

  it("a running job, then its end", () => {
    jobStarted("/api/model");
    assert.equal(runText(useJobStatus.getState()), "Running: Run the flood model…");
    jobFinished("/api/model", { ok: false, cancelled: true });
    assert.equal(runText(useJobStatus.getState()), "Idle · last: Run the flood model cancelled");
    jobFinished("/api/screen", { ok: true, partial: true });
    assert.equal(runText(useJobStatus.getState()), "Idle · last: Write folder and run screening partial result");
  });

  it("Check QGIS hand-off: all found, some missing, or no qgis_process", () => {
    const rows = [
      { role: "preflight", algorithm: "damit_screen:preflight", found: true },
      { role: "rundam", algorithm: "damit_run:rundam", found: true },
    ];
    jobFinished("/api/check", { ok: true, check: rows });
    assert.equal(engineText(useJobStatus.getState(), true).text, "QGIS hand-off ✓ 2/2 algorithms");
    jobFinished("/api/check", { ok: false, check: [rows[0], { ...rows[1], found: false }] });
    assert.deepEqual(engineText(useJobStatus.getState(), true), { text: "QGIS hand-off: 1 missing (damit_run:rundam)", tone: "warn" });
    jobFinished("/api/check", { ok: false, check: [] });
    assert.equal(engineText(useJobStatus.getState(), true).text, "QGIS hand-off: qgis_process not found");
    // A cancelled check keeps the last result; another job does not touch it.
    jobFinished("/api/check", { ok: false, cancelled: true, check: [] });
    jobFinished("/api/folder", { ok: true });
    assert.equal(engineText(useJobStatus.getState(), true).text, "QGIS hand-off: qgis_process not found");
    assert.equal(checkSummary(rows, false, "t").ok, false);
  });

  it("no desk server is reported as such", () => {
    jobNoServer();
    assert.equal(engineText(useJobStatus.getState(), true).tone, "warn");
  });

  it("a job asked for before the panel is up starts when it registers; afterwards at once", () => {
    const got: string[] = [];
    requestJob("/api/check");
    assert.equal(got.length, 0);
    const off = setJobStarter((p) => got.push(p));
    assert.deepEqual(got, ["/api/check"]);
    requestJob("/api/folder");
    assert.deepEqual(got, ["/api/check", "/api/folder"]);
    off();
    requestJob("/api/check");
    assert.deepEqual(got, ["/api/check", "/api/folder"]);
  });
});
