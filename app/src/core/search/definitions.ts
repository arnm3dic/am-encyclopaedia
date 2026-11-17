/**
 * Searching inside the definitions.
 *
 * An inverted index over ~4,000 bodies, built at first run in a few hundred
 * milliseconds. Postings hold document ids only, not term positions: phrases
 * are verified afterwards by checking the candidate's own normalised text.
 * Entries are short -- 415 characters at the median -- so that check is
 * cheaper than carrying positions for every token in memory.
 *
 * Scoring is BM25. It favours entries where the term is unusual and the entry
 * is short, which is what you want in a reference work: a query for "acacia"
 * should surface the article about acacia before a long article that mentions
 * it once in passing.
 */

import { normalise, sortKey } from "../normalise.ts";

const TOKEN = /[\p{L}\p{N}]+/gu;

const K1 = 1.2;   // term-frequency saturation
const B = 0.65;   // length normalisation

export type Scored = { id: number; score: number };

export function tokenize(text: string): string[] {
  const normalised = normalise(text);
  return normalised.match(TOKEN) ?? [];
}

export class DefinitionIndex {
  /** token -> document ids */
  private readonly postings = new Map<string, number[]>();
  /** document id -> term frequencies */
  private readonly frequencies = new Map<number, Map<string, number>>();
  /** document id -> normalised body, kept for phrase and substring checks */
  private readonly texts = new Map<number, string>();
  private readonly lengths = new Map<number, number>();
  private averageLength = 0;

  constructor(documents: Iterable<readonly [number, string]>) {
    let totalLength = 0;
    let count = 0;
    for (const [id, body] of documents) {
      const normalised = normalise(body);
      this.texts.set(id, sortKey(normalised));
      const tokens = normalised.match(TOKEN) ?? [];
      this.lengths.set(id, tokens.length);
      totalLength += tokens.length;
      count += 1;

      const counts = new Map<string, number>();
      for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
      this.frequencies.set(id, counts);
      for (const token of counts.keys()) {
        const list = this.postings.get(token);
        if (list) list.push(id);
        else this.postings.set(token, [id]);
      }
    }
    this.averageLength = count ? totalLength / count : 0;
  }

  get size(): number {
    return this.texts.size;
  }

  get vocabulary(): number {
    return this.postings.size;
  }

  /** Entries containing all the query's terms, ranked by BM25. */
  search(query: string, limit = 100): Scored[] {
    const terms = [...new Set(tokenize(query))];
    if (terms.length === 0) return [];

    // Start from the rarest term: it gives the smallest candidate set.
    const lists = terms.map((term) => this.postings.get(term) ?? []);
    if (lists.some((list) => list.length === 0)) return this.searchAny(terms, limit);

    lists.sort((a, b) => a.length - b.length);
    let candidates = new Set(lists[0]);
    for (let i = 1; i < lists.length; i++) {
      const next = new Set(lists[i]);
      candidates = new Set([...candidates].filter((id) => next.has(id)));
      if (candidates.size === 0) break;
    }
    if (candidates.size === 0) return this.searchAny(terms, limit);
    return this.rank([...candidates], terms, limit);
  }

  /** Fallback when no entry holds every term: rank on those it does hold. */
  private searchAny(terms: string[], limit: number): Scored[] {
    const candidates = new Set<number>();
    for (const term of terms) {
      for (const id of this.postings.get(term) ?? []) candidates.add(id);
    }
    if (candidates.size === 0) return [];
    return this.rank([...candidates], terms, limit);
  }

  private rank(candidates: number[], terms: string[], limit: number): Scored[] {
    const total = this.texts.size;
    const scored: Scored[] = [];
    for (const id of candidates) {
      const counts = this.frequencies.get(id);
      if (!counts) continue;
      const length = this.lengths.get(id) ?? 0;
      let score = 0;
      for (const term of terms) {
        const frequency = counts.get(term) ?? 0;
        if (frequency === 0) continue;
        const documentCount = (this.postings.get(term) ?? []).length;
        const idf = Math.log(1 + (total - documentCount + 0.5) / (documentCount + 0.5));
        const denominator =
          frequency + K1 * (1 - B + (B * length) / (this.averageLength || 1));
        score += idf * ((frequency * (K1 + 1)) / denominator);
      }
      if (score > 0) scored.push({ id, score });
    }
    scored.sort((a, b) => b.score - a.score || a.id - b.id);
    return scored.slice(0, limit);
  }

  /**
   * Entries whose definition contains the query as a contiguous phrase.
   *
   * Candidates come from the index, then each is confirmed against its own
   * text, so "feeling of great happiness" matches only where those words run
   * together rather than merely co-occur.
   */
  phrase(query: string, limit = 100): Scored[] {
    const needle = normalise(query);
    if (!needle) return [];
    const terms = [...new Set(tokenize(query))];
    const candidates = terms.length
      ? this.search(query, this.texts.size).map((hit) => hit.id)
      : [...this.texts.keys()];

    const hits: Scored[] = [];
    for (const id of candidates) {
      const text = this.texts.get(id);
      if (text && text.includes(needle)) hits.push({ id, score: 1 });
      if (hits.length >= limit) break;
    }
    return hits;
  }

  /**
   * Arbitrary substring inside a definition -- the one case an inverted index
   * cannot answer. At 4 MB of text a direct scan takes a few milliseconds, so
   * no additional index is warranted.
   */
  substring(query: string, limit = 100): number[] {
    const needle = normalise(query);
    if (!needle) return [];
    const out: number[] = [];
    for (const [id, text] of this.texts) {
      if (text.includes(needle)) {
        out.push(id);
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  /** Where the query appears in an entry, for highlighting. */
  offsetsIn(id: number, query: string): Array<[number, number]> {
    const text = this.texts.get(id);
    const needle = normalise(query);
    if (!text || !needle) return [];
    const spans: Array<[number, number]> = [];
    let from = 0;
    for (;;) {
      const at = text.indexOf(needle, from);
      if (at === -1) break;
      spans.push([at, at + needle.length]);
      from = at + needle.length;
      if (spans.length >= 50) break;
    }
    return spans;
  }
}
