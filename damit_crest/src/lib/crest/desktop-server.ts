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

/**
 * True when the page came from the desktop server (it carries the token). DamIT.html opened from disk has no server:
 * a call to /api/ there can only fail, and its Content-Security-Policy reports it, so callers that run by themselves
 * (not on a button) ask this first.
 */
export function hasDesktopServer(): boolean {
  return typeof document !== "undefined" && document.querySelector('meta[name="damit-token"]') !== null;
}
