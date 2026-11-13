// Kitchen Coach recipe parser (browser / iPhone build).
// Stage 1 (extraction) uses pdf.js, JSZip and DOMParser so everything runs on the device, offline.
// Stage 2 (analysis) mirrors recipe_parser.py exactly - tests/parser.test.mjs checks they agree.

export const MAX_STEPS = 80;
export const MAX_INGREDIENTS = 80;
const MAX_TIMER_SECONDS = 24 * 3600;
const MAX_PDF_PAGES = 60;
const SUPPORTED = [".pdf", ".docx", ".xml", ".xhtml", ".html", ".htm", ".txt"];

export class RecipeError extends Error {}

// ======================================================================================
// Stage 1: extraction
// ======================================================================================

export async function parseRecipeFile(file) {
  const name = file.name || "recipe";
  const dot = name.lastIndexOf(".");
  const suffix = dot >= 0 ? name.slice(dot).toLowerCase() : "";
  const stem = dot >= 0 ? name.slice(0, dot) : name;
  const ex = await extract(suffix, file);
  const result = analyse(ex.lines, ex.titleHint || "", stem, ex.structured || null, ex.warnings || []);
  result.source = ex.source;
  if (!result.steps.length) {
    throw new RecipeError("I couldn't find any method steps in that file. Make sure the recipe has a " +
      "'Method' or 'Instructions' section, or numbered steps.");
  }
  return result;
}

async function extract(suffix, file) {
  if (suffix === ".doc") {
    throw new RecipeError("Old-style Word .doc files can't be read. Open it in Word and use " +
      "File > Save As > Word Document (.docx), then upload that.");
  }
  if (!SUPPORTED.includes(suffix)) {
    throw new RecipeError("Please upload a PDF, Word (.docx), XML, XHTML, HTML or TXT recipe.");
  }
  if (!file.size) throw new RecipeError("That file is empty.");
  const buffer = await file.arrayBuffer();
  if (suffix === ".pdf") return extractPdf(buffer);
  if (suffix === ".docx") return extractDocx(buffer);
  const text = decode(buffer);
  if (suffix === ".txt") return { lines: text.split(/\r\n|\r|\n/), source: "txt" };
  if (suffix === ".xml") return extractXml(text);
  return extractHtml(text, suffix.slice(1), suffix === ".xhtml");
}

function decode(buffer) {
  const bytes = new Uint8Array(buffer);
  if ((bytes[0] === 0xff && bytes[1] === 0xfe) || (bytes[0] === 0xfe && bytes[1] === 0xff)) {
    return new TextDecoder(bytes[0] === 0xff ? "utf-16le" : "utf-16be").decode(bytes);
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder("windows-1252").decode(bytes);
  }
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new RecipeError("A component failed to load. Reload the app and try again."));
    document.head.appendChild(s);
  });
}

// ---- PDF -------------------------------------------------------------------------------
async function extractPdf(buffer) {
  const pdfjs = await import("./vendor/pdf.min.js");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL("./vendor/pdf.worker.min.js", import.meta.url).href;
  let doc;
  try {
    doc = await pdfjs.getDocument({ data: new Uint8Array(buffer), isEvalSupported: false }).promise;
  } catch (err) {
    if (err && err.name === "PasswordException") {
      throw new RecipeError("That PDF is password-protected. Remove the password and try again.");
    }
    throw new RecipeError("That PDF couldn't be opened - it may be damaged.");
  }
  const lines = [];
  const pages = Math.min(doc.numPages, MAX_PDF_PAGES);
  for (let p = 1; p <= pages; p++) {
    const page = await doc.getPage(p);
    const content = await page.getTextContent();
    let line = "", lastY = null, lastEnd = null;
    for (const item of content.items) {
      if (!("str" in item)) continue;
      const x = item.transform[4], y = item.transform[5];
      if (lastY !== null && Math.abs(y - lastY) > Math.max(2, (item.height || 10) * 0.5) && line.trim()) {
        lines.push(line); line = ""; lastEnd = null;
      }
      if (line && lastEnd !== null && x - lastEnd > 1 && !line.endsWith(" ") && !item.str.startsWith(" ")) line += " ";
      line += item.str;
      lastEnd = x + (item.width || 0);
      if (item.hasEOL) { lines.push(line); line = ""; lastEnd = null; }
      if (item.str) lastY = y;
    }
    if (line.trim()) lines.push(line);
  }
  if (lines.join("").replace(/\s/g, "").length < 20) {
    throw new RecipeError("This PDF has no readable text - it is probably a scanned photo. " +
      "Use a text-based PDF, or copy the recipe into Word and upload the .docx.");
  }
  const warnings = doc.numPages > MAX_PDF_PAGES ? [`Only the first ${MAX_PDF_PAGES} pages were read.`] : [];
  return { lines, source: "pdf", warnings };
}

// ---- DOCX ------------------------------------------------------------------------------
const W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

async function extractDocx(buffer) {
  if (!globalThis.JSZip) await loadScript(new URL("./vendor/jszip.min.js", import.meta.url).href);
  let zip;
  try {
    zip = await globalThis.JSZip.loadAsync(buffer);
  } catch {
    throw new RecipeError("That Word file couldn't be opened - make sure it is a .docx file.");
  }
  const read = async (name) => {
    const f = zip.file(name);
    if (!f) return null;
    const xml = new DOMParser().parseFromString(await f.async("string"), "application/xml");
    return xml.getElementsByTagName("parsererror").length ? null : xml;
  };
  const doc = await read("word/document.xml");
  if (!doc) throw new RecipeError("That Word file couldn't be opened - make sure it is a .docx file.");
  const numbering = await read("word/numbering.xml");
  const styles = await read("word/styles.xml");
  const kids = (el, local) => [...el.children].filter((c) => c.namespaceURI === W_NS && c.localName === local);
  const kid = (el, local) => kids(el, local)[0] || null;
  const val = (el, attr = "val") => (el ? el.getAttributeNS(W_NS, attr) || el.getAttribute("w:" + attr) : null);

  const formats = {};
  if (numbering) {
    const abstract = {};
    for (const an of kids(numbering.documentElement, "abstractNum")) {
      const levels = {};
      for (const lvl of kids(an, "lvl")) {
        const fmt = kid(lvl, "numFmt");
        levels[val(lvl, "ilvl") || "0"] = fmt ? val(fmt) || "decimal" : "decimal";
      }
      abstract[val(an, "abstractNumId")] = levels;
    }
    for (const num of kids(numbering.documentElement, "num")) {
      const ref = kid(num, "abstractNumId");
      if (ref) formats[val(num, "numId")] = abstract[val(ref)] || {};
    }
  }
  const styleNum = {};
  if (styles) {
    for (const st of kids(styles.documentElement, "style")) {
      const ppr = kid(st, "pPr");
      const numPr = ppr && kid(ppr, "numPr");
      const nid = numPr && kid(numPr, "numId");
      if (nid) {
        const ilvl = kid(numPr, "ilvl");
        styleNum[val(st, "styleId")] = [val(nid), ilvl ? val(ilvl) : "0"];
      }
    }
  }

  const counters = new Map();
  const lines = [];
  const paraText = (p) => {
    const out = [];
    let parts = [];
    for (const el of p.getElementsByTagNameNS(W_NS, "*")) {
      if (el.localName === "t") parts.push(el.textContent || "");
      else if (el.localName === "tab") parts.push(" ");
      else if (el.localName === "br" || el.localName === "cr") { out.push(parts.join("")); parts = []; }
    }
    out.push(parts.join(""));
    return out;
  };
  const numberingFor = (p) => {
    const ppr = kid(p, "pPr");
    let nid = null, ilvl = null;
    if (ppr) {
      const numPr = kid(ppr, "numPr");
      if (numPr) {
        const n = kid(numPr, "numId"), lv = kid(numPr, "ilvl");
        nid = n ? val(n) : null;
        ilvl = lv ? val(lv) : "0";
      }
      if (nid === null) {
        const ps = kid(ppr, "pStyle");
        if (ps && styleNum[val(ps)]) [nid, ilvl] = styleNum[val(ps)];
      }
    }
    if (!nid || nid === "0") return null;
    return [nid, ilvl || "0"];
  };
  const handlePara = (p) => {
    const texts = paraText(p);
    const num = numberingFor(p);
    if (num && texts.some((t) => t.trim())) {
      const [nid, ilvl] = num;
      const fmt = (formats[nid] || {})[ilvl] || "decimal";
      if (fmt !== "bullet" && fmt !== "none") {
        const key = nid + "|" + ilvl;
        counters.set(key, (counters.get(key) || 0) + 1);
        for (const k of [...counters.keys()]) {
          const [kn, kl] = k.split("|");
          if (kn === nid && Number(kl) > Number(ilvl)) counters.delete(k);
        }
        if (ilvl === "0") texts[0] = `${counters.get(key)}. ${texts[0].trim()}`;
      }
    }
    lines.push(...texts);
  };
  const handleTable = (tbl) => {
    for (const tr of kids(tbl, "tr")) {
      const cells = [];
      for (const tc of kids(tr, "tc")) {
        const cell = [...tc.getElementsByTagNameNS(W_NS, "p")].map((p) => paraText(p).join(" ")).join(" ").trim();
        if (cell) cells.push(cell);
      }
      if (!cells.length) continue;
      if (cells.length > 1 && /^\d{1,2}[.)]?$/.test(cells[0])) {
        lines.push(`${cells[0].replace(/[.)]+$/, "")}. ${cells.slice(1).join(" ")}`);
      } else lines.push(cells.join(" "));
    }
  };
  const walk = (el) => {
    for (const child of el.children) {
      if (child.namespaceURI === W_NS && child.localName === "p") handlePara(child);
      else if (child.namespaceURI === W_NS && child.localName === "tbl") handleTable(child);
      else walk(child);
    }
  };
  const body = kid(doc.documentElement, "body");
  if (body) walk(body);
  if (!lines.some((l) => l.trim())) throw new RecipeError("That Word document has no text in it.");
  return { lines, source: "docx" };
}

// ---- HTML / XHTML ----------------------------------------------------------------------
const INLINE_TAGS = new Set(["a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "font", "i",
  "kbd", "mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr", "img",
  "label", "input", "td", "th", "nobr"]);
const SKIP_TAGS = new Set(["script", "style", "noscript", "template", "svg", "nav", "footer", "form", "button",
  "select", "option", "iframe", "canvas", "object", "head", "math"]);

function sectionLabel(attrs) {
  attrs = attrs.toLowerCase();
  if (attrs.includes("ingredient")) return "Ingredients";
  if (/method|instruction|direction|preparation|steps/.test(attrs)) return "Method";
  return "";
}

function extractHtml(text, source, xhtml = false) {
  let doc = null;
  if (xhtml) {
    doc = new DOMParser().parseFromString(text, "application/xhtml+xml");
    if (doc.getElementsByTagName("parsererror").length) doc = null;
  }
  if (!doc) doc = new DOMParser().parseFromString(text, "text/html");
  return htmlFromDocument(doc, source);
}

function htmlFromDocument(doc, source) {
  let structured = null;
  for (const s of doc.querySelectorAll('script[type="application/ld+json" i]')) {
    structured = findLdRecipe(s.textContent || "");
    if (structured) break;
  }
  const lines = [];
  let buf = [];
  const flush = () => {
    const t = buf.join("").trim();
    if (t) lines.push(t);
    buf = [];
  };
  const walk = (node, lists) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) { buf.push(child.nodeValue); continue; }
      if (child.nodeType !== 1) continue;
      const tag = child.localName.toLowerCase();
      if (SKIP_TAGS.has(tag) || tag === "title") continue;
      if (tag === "td" || tag === "th") { buf.push(" "); walk(child, lists); continue; }
      if (INLINE_TAGS.has(tag)) { walk(child, lists); continue; }
      flush();
      if (tag === "br") continue;
      if (tag === "ol" || tag === "ul") {
        const label = sectionLabel(`${child.getAttribute("class") || ""} ${child.getAttribute("id") || ""}`);
        if (label) lines.push(label);
        const start = child.getAttribute("start") || "1";
        walk(child, [...lists, { ordered: tag === "ol", n: /^\d+$/.test(start) ? Number(start) - 1 : 0 }]);
      } else if (tag === "li" && lists.length && lists[lists.length - 1].ordered) {
        const top = lists[lists.length - 1];
        top.n += 1;
        buf.push(`${top.n}. `);
        walk(child, lists);
      } else {
        walk(child, lists);
      }
      flush();
    }
  };
  const body = doc.body || doc.documentElement;
  walk(body, []);
  flush();
  const h1 = doc.querySelector("h1");
  const titleEl = doc.querySelector("title");
  const hint = ((h1 && h1.textContent) || (titleEl && titleEl.textContent) || "").replace(/\s+/g, " ").trim();
  if (!lines.length && !structured) throw new RecipeError("That page has no readable text in it.");
  return { lines, titleHint: hint, structured, source };
}

export function findLdRecipe(block) {
  let data;
  try { data = JSON.parse(block); } catch { return null; }
  const stack = [data];
  while (stack.length) {
    const item = stack.shift();
    if (Array.isArray(item)) stack.push(...item);
    else if (item && typeof item === "object") {
      const kinds = Array.isArray(item["@type"]) ? item["@type"] : [item["@type"]];
      if (kinds.includes("Recipe") && item.recipeInstructions) return item;
      if (item["@graph"]) stack.push(...(Array.isArray(item["@graph"]) ? item["@graph"] : [item["@graph"]]));
    }
  }
  return null;
}

// ---- generic XML -----------------------------------------------------------------------
function extractXml(text) {
  if (/<!ENTITY/i.test(text)) {
    throw new RecipeError("That XML file uses features that aren't allowed for safety (DTD entities).");
  }
  const doc = new DOMParser().parseFromString(text, "application/xml");
  if (doc.getElementsByTagName("parsererror").length) {
    throw new RecipeError("That XML file isn't valid XML - check it opens in a browser.");
  }
  const root = doc.documentElement;
  if (root.localName.toLowerCase() === "html") return htmlFromDocument(doc, "xml");

  const lines = [];
  let title = "";
  const cache = new Map();
  const local = (el) => el.localName.toLowerCase();
  const fullText = (el) => (el.textContent || "").replace(/\s+/g, " ").trim();
  const fullTextSpaced = (el) => {
    const parts = [];
    const tw = doc.createTreeWalker(el, 4 /* SHOW_TEXT */);
    while (tw.nextNode()) { const t = tw.currentNode.nodeValue.trim(); if (t) parts.push(t); }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };
  const isContainer = (el) => {
    if (cache.has(el)) return cache.get(el);
    const children = [...el.children];
    const names = children.map(local);
    let result;
    if (!children.length) result = false;
    else if (names.length !== new Set(names).size || fullTextSpaced(el).length > 300) result = true;
    else result = children.some(isContainer);
    cache.set(el, result);
    return result;
  };
  const metaNames = { yield: "Serves", servings: "Serves", serves: "Serves", preptime: "Prep time:",
    cooktime: "Cook time:", totaltime: "Total time:" };
  const walk = (el, counter) => {
    const name = local(el);
    if (SKIP_TAGS.has(name) && name !== "head") return;
    if (!title && ["title", "name", "recipename", "recipe_name"].includes(name) && !el.children.length) {
      title = fullText(el);
      return;
    }
    if (metaNames[name] && !el.children.length) {
      if (fullText(el)) lines.push(`${metaNames[name]} ${fullText(el)}`);
      return;
    }
    if (name === "head") cache.set(el, true);
    if (!isContainer(el)) {
      let t = fullTextSpaced(el);
      if (t) {
        if (counter) { counter.n += 1; t = `${counter.n}. ${t}`; }
        lines.push(t);
      }
      return;
    }
    const label = sectionLabel(name);
    if (label) lines.push(label);
    const own = [...el.childNodes];
    const childCounter = ["ol", "steps", "directions", "instructions", "method"].includes(name) ? { n: 0 } : null;
    let seenElement = false;
    for (const node of own) {
      if (node.nodeType === 1) { walk(node, childCounter); seenElement = true; }
      else if ((node.nodeType === 3 || node.nodeType === 4) && node.nodeValue.trim()) {
        lines.push(node.nodeValue.trim());
      }
    }
    void seenElement;
  };
  walk(root, null);
  if (!lines.length) throw new RecipeError("That XML file has no recipe text in it.");
  return { lines, titleHint: title, source: "xml" };
}

// ======================================================================================
// Stage 2: analysis (mirror of recipe_parser.py)
// ======================================================================================

const BULLET_RE = /^(?:[•‣⁃∙▪●◦□☐☑*·\-–—>]+)\s*/;
const JUNK_RE = /^(?:page\s*\d+(?:\s*(?:of|\/)\s*\d+)?|\d{1,3}\s*(?:of|\/)\s*\d{1,3}|https?:\/\/\S+|www\.\S+|print(?: recipe)?|advertisement|jump to recipe|save recipe|rate this recipe|share|pin it|[\W_]+)$/i;
const ING_HEAD_RE = /^(?:the\s+)?(?:ingredients?|you(?:'|’)?ll need|you will need|what you(?:'|’)?ll need|what you need|shopping list)(?:\s+for\b.{0,30})?(?:\s*\(.{0,30}\))?\s*:?$/i;
const METHOD_HEAD_RE = /^(?:the\s+)?(?:method|instructions?|directions?|preparation|steps|how to make(?: it)?|procedure|cooking instructions|to make|to serve|to finish|assembly)(?:\s+for\b.{0,30})?(?:\s*\(.{0,30}\))?\s*:?$/i;
const OTHER_HEAD_RE = /^(?:the\s+)?(?:notes?|tips?|cook(?:'|’)?s notes?|chef(?:'|’)?s notes?|recipe notes?|nutrition(?:al)?(?: information| info| facts)?|equipment|storage|serving suggestions?|variations?|make ahead|freezing|allergens?|reviews?|comments?)\s*:?$/i;
const META_PATTERNS = [
  ["serves", /^(?:serves|servings|portions)\s*:?\s*(.{1,40})$/i],
  ["serves", /^(?:yield|makes)\s*:?\s*(\d.{0,38})$/i],
  ["prep", /^prep(?:aration)?(?:\s*time)?\s*:\s*(.{1,40})$/i],
  ["prep", /^prep(?:aration)?\s+time\s*(.{1,40})$/i],
  ["cook", /^(?:cook(?:ing)?|bake|baking)(?:\s*time)?\s*:\s*(.{1,40})$/i],
  ["cook", /^(?:cook(?:ing)?|bake|baking)\s+time\s*(.{1,40})$/i],
  ["total", /^(?:total(?:\s*time)?|ready in)\s*:?\s*(.{1,40})$/i],
];
const STEP_WORD_RE = /^step\s*(\d{1,2})\s*[.):\-–]?\s*(.*)$/i;
const NUMBERED_RE = /^(\d{1,2})\s*(?:[.)]|:|\s[-–])\s+(.+)$/;
const BARE_NUMBER_RE = /^(\d{1,2})\s+([A-Z].+)$/;
const LONE_NUMBER_RE = /^(\d{1,2})[.)]?$/;
const UNIT_WORDS = "(?:g|kg|mg|ml|l|lb|lbs|oz|tsp|tbsp|tbs|tablespoons?|teaspoons?|cups?|pints?|quarts?|" +
  "litres?|liters?|grams?|kilograms?|ounces?|pounds?|cloves?|tins?|cans?|packs?|packets?|" +
  "sticks?|bunch(?:es)?|handfuls?|pinch(?:es)?|slices?|large|medium|small|x)";
const UNIT_START_RE = new RegExp(`^${UNIT_WORDS}\\b`, "i");
const INGREDIENT_RE = new RegExp(`^(?:\\d+(?:[.,/]\\d+)?\\s*[½¼¾⅓⅔⅛]?|[½¼¾⅓⅔⅛])\\s*(?:-\\s*\\d+\\s*)?${UNIT_WORDS}?\\b`, "i");
const COOK_VERBS = new Set(`add arrange bake baste beat blanch blend boil braise bring brown brush caramelise caramelize
carve check chill chop coat combine cook cool cover cream crumble crush cut deglaze dice discard divide dot drain
drizzle dust fill flip fold fry garnish grate grease grill heat knead layer leave let line marinate mash measure
melt mix pat peel pierce place poach pour preheat prepare press prick put reduce remove repeat rest return roast
roll rub saute sauté scatter season sear serve set shake shred sift simmer slice soak spoon spread sprinkle squeeze
steam stir strain stuff take taste tip toast top toss transfer turn wash whisk wrap`.split(/\s+/));

const FRACTIONS = { "½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125 };
const WORD_NUMBERS = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8,
  nine: 9, ten: 10, eleven: 11, twelve: 12, fifteen: 15, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60,
  ninety: 90, "forty five": 45, "forty-five": 45, "a few": 3, few: 3, several: 5, "a couple of": 2,
  "couple of": 2, "half a": 0.5, "half an": 0.5 };
const VAGUE = new Set(["a few", "few", "several", "a couple of", "couple of"]);
const NUM = "(?:\\d+(?:[.,]\\d+)?(?:\\s*[½¼¾⅓⅔]|\\s+[1-3]/[2-4])?(?:\\s+and\\s+a\\s+half)?|[½¼¾⅓⅔]|[1-3]/[2-4]|" +
  "(?:one|two|three|four)\\s+and\\s+a\\s+half|half\\s+an?|a\\s+couple\\s+of|couple\\s+of|a\\s+few|few|several|" +
  "forty[\\s-]five|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|" +
  "forty|fifty|sixty|ninety|an?)";
const DURATION_SRC = `(?<![\\w.,/])(${NUM})(?:\\s*(?:-|–|—|to|or)\\s*(${NUM}))?\\s*` +
  "(hours?|hrs?|h|minutes?|mins?|seconds?|secs?)(?![a-z])";
const HM_SRC = "(?<![\\w.])(\\d{1,2})\\s*h\\s*(\\d{1,2})(?:\\s*m(?:ins?)?)?(?![a-z\\d])";
const SPLIT_RE = /(?<=[.!?;])\s+(?=[A-Z0-9])|(?<=,)\s+(?=then\b)/;
const TERMINAL_RE = /[.!?:)\]]$/;
const CONNECTOR_END_RE = /(?:[,;\-–]|\b(?:and|or|the|a|an|to|of|with|for|in|into|until|on|at|from|over))$/i;

const isLower = (c) => !!c && c !== c.toUpperCase() && c === c.toLowerCase();
const isDigit = (c) => !!c && c >= "0" && c <= "9";

export function cleanLine(line) {
  line = String(line || "").replace(/ /g, " ").replace(/​/g, "").replace(/\t/g, " ");
  line = line.replace(/\s+/g, " ").trim();
  return line.replace(BULLET_RE, "").trim();
}

function headingKind(line) {
  if (line.length > 48 || line.split(/\s+/).length > 7) return "";
  if (ING_HEAD_RE.test(line)) return "ing";
  if (METHOD_HEAD_RE.test(line)) return "method";
  if (OTHER_HEAD_RE.test(line)) return "other";
  return "";
}

function metaOf(line) {
  if (line.length > 60) return null;
  for (const [key, rx] of META_PATTERNS) {
    const m = line.match(rx);
    if (m) return [key, m[1].trim().replace(/^[ :-]+|[ :-]+$/g, "")];
  }
  return null;
}

function isSubheading(line) {
  if (line.length <= 50 && line.endsWith(":")) return true;
  return /^for the\b/i.test(line) && line.length <= 40 && !TERMINAL_RE.test(line);
}

export function looksLikeIngredient(line) {
  if (line.length > 90 || (TERMINAL_RE.test(line) && line.length > 60)) return false;
  const first = line.toLowerCase().split(/[\s,]/)[0];
  if (COOK_VERBS.has(first) || findDurations(line).length || NUMBERED_RE.test(line) || STEP_WORD_RE.test(line)) return false;
  return INGREDIENT_RE.test(line);
}

function looksLikeInstruction(line) {
  if (looksLikeIngredient(line)) return false;
  const words = line.split(/\s+/).filter(Boolean);
  const first = words.length ? words[0].toLowerCase().replace(/[^a-zé]/g, "") : "";
  return COOK_VERBS.has(first) || line.length > 40 || findDurations(line).length > 0;
}

function numValue(text) {
  let s = text.trim().toLowerCase().replace(/\s+/g, " ");
  let half = 0;
  if (s.endsWith(" and a half")) { s = s.slice(0, -" and a half".length); half = 0.5; }
  if (Object.prototype.hasOwnProperty.call(WORD_NUMBERS, s)) return WORD_NUMBERS[s] + half;
  const m = s.match(/^(\d+(?:[.,]\d+)?)?\s*([½¼¾⅓⅔])?(?:\s*([1-3])\/([2-4]))?$/);
  if (m && (m[1] || m[2] || m[3])) {
    let total = 0;
    if (m[1]) total += parseFloat(m[1].replace(",", "."));
    if (m[2]) total += FRACTIONS[m[2]];
    if (m[3]) total += Number(m[3]) / Number(m[4]);
    return total + half;
  }
  return 0;
}

const unitSeconds = (u) => (u[0].toLowerCase() === "h" ? 3600 : u[0].toLowerCase() === "m" ? 60 : 1);
const pyRound = (x) => {          // Python's round(): halves go to the even number
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
};

export function findDurations(text) {
  const found = [];
  for (const m of text.matchAll(new RegExp(HM_SRC, "gi"))) {
    const secs = Number(m[1]) * 3600 + Number(m[2]) * 60;
    found.push({ start: m.index, end: m.index + m[0].length, lo: secs, hi: secs, vague: false, raw: m[0], unit: "h" });
  }
  for (const m of text.matchAll(new RegExp(DURATION_SRC, "gi"))) {
    const start = m.index;
    if (found.some((f) => f.start <= start && start < f.end)) continue;
    const [, a, b, unit] = m;
    if (unit.toLowerCase() === "h" && /^(an?|half\s+an?)$/i.test(a.trim())) continue;
    const mult = unitSeconds(unit);
    const lo = numValue(a) * mult;
    const hi = b ? numValue(b) * mult : lo;
    if (lo <= 0) continue;
    const before = text.slice(Math.max(0, start - 14), start).toLowerCase();
    if (/\b(?:every|each|per)\s*$/.test(before)) continue;
    found.push({ start, end: start + m[0].length, lo: pyRound(Math.min(lo, hi)), hi: pyRound(Math.max(lo, hi)),
      vague: VAGUE.has(a.trim().toLowerCase().replace(/\s+/g, " ")), raw: m[0], unit: unit[0].toLowerCase() });
  }
  found.sort((x, y) => x.start - y.start);
  const order = { h: 0, m: 1, s: 2 };
  const merged = [];
  for (const f of found) {
    if (merged.length) {
      const prev = merged[merged.length - 1];
      const gap = text.slice(prev.end, f.start);
      if (order[prev.unit] < order[f.unit] && /^\s*(?:,|and|&)?\s*$/.test(gap)) {
        Object.assign(prev, { end: f.end, lo: prev.lo + f.lo, hi: prev.hi + f.hi, vague: prev.vague || f.vague,
          raw: text.slice(prev.start, f.end), unit: f.unit });
        continue;
      }
    }
    merged.push({ ...f });
  }
  return merged;
}

export function formatSeconds(total) {
  total = Math.round(total);
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  const parts = [];
  if (h) parts.push(`${h} hr`);
  if (m) parts.push(`${m} min`);
  if (s || !parts.length) parts.push(`${s} sec`);
  return parts.join(" ");
}

export function timerFor(text) {
  const durations = findDurations(text);
  if (!durations.length) {
    if (/\bovernight\b/i.test(text)) return [0, "Overnight - no timer set. Set your own reminder."];
    return [0, ""];
  }
  const best = durations.reduce((a, d) => (d.lo > a.lo ? d : a));
  const seconds = Math.min(best.lo, MAX_TIMER_SECONDS);
  const notes = [];
  if (best.vague) notes.push(`Recipe says “${best.raw.trim()}” - timer is an estimate.`);
  else if (best.hi > best.lo) {
    notes.push(`Recipe gives ${formatSeconds(best.lo)}–${formatSeconds(best.hi)}. ` +
      "Timer uses the shorter time - check, then add time if needed.");
  }
  if (/\b(?:per|each|on each|on the other)\s+side\b/i.test(text)) {
    notes.push("Timer covers one side - tap Restart timer for the other side.");
  }
  if (durations.length > 1) notes.push("This step mentions more than one time; the longest is used.");
  return [seconds, notes.join(" ")];
}

export function splitStep(text) {
  const sentences = text.split(SPLIT_RE).map((s) => (s || "").trim()).filter(Boolean);
  const flags = sentences.map((s) => findDurations(s).length > 0);
  if (flags.filter(Boolean).length < 2) return [text];
  const chunks = [];
  let current = [];
  sentences.forEach((sentence, i) => {
    current.push(sentence);
    if (flags[i]) { chunks.push(current.join(" ")); current = []; }
  });
  if (current.length) chunks[chunks.length - 1] += " " + current.join(" ");
  return chunks.map(tidyChunk);
}

function tidyChunk(chunk) {
  chunk = chunk.trim().replace(/,+$/, "").trim();
  return chunk ? chunk[0].toUpperCase() + chunk.slice(1) : chunk;
}

function joinWrapped(lines, strict = false) {
  const out = [];
  for (const line of lines) {
    if (out.length) {
      const prev = out[out.length - 1];
      const startsLower = isLower(line[0]);
      const unterminated = !TERMINAL_RE.test(prev);
      if ((strict && startsLower && unterminated) ||
          (!strict && unterminated && (startsLower || (isDigit(line[0]) && !NUMBERED_RE.test(line)) ||
            CONNECTOR_END_RE.test(prev)))) {
        out[out.length - 1] = `${prev} ${line}`;
        continue;
      }
    }
    out.push(line);
  }
  return out;
}

function prettyStem(stem) {
  stem = String(stem || "").replace(/[_-]+/g, " ").trim();
  return stem ? stem[0].toUpperCase() + stem.slice(1) : "My recipe";
}

function cleanTitle(hint) {
  hint = cleanLine(hint);
  hint = hint.split(" | ")[0].trim();
  if (hint.length > 12) hint = hint.replace(/\s+(?:recipe)\s*$/i, "");
  return hint.slice(0, 90);
}

export function analyse(lines, titleHint = "", stem = "", structured = null, warnings = []) {
  warnings = [...(warnings || [])];
  if (structured) return analyseStructured(structured, stem, warnings);

  const cleaned = lines.map(cleanLine).filter((l) => l && !JUNK_RE.test(l));
  const info = {};
  const entries = [];
  let section = null;
  for (const line of cleaned) {
    const meta = metaOf(line);
    if (meta) { if (!(meta[0] in info)) info[meta[0]] = meta[1]; continue; }
    if (LONE_NUMBER_RE.test(line) && section !== "method") continue;
    const kind = headingKind(line);
    if (kind) { section = kind; entries.push([line, "head", kind]); }
    else entries.push([line, "text", section]);
  }

  let title = titleHint ? cleanTitle(titleHint) : "";
  let titleIndex = -1;
  if (!title) {
    for (let i = 0; i < Math.min(6, entries.length); i++) {
      const [text, kind, sec] = entries[i];
      if (kind !== "text" || sec !== null) break;
      if (text.length >= 3 && text.length <= 80 && text.split(/\s+/).length <= 12 && !text.endsWith(".") &&
          !looksLikeIngredient(text) && !NUMBERED_RE.test(text) && !STEP_WORD_RE.test(text)) {
        title = text; titleIndex = i; break;
      }
    }
  }
  if (!title) title = prettyStem(stem);
  else if (titleIndex < 0) {
    for (let i = 0; i < Math.min(6, entries.length); i++) {
      if (entries[i][1] === "text" && entries[i][0].toLowerCase() === title.toLowerCase()) { titleIndex = i; break; }
    }
  }

  const hasMethod = entries.some(([, k, s]) => k === "head" && s === "method");
  const hasIng = entries.some(([, k, s]) => k === "head" && s === "ing");
  let firstMethod = entries.findIndex(([, k, s]) => k === "head" && s === "method");
  if (firstMethod < 0) firstMethod = entries.length;

  let ingLines;
  if (hasIng) ingLines = entries.filter(([, k, s]) => k === "text" && s === "ing").map(([t]) => t);
  else {
    ingLines = entries.filter(([t, k, s], i) => k === "text" && s === null && i !== titleIndex && i < firstMethod &&
      looksLikeIngredient(t)).map(([t]) => t);
  }
  const ingredientSet = new Set(ingLines);
  const ingredients = joinWrapped(ingLines, true).slice(0, MAX_INGREDIENTS);

  const inRegion = (i, text, kind, sec) => {
    if (kind !== "text" || i === titleIndex) return false;
    if (hasMethod) return sec === "method";
    return sec === null && !ingredientSet.has(text);
  };

  const numbered = [];
  let current = null, lastN = 0, pendingNumber = null;
  entries.forEach(([text, kind, sec], i) => {
    if (!inRegion(i, text, kind, sec)) { current = null; pendingNumber = null; return; }
    let n = null, rest = null;
    let m = text.match(STEP_WORD_RE) || text.match(NUMBERED_RE);
    if (m) { n = Number(m[1]); rest = m[2]; }
    else if (hasMethod) {
      m = text.match(BARE_NUMBER_RE);
      if (m && !UNIT_START_RE.test(m[2])) { n = Number(m[1]); rest = m[2]; }
      else {
        m = text.match(LONE_NUMBER_RE);
        if (m) { pendingNumber = Number(m[1]); return; }
      }
    }
    if (n === null && pendingNumber !== null) { n = pendingNumber; rest = text; pendingNumber = null; }
    if (n !== null && (n === lastN + 1 || n === 1)) {
      current = { text: rest.trim() };
      numbered.push(current);
      lastN = n;
    } else if (isSubheading(text)) {
      current = null;
    } else if (current !== null && text.length > 3 && (hasMethod || !looksLikeIngredient(text))) {
      current.text = `${current.text} ${text}`.trim();
    }
  });
  let rawSteps = numbered.map((s) => s.text).filter(Boolean);

  if (rawSteps.length < 2) {
    const region = [];
    entries.forEach(([text, kind, sec], i) => {
      if (inRegion(i, text, kind, sec) && !isSubheading(text) && !LONE_NUMBER_RE.test(text)) region.push(text);
      else if (region.length && region[region.length - 1] !== "\x00") region.push("\x00");
    });
    const paragraphs = [];
    let block = [];
    for (const text of [...region, "\x00"]) {
      if (text === "\x00") { paragraphs.push(...joinWrapped(block)); block = []; }
      else block.push(text);
    }
    if (hasMethod) rawSteps = paragraphs;
    else {
      rawSteps = paragraphs.filter(looksLikeInstruction);
      if (rawSteps.length) {
        warnings.push("No numbered method was found, so the instructions were guessed - " +
          "please check the steps before you start.");
      }
    }
  }

  const steps = buildSteps(rawSteps, warnings);
  return { title, ingredients, info, steps, warnings };
}

function buildSteps(rawSteps, warnings) {
  let steps = [];
  for (let raw of rawSteps) {
    raw = raw.replace(/\s+/g, " ").trim();
    for (const chunk of splitStep(raw)) {
      const [seconds, note] = timerFor(chunk);
      steps.push({ text: chunk, seconds, note });
    }
  }
  if (steps.length > MAX_STEPS) {
    warnings.push(`The recipe had ${steps.length} steps; only the first ${MAX_STEPS} were kept.`);
    steps = steps.slice(0, MAX_STEPS);
  }
  return steps;
}

function stripTags(text) {
  text = String(text ?? "").replace(/<[^>]+>/g, " ");
  text = text.replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&#39;/g, "'").replace(/&quot;/g, '"');
  return text.replace(/\s+/g, " ").trim();
}

export function isoDuration(value) {
  const m = String(value || "").trim().match(/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/i);
  if (!m || !(m[1] || m[2] || m[3] || m[4])) return "";
  const [d, h, mi, s] = m.slice(1).map((g) => Number(g || 0));
  return formatSeconds(d * 86400 + h * 3600 + mi * 60 + s);
}

function analyseStructured(recipe, stem, warnings) {
  const rawSteps = [];
  const collect = (node) => {
    if (typeof node === "string") {
      for (const part of (node.includes("<") ? stripTags(node) : node).split(/\n+/)) {
        if (part.trim()) rawSteps.push(cleanLine(part));
      }
    } else if (Array.isArray(node)) node.forEach(collect);
    else if (node && typeof node === "object") {
      if (node.itemListElement) collect(node.itemListElement);
      else if (node.text) collect(stripTags(node.text));
      else if (node.name) collect(stripTags(node.name));
    }
  };
  collect(recipe.recipeInstructions);
  const numbered = rawSteps.map((s) => s.replace(/^(?:step\s*)?\d{1,2}[.):]\s+/i, ""));
  let ingredients = recipe.recipeIngredient || recipe.ingredients || [];
  if (typeof ingredients === "string") ingredients = [ingredients];
  const info = {};
  let yld = recipe.recipeYield;
  if (Array.isArray(yld)) yld = yld.length ? yld[0] : "";
  if (yld) info.serves = stripTags(yld);
  for (const [key, src] of [["prep", "prepTime"], ["cook", "cookTime"], ["total", "totalTime"]]) {
    const v = isoDuration(recipe[src]);
    if (v) info[key] = v;
  }
  const title = recipe.name ? cleanTitle(stripTags(recipe.name)) : prettyStem(stem);
  return {
    title,
    ingredients: ingredients.map(stripTags).filter(Boolean).slice(0, MAX_INGREDIENTS),
    info,
    steps: buildSteps(numbered, warnings),
    warnings,
  };
}
