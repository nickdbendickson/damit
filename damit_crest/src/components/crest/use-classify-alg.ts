/**
 * The classify algorithm the desk names in its labels and help (the palette, the Report to-do, the class badge, the
 * receptor list): the one a stored result came from, else the active profile's (damit:classify for the DamIT
 * profile, ndhazard:classify for North Dakota). North Dakota profile test 2026-11-22: the palette said
 * "Classify (damit:classify)" while the desk ran ndhazard:classify.
 */
import { classifyAlgorithm } from "@/lib/crest/handoff";
import { useProfile } from "@/lib/crest/profile";
import type { HazardResult } from "@/lib/crest/types";

export function useClassifyAlg(result?: Pick<HazardResult, "source" | "gpkg"> | null): string {
  const profile = useProfile((s) => s.profile);
  return classifyAlgorithm(profile, result);
}
