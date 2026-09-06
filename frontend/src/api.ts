import type { Digest } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080";

export class NoDigestYet extends Error {}
export class ApiUnreachable extends Error {}

/** Result of `POST /run`. `truncated`: the daily LLM budget cap (backend/guardrails.py) stopped the
 *  run before the end of the batch. That is not an error — the items already analysed are recorded
 *  and served — but the digest carries only part of the collection. */
export type RunResult = { item_count: number; truncated: boolean };

/** `days`: depth of the sliding window served by the API. Omitted, the backend applies its default
 *  (DIGEST_WINDOW_DAYS) — the front has no business duplicating that product choice. */
export async function fetchDigest(days?: number): Promise<Digest> {
  const url = days === undefined ? `${BASE}/events` : `${BASE}/events?days=${days}`;
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new ApiUnreachable(BASE);
  }
  if (res.status === 404) throw new NoDigestYet();
  if (!res.ok) throw new Error(`GET /events → ${res.status}`);
  return res.json();
}

export async function triggerRun(): Promise<RunResult> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/run`, { method: "POST" });
  } catch {
    throw new ApiUnreachable(BASE);
  }
  if (res.ok) return res.json();

  const detail = await res.json().then(
    (b) => b?.detail as string | undefined,
    () => undefined,
  );
  throw new Error(detail ?? `POST /run → ${res.status}`);
}
