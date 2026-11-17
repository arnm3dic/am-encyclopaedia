/**
 * Loading the dictionary bundle.
 *
 * Data is fetched from a relative URL rather than reached for through the
 * service worker. The same code path then works online, offline once the
 * worker has cached it, and inside a WebView if this is ever wrapped as a
 * native app -- which is the decision that keeps the store option open at no
 * cost now.
 */

import type { HeadwordRow } from "../search/headwords.ts";
import type { CrossRef, Entry } from "../search/engine.ts";
import { Dictionary } from "../search/engine.ts";

export type Meta = {
  source_title: string;
  source_author: string;
  source_edition: string;
  entries: string;
  cross_refs: string;
  cross_refs_resolved: string;
  letter_counts: Record<string, number>;
};

type EntriesFile = {
  /** id -> [headword, body, printedPage, pdfPage, needsReview] */
  entries: Record<string, [string, string, number, number, number]>;
  /** id -> [[toEntry, rawTarget, kind], ...] */
  crossrefs: Record<string, Array<[number | null, string, string]>>;
};

export function buildDictionary(
  headwords: HeadwordRow[],
  file: EntriesFile,
): Dictionary {
  const entries = new Map<number, Entry>();
  for (const [key, value] of Object.entries(file.entries)) {
    const id = Number(key);
    entries.set(id, {
      id,
      headword: value[0],
      body: value[1],
      printedPage: value[2],
      pdfPage: value[3],
      needsReview: value[4] === 1,
    });
  }

  const crossrefs = new Map<number, CrossRef[]>();
  for (const [key, value] of Object.entries(file.crossrefs ?? {})) {
    crossrefs.set(
      Number(key),
      value.map(([toEntry, rawTarget, kind]) => ({ toEntry, rawTarget, kind })),
    );
  }

  return new Dictionary(headwords, entries, crossrefs);
}

/** Fetch and assemble the dictionary. `base` is relative to the app root. */
export async function loadDictionary(base = "data"): Promise<{
  dictionary: Dictionary;
  meta: Meta;
}> {
  const [headwords, file, meta] = await Promise.all([
    fetchJson<HeadwordRow[]>(`${base}/headwords.json`),
    fetchJson<EntriesFile>(`${base}/entries.json`),
    fetchJson<Meta>(`${base}/meta.json`),
  ]);
  return { dictionary: buildDictionary(headwords, file), meta };
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`could not load ${url}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}
