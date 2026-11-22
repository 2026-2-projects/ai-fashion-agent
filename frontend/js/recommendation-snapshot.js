/** The last verified recommendation can survive a reload in THIS TAB, for THIS account.
 * No credentials/CSRF/passwords are stored. Validation is rerun on every restore.
 */
import { validateRecommendation, validateLookImages } from "./recommendation-model.js";

const PREFIX = "clomori:last-recommendation:v1:";
const TTL_MS = 24 * 60 * 60 * 1000;
const MAX_BYTES = 160_000;
const key = ownerId => PREFIX + ownerId;
const validId = value => Number.isSafeInteger(value) && value > 0;
function storage() { try { return window.sessionStorage; } catch { return null; } }

export function clearRecommendationSnapshots() {
  const s = storage();
  if (!s) return;
  try {
    for (let i = s.length - 1; i >= 0; i--) {
      const entry = s.key(i);
      if (entry?.startsWith(PREFIX)) s.removeItem(entry);
    }
  } catch { /* Browsers can disable storage. The app still works without caching. */ }
}

export function clearRecommendationSnapshot(ownerId) {
  if (!validId(ownerId)) return;
  try { storage()?.removeItem(key(ownerId)); } catch { /* optional cache */ }
}

export function saveRecommendationSnapshot(ownerId, memory) {
  if (!validId(ownerId) || memory?.ownerId !== ownerId || !memory?.result) return false;
  const s = storage();
  if (!s) return false;
  try {
    const result = validateRecommendation(memory.result);
    const images = [];
    for (const [lookId, record] of memory.images instanceof Map ? memory.images : []) {
      if (record?.phase !== "ready" || !record.data) continue;
      const look = result.looks.find(x => x.look_id === lookId);
      if (!look) continue;
      validateLookImages(record.data, result.recommendation_id, look);
      images.push({ lookId, data: record.data, expanded: Boolean(record.expanded) });
    }
    const draft = {};
    for (const field of ["message", "place", "date", "time"]) {
      const value = memory.draft?.[field];
      draft[field] = typeof value === "string" ? value.slice(0, field === "message" ? 1000 : 100) : "";
    }
    const value = JSON.stringify({ v: 1, ownerId, at: Date.now(), draft, result, images });
    if (value.length > MAX_BYTES) return false;
    s.setItem(key(ownerId), value);
    return true;
  } catch { return false; }
}

export function loadRecommendationSnapshot(ownerId) {
  if (!validId(ownerId)) return null;
  const s = storage();
  if (!s) return null;
  try {
    const raw = s.getItem(key(ownerId));
    if (!raw || raw.length > MAX_BYTES) return null;
    const cached = JSON.parse(raw);
    if (cached.v !== 1 || cached.ownerId !== ownerId || !Number.isFinite(cached.at)
        || cached.at > Date.now() + 60_000 || Date.now() - cached.at > TTL_MS) {
      clearRecommendationSnapshot(ownerId);
      return null;
    }
    const result = validateRecommendation(cached.result);
    const images = new Map();
    if (!Array.isArray(cached.images) || cached.images.length > 5) throw Error("Invalid cached image records");
    for (const entry of cached.images) {
      if (!Number.isInteger(entry.lookId) || images.has(entry.lookId)) throw Error("Duplicate look id");
      const look = result.looks.find(x => x.look_id === entry.lookId);
      if (!look) throw Error("Unknown look");
      validateLookImages(entry.data, result.recommendation_id, look);
      images.set(entry.lookId, { phase: "ready", expanded: entry.expanded === true,
        data: entry.data, error: "" });
    }
    const draft = {};
    for (const field of ["message", "place", "date", "time"]) {
      if (typeof cached.draft?.[field] !== "string") throw Error("Invalid draft");
      draft[field] = cached.draft[field].slice(0, field === "message" ? 1000 : 100);
    }
    return { ownerId, draft, result, images };
  } catch {
    clearRecommendationSnapshot(ownerId);
    return null;
  }
}
