/**
 * Headword matching, held entirely in memory.
 *
 * All ~4,000 headwords come to about 60 KB gzipped. Held in a plain array,
 * every match type is a scan of 4,000 short strings: microseconds, with no
 * index to build, no query planner and no storage layer to fail offline.
 *
 * This is why the app ships no SQLite. The database the pipeline builds has
 * a trigram index for exactly these queries, and at this corpus size it would
 * be slower than the scan it replaces.
 */

import { normalise, sortKey } from "../normalise.js";

/**
 * The key all headword matching runs on.
 *
 * `normalise` keeps internal hyphens and apostrophes, which is right for
 * storage but wrong for matching: someone typing "rose croix" must still find
 * "Rose-Croix." `sortKey` flattens both to spaces, so the two agree.
 */
export function searchKey(text        )         {
  return sortKey(text);
}

/** [id, headword as printed, normalised form, letter, printed page] */
                                                                   

export const ID = 0;
export const DISPLAY = 1;
export const PLAIN = 2;
export const LETTER = 3;
export const PAGE = 4;

                                                        

/**
 * Damerau-Levenshtein distance, abandoned once it exceeds `limit`.
 *
 * Transpositions matter here: typing "Tetragrammton" or "Kadsoh" should still
 * find the entry, and plain Levenshtein charges two edits for a swap.
 */
export function editDistance(a        , b        , limit        )         {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;

  let previousPrevious           = [];
  let previous           = new Array(b.length + 1);
  let current           = new Array(b.length + 1);
  for (let j = 0; j <= b.length; j++) previous[j] = j;

  for (let i = 1; i <= a.length; i++) {
    current[0] = i;
    let rowBest = current[0];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let value = Math.min(
        current[j - 1] + 1,      // insertion
        previous[j] + 1,         // deletion
        previous[j - 1] + cost,  // substitution
      );
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        value = Math.min(value, previousPrevious[j - 2] + 1);  // transposition
      }
      current[j] = value;
      if (value < rowBest) rowBest = value;
    }
    // No later row can improve on the best in this one.
    if (rowBest > limit) return limit + 1;
    previousPrevious = previous;
    previous = current;
    current = new Array(b.length + 1);
  }
  return previous[b.length];
}

export class HeadwordIndex {
           rows                        ;
  /** Match keys, parallel to `rows`. Derived once, not shipped in the bundle. */
                   keys          ;
                   exactMap                       ;

  constructor(rows                        ) {
    this.rows = rows;
    this.exactMap = new Map();
    this.keys = rows.map((row) => searchKey(row[PLAIN]));
    for (const row of rows) {
      const key = searchKey(row[PLAIN]);
      const existing = this.exactMap.get(key);
      if (existing) existing.push(row[ID]);
      else this.exactMap.set(key, [row[ID]]);
    }
  }

  get size()         {
    return this.rows.length;
  }

  /** The whole headword, ignoring case, accents and punctuation. */
  exact(query        )           {
    return this.exactMap.get(searchKey(query)) ?? [];
  }

  /** Headwords beginning with the query: "beaut" finds "Beauty". */
  prefix(query        , limit = 200)           {
    const needle = searchKey(query);
    if (!needle) return [];
    const out           = [];
    for (let i = 0; i < this.rows.length; i++) {
      if (this.keys[i].startsWith(needle)) {
        out.push(this.rows[i][ID]);
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  /** Headwords ending with the query: "tion" finds "Initiation". */
  suffix(query        , limit = 200)           {
    const needle = searchKey(query);
    if (!needle) return [];
    const out           = [];
    for (let i = 0; i < this.rows.length; i++) {
      if (this.keys[i].endsWith(needle)) {
        out.push(this.rows[i][ID]);
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  /** Headwords containing the query anywhere: "aut" finds "Autopsy". */
  substring(query        , limit = 200)           {
    const needle = searchKey(query);
    if (!needle) return [];
    const out           = [];
    for (let i = 0; i < this.rows.length; i++) {
      if (this.keys[i].includes(needle)) {
        out.push(this.rows[i][ID]);
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  /**
   * Near-misses, for "did you mean". The distance allowed grows with the
   * query: one edit is plenty for a short word, two for a longer one.
   */
  fuzzy(query        , limit = 10)             {
    const needle = searchKey(query);
    if (needle.length < 3) return [];
    const maxDistance = needle.length <= 5 ? 1 : 2;
    const hits             = [];
    for (let i = 0; i < this.rows.length; i++) {
      const row = this.rows[i];
      const candidate = this.keys[i];
      if (Math.abs(candidate.length - needle.length) > maxDistance) continue;
      const distance = editDistance(needle, candidate, maxDistance);
      if (distance <= maxDistance) hits.push({ id: row[ID], distance });
    }
    hits.sort((a, b) => a.distance - b.distance);
    return hits.slice(0, limit);
  }

  /** Headwords under one letter of the A–Z index, in printed order. */
  byLetter(letter        )           {
    const wanted = letter.toUpperCase();
    return this.rows.filter((row) => row[LETTER] === wanted).map((row) => row[ID]);
  }

  /** How many entries sit under each letter. */
  letterCounts()                         {
    const counts                         = {};
    for (const row of this.rows) counts[row[LETTER]] = (counts[row[LETTER]] ?? 0) + 1;
    return counts;
  }
}
