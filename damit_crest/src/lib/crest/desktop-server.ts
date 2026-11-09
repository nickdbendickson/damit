/**
 * Calls to the DamIT Crest desktop server (desktop/damit_desktop/__main__.py). The server puts a per-launch token in
 * <meta name="damit-token"> of the page it serves; every /api/ call must send it back.
 */
export function crestApiHeaders(json = false): Record<string, string> {
  const token =
    typeof document === "undefined"
      ? ""
      : (document.querySelector('meta[name="damit-token"]')?.getAttribute("content") ?? "");
  return { ...(json ? { "Content-Type": "application/json" } : {}), "X-DamIT-Token": token };
}
