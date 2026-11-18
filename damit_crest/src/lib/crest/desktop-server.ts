/**
 * Calls to the DamIT Crest desktop server (desktop/damit_desktop/__main__.py). The server opens the desk at
 * index.html#damit-token=<token>; every /api/ call must send that per-launch token back in X-DamIT-Token.
 *
 * Security audit 2026-11-18: the token used to be written into <meta name="damit-token"> of the served page, so any
 * local process or other OS user that could reach 127.0.0.1 read it with a plain GET /. A URL fragment is never sent
 * over HTTP, so no request to the server can obtain it now. On first load the token is moved into sessionStorage (a
 * reload of the same window keeps working) and stripped from the address with history.replaceState.
 */
const FRAGMENT_KEY = "damit-token";
const STORAGE_KEY = "damit-token";

/** The token in a location hash such as "#damit-token=abc" or "#x=1&damit-token=abc" ("" when absent), and the hash
 * with that parameter removed. */
export function splitTokenFragment(hash: string): { token: string; rest: string } {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  let token = "";
  const kept: string[] = [];
  for (const part of raw ? raw.split("&") : []) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq) === FRAGMENT_KEY) {
      try {
        token = decodeURIComponent(part.slice(eq + 1));
      } catch {
        token = "";
      }
    } else if (part) {
      kept.push(part);
    }
  }
  return { token, rest: kept.length ? `#${kept.join("&")}` : "" };
}

function storage(): Storage | undefined {
  try {
    return typeof sessionStorage === "undefined" ? undefined : sessionStorage;
  } catch {
    return undefined;
  }
}

/** Move a token from the address fragment into sessionStorage and strip it from the address bar. */
function adoptFragmentToken(): string {
  if (typeof location === "undefined") return "";
  const { token, rest } = splitTokenFragment(location.hash || "");
  if (!token) return "";
  try {
    storage()?.setItem(STORAGE_KEY, token);
  } catch {
    /* private mode: keep it in memory only */
  }
  try {
    if (typeof history !== "undefined") history.replaceState(history.state, "", `${location.pathname}${location.search}${rest}`);
  } catch {
    /* ignore */
  }
  return token;
}

let cached = adoptFragmentToken();

/** The per-launch desktop API token ("" when the page did not come from the desktop server). */
export function desktopToken(): string {
  if (cached) return cached;
  cached = adoptFragmentToken();
  if (!cached) {
    try {
      cached = storage()?.getItem(STORAGE_KEY) || "";
    } catch {
      cached = "";
    }
  }
  return cached;
}

export function crestApiHeaders(json = false): Record<string, string> {
  return { ...(json ? { "Content-Type": "application/json" } : {}), "X-DamIT-Token": desktopToken() };
}

/**
 * True when the page came from the desktop server (it was opened with the token). DamIT.html opened from disk has no
 * server: a call to /api/ there can only fail, and its Content-Security-Policy reports it, so callers that run by
 * themselves (not on a button) ask this first.
 */
export function hasDesktopServer(): boolean {
  return desktopToken() !== "";
}
