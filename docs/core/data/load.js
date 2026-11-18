/**
 * Loading the dictionary bundle.
 *
 * Data is fetched from a relative URL rather than reached for through the
 * service worker. The same code path then works online, offline once the
 * worker has cached it, and inside a WebView if this is ever wrapped as a
 * native app -- which is the decision that keeps the store option open at no
 * cost now.
 */

                                                          
                                                           
import { Dictionary } from "../search/engine.js";

                    
                       
                        
                         
                  
                     
                              
                                        
  

                    
                                                                  
                                                                    
                                                
                                                                    
  

export function buildDictionary(
  headwords               ,
  file             ,
)             {
  const entries = new Map               ();
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

  const crossrefs = new Map                    ();
  for (const [key, value] of Object.entries(file.crossrefs ?? {})) {
    crossrefs.set(
      Number(key),
      value.map(([toEntry, rawTarget, kind]) => ({ toEntry, rawTarget, kind })),
    );
  }

  return new Dictionary(headwords, entries, crossrefs);
}

/**
 * Where the data sits, resolved from this module's own URL.
 *
 * A plain relative path is resolved against the *page* URL, and a page served
 * without a trailing slash drops its last segment: "data/entries.json" under
 * /artifact/abc123 asks for /artifact/data/entries.json, which does not exist.
 * This module's URL is stable whatever the page is called, so the data is
 * found from it instead.
 */
function dataUrl(name        )         {
  return new URL(`../../data/${name}`, import.meta.url).href;
}

/** Fetch and assemble the dictionary. */
export async function loadDictionary()           
                         
             
   {
  const [headwords, file, meta] = await Promise.all([
    fetchJson               (dataUrl("headwords.json")),
    fetchJson             (dataUrl("entries.json")),
    fetchJson      (dataUrl("meta.json")),
  ]);
  return { dictionary: buildDictionary(headwords, file), meta };
}

async function fetchJson   (url        )             {
  let response          ;
  try {
    response = await fetch(url);
  } catch (cause) {
    throw new Error(`${url} could not be reached (${String(cause)})`);
  }
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status} ${response.statusText}`);
  }
  try {
    return (await response.json())     ;
  } catch (cause) {
    throw new Error(`${url} is not valid JSON (${String(cause)})`);
  }
}
