# AM Encyclopaedia — web app

Phase 5 is the search engine, headless. No UI yet; correctness is proven
before any screen exists.

## Running the tests

No install step. Node 22 strips the types and runs the tests itself:

```bash
node --experimental-strip-types --test app/tests/normalise.test.ts
node --experimental-strip-types --test app/tests/search.test.ts
```

The data bundle must exist first:

```bash
python3 -I pipeline/build_db.py build/full2/entries.json --out build/dictionary.db
python3 -I pipeline/export_web.py build/dictionary.db --out app/public/data
```

## Zero dependencies

The engine uses nothing but the standard library — no MiniSearch, no SQLite
WASM, no test framework. At 4,000 entries a hand-written inverted index and a
scan over the headword array beat anything that has to be downloaded, parsed
and kept in step with a build.

## Startup

| Step | Cost |
| --- | --- |
| Ready for typing | ~40 ms |
| Headword search (exact, prefix, suffix, substring, fuzzy) | < 1 ms |
| `warm()` the definition index | ~1.7 s, in the background |
| Definition search once warm | ~2 ms |

Building the definition index over 4 MB of text is the one slow step, so it is
lazy. The app paints, accepts typing and answers headword queries immediately,
calls `warm()` when idle, then re-runs the query for the full result set. Pass
`{ definitions: false }` for that fast path.

## Shape

```
src/core/
  normalise.ts            must match pipeline/parse/normalise.py exactly
  data/load.ts            fetches the bundle by relative URL
  search/headwords.ts     in-memory headword matching, Damerau-Levenshtein
  search/definitions.ts   inverted index, BM25, phrase and substring
  search/engine.ts        merges both into ranked bands
```

`normalise.ts` and `normalise.py` are the one coupling that fails silently: a
query normalised differently from the stored text matches nothing and reads as
a broken search engine. 251 shared fixtures pin them together.
