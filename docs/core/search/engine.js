/**
 * The public search API: two engines merged into one ranked list.
 *
 * Results carry the band they came from rather than arriving as one
 * undifferentiated list, so the interface can group them ("in headwords", "in
 * definitions", "did you mean") and so ranking can be tuned later without
 * touching either engine.
 */

import { HeadwordIndex, DISPLAY, ID, LETTER, PAGE, PLAIN } from "./headwords.js";
                                                  
import { DefinitionIndex } from "./definitions.js";
import { normalise } from "../normalise.js";

/**
 * Ordered best to worst; the number is the rank band.
 *
 * A const object rather than an enum: an enum emits runtime code, which rules
 * out Node's type-stripping and any build step that only erases types.
 */
export const Band = {
  ExactHeadword: 0,
  HeadwordPrefix: 1,
  HeadwordContains: 2,
  DefinitionPhrase: 3,
  DefinitionTerms: 4,
  FuzzyHeadword: 5,
}         ;

                                                    

export const BAND_LABEL                       = {
  [Band.ExactHeadword]: "Exact match",
  [Band.HeadwordPrefix]: "Begins with",
  [Band.HeadwordContains]: "Contains",
  [Band.DefinitionPhrase]: "Phrase in definition",
  [Band.DefinitionTerms]: "In definitions",
  [Band.FuzzyHeadword]: "Did you mean",
};

                      
             
                   
                 
                      
             
                
  

                             
                 
                                                              
              
                                                                  
                         
     
                                                               
    
                                                                              
                                                                            
                                                                          
                                                                     
     
                        
  

                     
             
                   
               
                      
                  
                       
  

                                                                                   

export class Dictionary {
           headwords               ;
          definitionIndex                         = null;
                   entries                    ;
                   crossrefs                         ;
                   rowById                          ;

  constructor(
    rows                        ,
    entries                    ,
    crossrefs                          = new Map(),
  ) {
    this.headwords = new HeadwordIndex(rows);
    this.entries = entries;
    this.crossrefs = crossrefs;
    this.rowById = new Map(rows.map((row) => [row[ID], row]));
  }

  /**
   * The definition index, built on first use.
   *
   * Building it over 4 MB of text takes about 1.7 seconds on a laptop and
   * several on a mid-range phone -- long enough to stall startup if it ran
   * eagerly. Headword search needs none of it and is ready immediately, which
   * covers most queries, so the app paints, accepts typing, and calls warm()
   * once idle. Until then a definition query simply builds it first.
   */
  get definitions()                  {
    if (this.definitionIndex === null) {
      this.definitionIndex = new DefinitionIndex(
        [...this.entries.values()].map((entry) => [entry.id, entry.body]         ),
      );
    }
    return this.definitionIndex;
  }

  /** True once definition search is ready without a pause. */
  get isWarm()          {
    return this.definitionIndex !== null;
  }

  /** Build the definition index ahead of need. Call when the UI is idle. */
  warm()       {
    void this.definitions;
  }

  get size()         {
    return this.entries.size;
  }

  entry(id        )                    {
    return this.entries.get(id);
  }

  referencesFrom(id        )             {
    return this.crossrefs.get(id) ?? [];
  }

  /** Entries whose cross-references point at this one. */
  referencesTo(id        )           {
    const out           = [];
    for (const [from, refs] of this.crossrefs) {
      if (refs.some((ref) => ref.toEntry === id)) out.push(from);
    }
    return out;
  }

  /**
   * Search every field, ranked.
   *
   * Each id appears once, in the best band it qualified for: an entry whose
   * headword matches exactly is not repeated lower down for also mentioning
   * the term in its text.
   */
  search(query        , options                = {})           {
    const limit = options.limit ?? 50;
    const trimmed = query.trim();
    if (!trimmed) return [];

    const seen = new Set        ();
    const results           = [];

    const push = (id        , band      , score        ) => {
      if (seen.has(id)) return;
      const row = this.rowById.get(id);
      if (!row) return;
      seen.add(id);
      results.push({
        id,
        headword: row[DISPLAY],
        letter: row[LETTER],
        printedPage: row[PAGE],
        band,
        score,
      });
    };

    const wanted = (band      ) => options.only === undefined || options.only === band;

    if (wanted(Band.ExactHeadword)) {
      for (const id of this.headwords.exact(trimmed)) push(id, Band.ExactHeadword, 1000);
    }
    if (wanted(Band.HeadwordPrefix)) {
      for (const id of this.headwords.prefix(trimmed)) push(id, Band.HeadwordPrefix, 500);
    }
    if (wanted(Band.HeadwordContains)) {
      for (const id of this.headwords.substring(trimmed)) {
        push(id, Band.HeadwordContains, 250);
      }
    }
    const searchDefinitions = options.definitions ?? true;
    if (searchDefinitions && wanted(Band.DefinitionPhrase) && trimmed.includes(" ")) {
      for (const hit of this.definitions.phrase(trimmed)) {
        push(hit.id, Band.DefinitionPhrase, 100);
      }
    }
    if (searchDefinitions && wanted(Band.DefinitionTerms)) {
      for (const hit of this.definitions.search(trimmed)) {
        push(hit.id, Band.DefinitionTerms, hit.score);
      }
    }

    const nothingSolid = results.length === 0;
    const askedFor = options.includeFuzzy ?? nothingSolid;
    if (askedFor && wanted(Band.FuzzyHeadword)) {
      for (const hit of this.headwords.fuzzy(trimmed)) {
        push(hit.id, Band.FuzzyHeadword, 10 - hit.distance);
      }
    }

    results.sort((a, b) => a.band - b.band || b.score - a.score ||
      a.headword.localeCompare(b.headword));
    return results.slice(0, limit);
  }

  /** As-you-type suggestions: headwords only, so it stays instant. */
  suggest(query        , limit = 8)           {
    return this.search(query, {
      limit,
      includeFuzzy: false,
      definitions: false,
    }).filter((result) => result.band <= Band.HeadwordContains);
  }

  /** Where to highlight the query inside an entry's body. */
  highlights(id        , query        )                          {
    return this.definitions.offsetsIn(id, query);
  }

  /** The A–Z index. */
  letterCounts()                         {
    return this.headwords.letterCounts();
  }

  byLetter(letter        )           {
    return this.headwords.byLetter(letter).map((id) => {
      const row = this.rowById.get(id) ;
      return {
        id,
        headword: row[DISPLAY],
        letter: row[LETTER],
        printedPage: row[PAGE],
        band: Band.ExactHeadword,
        score: 0,
      };
    });
  }

  /** Browse by the page number printed in the book. */
  byPage(printedPage        )           {
    return [...this.entries.values()]
      .filter((entry) => entry.printedPage === printedPage)
      .map((entry) => {
        const row = this.rowById.get(entry.id) ;
        return {
          id: entry.id,
          headword: row[DISPLAY],
          letter: row[LETTER],
          printedPage: row[PAGE],
          band: Band.ExactHeadword,
          score: 0,
        };
      });
  }
}

export { normalise, PLAIN };
