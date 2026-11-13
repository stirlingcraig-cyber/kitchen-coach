"""Kitchen Coach recipe parser.

Two stages:
  1. extract()  - turn a PDF / DOCX / XML / XHTML / HTML / TXT file into ordered text lines
                  (plus an optional title hint and schema.org structured recipe).
  2. analyse()  - work out the title, ingredients, recipe info and timed steps.

The analysis stage is mirrored in web/parser.js so the iPhone (offline) build behaves the
same way as the Windows build. tests/test_parity.py + tests/parser.test.mjs keep the two in step.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from defusedxml import ElementTree as SafeET  # blocks XXE / entity-expansion attacks

MAX_STEPS = 80
MAX_INGREDIENTS = 80
MAX_TIMER_SECONDS = 24 * 3600
MAX_PDF_PAGES = 60

SUPPORTED = {".pdf", ".docx", ".xml", ".xhtml", ".html", ".htm", ".txt"}


class RecipeError(Exception):
    """An error whose message is safe and helpful to show to the cook."""


@dataclass
class Extracted:
    lines: list[str]
    title_hint: str = ""
    structured: dict | None = None
    source: str = ""
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Stage 1: extraction
# --------------------------------------------------------------------------------------

def extract(filename: str, data: bytes) -> Extracted:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".doc":
        raise RecipeError("Old-style Word .doc files can't be read. Open it in Word and use "
                          "File > Save As > Word Document (.docx), then upload that.")
    if suffix not in SUPPORTED:
        raise RecipeError("Please upload a PDF, Word (.docx), XML, XHTML, HTML or TXT recipe.")
    if not data:
        raise RecipeError("That file is empty.")

    if suffix == ".pdf":
        return _extract_pdf(data)
    if suffix == ".docx":
        return _extract_docx(data)
    if suffix == ".xml":
        return _extract_xml(data)
    text = _decode(data)
    if suffix == ".txt":
        return Extracted(lines=text.splitlines(), source="txt")
    return _extract_html(text, source=suffix.lstrip("."))


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ---- PDF -----------------------------------------------------------------------------

def _extract_pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise RecipeError("That PDF is password-protected. Remove the password and try again.")
            except RecipeError:
                raise
            except Exception:
                raise RecipeError("That PDF is password-protected. Remove the password and try again.")
        pages = reader.pages[:MAX_PDF_PAGES]
        text = "\n".join((page.extract_text() or "") for page in pages)
    except RecipeError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:  # damaged / not a PDF
        raise RecipeError("That PDF couldn't be opened - it may be damaged.") from exc

    if len(re.sub(r"\s", "", text)) < 20:
        raise RecipeError("This PDF has no readable text - it is probably a scanned photo. "
                          "Use a text-based PDF, or copy the recipe into Word and upload the .docx.")
    warnings = []
    if len(reader.pages) > MAX_PDF_PAGES:
        warnings.append(f"Only the first {MAX_PDF_PAGES} pages were read.")
    return Extracted(lines=text.splitlines(), source="pdf", warnings=warnings)


# ---- DOCX ----------------------------------------------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_docx(data: bytes) -> Extracted:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        doc_xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise RecipeError("That Word file couldn't be opened - make sure it is a .docx file.") from exc

    def optional(name):
        try:
            return SafeET.fromstring(zf.read(name))
        except KeyError:
            return None

    root = SafeET.fromstring(doc_xml)
    numbering = optional("word/numbering.xml")
    styles = optional("word/styles.xml")

    # numId -> {ilvl: numFmt}
    formats: dict[str, dict[str, str]] = {}
    if numbering is not None:
        abstract = {}
        for an in numbering.findall(f"{W}abstractNum"):
            levels = {}
            for lvl in an.findall(f"{W}lvl"):
                fmt = lvl.find(f"{W}numFmt")
                levels[lvl.get(f"{W}ilvl", "0")] = fmt.get(f"{W}val", "decimal") if fmt is not None else "decimal"
            abstract[an.get(f"{W}abstractNumId")] = levels
        for num in numbering.findall(f"{W}num"):
            ref = num.find(f"{W}abstractNumId")
            if ref is not None:
                formats[num.get(f"{W}numId")] = abstract.get(ref.get(f"{W}val"), {})

    # paragraph style -> numId (for "List Number" style lists)
    style_num: dict[str, tuple[str, str]] = {}
    if styles is not None:
        for st in styles.findall(f"{W}style"):
            num_pr = st.find(f"{W}pPr/{W}numPr")
            if num_pr is not None:
                nid = num_pr.find(f"{W}numId")
                ilvl = num_pr.find(f"{W}ilvl")
                if nid is not None:
                    style_num[st.get(f"{W}styleId")] = (nid.get(f"{W}val"), ilvl.get(f"{W}val") if ilvl is not None else "0")

    counters: dict[tuple[str, str], int] = {}
    lines: list[str] = []

    def para_text(p) -> list[str]:
        parts, out = [], []
        for el in p.iter():
            tag = el.tag
            if tag == f"{W}t":
                parts.append(el.text or "")
            elif tag == f"{W}tab":
                parts.append(" ")
            elif tag in (f"{W}br", f"{W}cr"):
                out.append("".join(parts))
                parts = []
        out.append("".join(parts))
        return out

    def numbering_for(p):
        ppr = p.find(f"{W}pPr")
        nid = ilvl = None
        if ppr is not None:
            num_pr = ppr.find(f"{W}numPr")
            if num_pr is not None:
                n = num_pr.find(f"{W}numId")
                lv = num_pr.find(f"{W}ilvl")
                nid = n.get(f"{W}val") if n is not None else None
                ilvl = lv.get(f"{W}val") if lv is not None else "0"
            if nid is None:
                ps = ppr.find(f"{W}pStyle")
                if ps is not None and ps.get(f"{W}val") in style_num:
                    nid, ilvl = style_num[ps.get(f"{W}val")]
        if not nid or nid == "0":
            return None
        return nid, ilvl or "0"

    def handle_para(p):
        texts = para_text(p)
        num = numbering_for(p)
        if num and any(t.strip() for t in texts):
            nid, ilvl = num
            fmt = formats.get(nid, {}).get(ilvl, "decimal")
            if fmt not in ("bullet", "none"):
                key = (nid, ilvl)
                counters[key] = counters.get(key, 0) + 1
                for k in list(counters):  # restart deeper levels
                    if k[0] == nid and int(k[1]) > int(ilvl):
                        del counters[k]
                if ilvl == "0":
                    texts[0] = f"{counters[key]}. {texts[0].strip()}"
        lines.extend(texts)

    def handle_table(tbl):
        for tr in tbl.findall(f"{W}tr"):
            cells = []
            for tc in tr.findall(f"{W}tc"):
                cell = " ".join(" ".join(para_text(p)) for p in tc.iter(f"{W}p")).strip()
                if cell:
                    cells.append(cell)
            if not cells:
                continue
            if len(cells) > 1 and re.fullmatch(r"\d{1,2}[.)]?", cells[0]):
                lines.append(f"{cells[0].rstrip('.)')}. {' '.join(cells[1:])}")
            else:
                lines.append(" ".join(cells))

    def walk(el):
        for child in el:
            if child.tag == f"{W}p":
                handle_para(child)
            elif child.tag == f"{W}tbl":
                handle_table(child)
            else:
                walk(child)  # content controls, custom XML, etc.

    body = root.find(f"{W}body")
    if body is not None:
        walk(body)
    if not any(l.strip() for l in lines):
        raise RecipeError("That Word document has no text in it.")
    return Extracted(lines=lines, source="docx")


# ---- HTML / XHTML ----------------------------------------------------------------------

INLINE_TAGS = {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "font", "i",
               "kbd", "mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time",
               "u", "var", "wbr", "img", "label", "input", "td", "th", "nobr"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "nav", "footer", "form", "button",
             "select", "option", "iframe", "canvas", "object", "head", "math"}
VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "wbr", "area", "base", "col", "embed",
             "source", "track", "param"}


def _section_label(attrs: str) -> str:
    attrs = attrs.lower()
    if "ingredient" in attrs:
        return "Ingredients"
    if re.search(r"method|instruction|direction|preparation|steps", attrs):
        return "Method"
    return ""


class _HTMLLines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip_depth = 0
        self.lists: list[list] = []  # [is_ordered, counter]
        self.title = ""
        self.h1 = ""
        self._in_title = False
        self._in_h1 = False
        self._ld = False
        self.ld_blocks: list[str] = []

    def flush(self):
        text = "".join(self.buf).strip()
        if text:
            self.lines.append(text)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._ld = True
            self.ld_blocks.append("")
            return
        if tag == "title":
            self._in_title = True
            return
        if self.skip_depth or tag in SKIP_TAGS:
            if tag not in VOID_TAGS:
                self.skip_depth += 1
            return
        if tag in ("td", "th"):
            self.buf.append(" ")
            return
        if tag in INLINE_TAGS:
            return
        self.flush()
        if tag == "br":
            return
        if tag == "h1" and not self.h1:
            self._in_h1 = True
        if tag in ("ol", "ul"):
            label = _section_label(f"{a.get('class', '')} {a.get('id', '')}")
            if label:
                self.lines.append(label)
            start = a.get("start", "1")
            self.lists.append([tag == "ol", (int(start) - 1) if start.isdigit() else 0])
        elif tag == "li" and self.lists and self.lists[-1][0]:
            self.lists[-1][1] += 1
            self.buf.append(f"{self.lists[-1][1]}. ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self._ld:
            self._ld = False
            return
        if tag == "title":
            self._in_title = False
            return
        if self.skip_depth:
            if tag in SKIP_TAGS or tag not in VOID_TAGS:
                self.skip_depth -= 1
            return
        if tag in INLINE_TAGS:
            return
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.h1 = self.h1.strip()
        self.flush()
        if tag in ("ol", "ul") and self.lists:
            self.lists.pop()

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br" and not self.skip_depth:
            self.flush()

    def handle_data(self, data):
        if self._ld:
            self.ld_blocks[-1] += data
            return
        if self._in_title:
            self.title += data
            return
        if self.skip_depth:
            return
        if self._in_h1:
            self.h1 += data
        self.buf.append(data)


def _extract_html(text: str, source: str = "html") -> Extracted:
    parser = _HTMLLines()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # html.parser is lenient; this is a last resort
        raise RecipeError("That web page couldn't be read.") from exc
    parser.flush()
    structured = None
    for block in parser.ld_blocks:
        structured = find_ld_recipe(block)
        if structured:
            break
    hint = parser.h1 or parser.title
    hint = re.sub(r"\s+", " ", hint).strip()
    if not parser.lines and not structured:
        raise RecipeError("That page has no readable text in it.")
    return Extracted(lines=parser.lines, title_hint=hint, structured=structured, source=source)


def find_ld_recipe(block: str) -> dict | None:
    try:
        data = json.loads(block)
    except (ValueError, TypeError):
        return None
    stack = [data]
    while stack:
        item = stack.pop(0)
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Recipe" in kinds and item.get("recipeInstructions"):
                return item
            if "@graph" in item:
                stack.extend(item["@graph"] if isinstance(item["@graph"], list) else [item["@graph"]])
    return None


# ---- generic XML -----------------------------------------------------------------------

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _extract_xml(data: bytes) -> Extracted:
    try:
        root = SafeET.fromstring(data)  # bytes, so the file's own encoding declaration is honoured
    except SafeET.ParseError as exc:
        raise RecipeError("That XML file isn't valid XML - check it opens in a browser.") from exc
    except Exception as exc:  # defusedxml forbids DTD entities etc.
        raise RecipeError("That XML file uses features that aren't allowed for safety (DTD entities).") from exc

    if _local(root.tag) == "html":
        return _extract_html(_decode(data), source="xml")

    lines: list[str] = []
    title = ""
    container_cache: dict[int, bool] = {}

    def full_text(el) -> str:
        return re.sub(r"\s+", " ", " ".join(t.strip() for t in el.itertext() if t.strip())).strip()

    def is_container(el) -> bool:
        key = id(el)
        if key in container_cache:
            return container_cache[key]
        children = list(el)
        names = [_local(c.tag) for c in children]
        result = False
        if not children:
            result = False
        elif len(names) != len(set(names)) or len(full_text(el)) > 300:
            result = True
        else:
            result = any(is_container(c) for c in children)
        container_cache[key] = result
        return result

    meta_names = {"yield": "Serves", "servings": "Serves", "serves": "Serves", "preptime": "Prep time:",
                  "cooktime": "Cook time:", "totaltime": "Total time:"}

    def walk(el, ordered_counter=None):
        nonlocal title
        name = _local(el.tag)
        if name in SKIP_TAGS - {"head"}:
            return
        if not title and name in ("title", "name", "recipename", "recipe_name") and not list(el):
            title = (el.text or "").strip()
            return
        if name in meta_names and not list(el):
            if (el.text or "").strip():
                lines.append(f"{meta_names[name]} {el.text.strip()}")
            return
        if name == "head":
            container_cache[id(el)] = True
        if not is_container(el):
            text = full_text(el)
            if text:
                if ordered_counter is not None:
                    ordered_counter[0] += 1
                    text = f"{ordered_counter[0]}. {text}"
                lines.append(text)
            return
        label = _section_label(name)
        if label:
            lines.append(label)
        if el.text and el.text.strip():
            lines.append(el.text.strip())
        counter = [0] if name in ("ol", "steps", "directions", "instructions", "method") else None
        for child in el:
            walk(child, counter)
            if child.tail and child.tail.strip():
                lines.append(child.tail.strip())

    walk(root)
    if not lines:
        raise RecipeError("That XML file has no recipe text in it.")
    return Extracted(lines=lines, title_hint=title, source="xml")


# --------------------------------------------------------------------------------------
# Stage 2: analysis  (keep in step with web/parser.js)
# --------------------------------------------------------------------------------------

BULLET_RE = re.compile(r"^(?:[•‣⁃∙▪●◦□☐☑*·\-–—>]+)\s*")
JUNK_RE = re.compile(
    r"^(?:page\s*\d+(?:\s*(?:of|/)\s*\d+)?|\d{1,3}\s*(?:of|/)\s*\d{1,3}|https?://\S+|www\.\S+|print(?: recipe)?|"
    r"advertisement|jump to recipe|save recipe|rate this recipe|share|pin it|[\W_]+)$", re.I)
ING_HEAD_RE = re.compile(
    r"^(?:the\s+)?(?:ingredients?|you(?:'|’)?ll need|you will need|what you(?:'|’)?ll need|what you need|shopping list)"
    r"(?:\s+for\b.{0,30})?(?:\s*\(.{0,30}\))?\s*:?$", re.I)
METHOD_HEAD_RE = re.compile(
    r"^(?:the\s+)?(?:method|instructions?|directions?|preparation|steps|how to make(?: it)?|procedure|"
    r"cooking instructions|to make|to serve|to finish|assembly)(?:\s+for\b.{0,30})?(?:\s*\(.{0,30}\))?\s*:?$", re.I)
OTHER_HEAD_RE = re.compile(
    r"^(?:the\s+)?(?:notes?|tips?|cook(?:'|’)?s notes?|chef(?:'|’)?s notes?|recipe notes?|nutrition(?:al)?"
    r"(?: information| info| facts)?|equipment|storage|serving suggestions?|variations?|make ahead|freezing|"
    r"allergens?|reviews?|comments?)\s*:?$", re.I)
META_PATTERNS = [
    ("serves", re.compile(r"^(?:serves|servings|portions)\s*:?\s*(.{1,40})$", re.I)),
    ("serves", re.compile(r"^(?:yield|makes)\s*:?\s*(\d.{0,38})$", re.I)),
    ("prep", re.compile(r"^prep(?:aration)?(?:\s*time)?\s*:\s*(.{1,40})$", re.I)),
    ("prep", re.compile(r"^prep(?:aration)?\s+time\s*(.{1,40})$", re.I)),
    ("cook", re.compile(r"^(?:cook(?:ing)?|bake|baking)(?:\s*time)?\s*:\s*(.{1,40})$", re.I)),
    ("cook", re.compile(r"^(?:cook(?:ing)?|bake|baking)\s+time\s*(.{1,40})$", re.I)),
    ("total", re.compile(r"^(?:total(?:\s*time)?|ready in)\s*:?\s*(.{1,40})$", re.I)),
]
STEP_WORD_RE = re.compile(r"^step\s*(\d{1,2})\s*[.):\-–]?\s*(.*)$", re.I)
NUMBERED_RE = re.compile(r"^(\d{1,2})\s*(?:[.)]|:|\s[-–])\s+(.+)$")
BARE_NUMBER_RE = re.compile(r"^(\d{1,2})\s+([A-Z].+)$")
LONE_NUMBER_RE = re.compile(r"^(\d{1,2})[.)]?$")
UNIT_WORDS = (r"(?:g|kg|mg|ml|l|lb|lbs|oz|tsp|tbsp|tbs|tablespoons?|teaspoons?|cups?|pints?|quarts?|"
              r"litres?|liters?|grams?|kilograms?|ounces?|pounds?|cloves?|tins?|cans?|packs?|packets?|"
              r"sticks?|bunch(?:es)?|handfuls?|pinch(?:es)?|slices?|large|medium|small|x)")
QTY_START_RE = re.compile(r"^(?:\d+(?:[.,/]\d+)?|[½¼¾⅓⅔⅛]|a|an|one|two|three|four|half)\b", re.I)
INGREDIENT_RE = re.compile(rf"^(?:\d+(?:[.,/]\d+)?\s*[½¼¾⅓⅔⅛]?|[½¼¾⅓⅔⅛])\s*(?:-\s*\d+\s*)?{UNIT_WORDS}?\b", re.I)
COOK_VERBS = set("""add arrange bake baste beat blanch blend boil braise bring brown brush caramelise caramelize
carve check chill chop coat combine cook cool cover cream crumble crush cut deglaze dice discard divide dot drain
drizzle dust fill flip fold fry garnish grate grease grill heat knead layer leave let line marinate mash measure
melt mix pat peel pierce place poach pour preheat prepare press prick put reduce remove repeat rest return roast
roll rub saute sauté scatter season sear serve set shake shred sift simmer slice soak spoon spread sprinkle squeeze
steam stir strain stuff take taste tip toast top toss transfer turn wash whisk wrap""".split())

FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
                "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90, "forty five": 45,
                "forty-five": 45, "a few": 3, "few": 3, "several": 5, "a couple of": 2, "couple of": 2,
                "half a": 0.5, "half an": 0.5}
VAGUE = {"a few", "few", "several", "a couple of", "couple of"}
_NUM = (r"(?:\d+(?:[.,]\d+)?(?:\s*[½¼¾⅓⅔]|\s+[1-3]/[2-4])?(?:\s+and\s+a\s+half)?|[½¼¾⅓⅔]|[1-3]/[2-4]|"
        r"(?:one|two|three|four)\s+and\s+a\s+half|half\s+an?|a\s+couple\s+of|couple\s+of|a\s+few|few|several|"
        r"forty[\s-]five|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|"
        r"forty|fifty|sixty|ninety|an?)")
DURATION_RE = re.compile(
    rf"(?<![\w.,/])(?P<a>{_NUM})(?:\s*(?:-|–|—|to|or)\s*(?P<b>{_NUM}))?\s*"
    r"(?P<u>hours?|hrs?|h|minutes?|mins?|seconds?|secs?)(?![a-z])", re.I)
HM_RE = re.compile(r"(?<![\w.])(\d{1,2})\s*h\s*(\d{1,2})(?:\s*m(?:ins?)?)?(?![a-z\d])", re.I)
SPLIT_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9])|(?<=,)\s+(?=then\b)")
TERMINAL_RE = re.compile(r"[.!?:)\]]$")
CONNECTOR_END_RE = re.compile(r"(?:[,;\-–]|\b(?:and|or|the|a|an|to|of|with|for|in|into|until|on|at|from|over))$", re.I)


def clean_line(line: str) -> str:
    line = (line or "").replace(" ", " ").replace("​", "").replace("\t", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return BULLET_RE.sub("", line).strip()


def heading_kind(line: str) -> str:
    if len(line) > 48 or len(line.split()) > 7:
        return ""
    if ING_HEAD_RE.match(line):
        return "ing"
    if METHOD_HEAD_RE.match(line):
        return "method"
    if OTHER_HEAD_RE.match(line):
        return "other"
    return ""


def meta_of(line: str):
    if len(line) > 60:
        return None
    for key, rx in META_PATTERNS:
        m = rx.match(line)
        if m:
            return key, m.group(1).strip(" :-")
    return None


def is_subheading(line: str) -> bool:
    if len(line) <= 50 and line.endswith(":"):
        return True
    return bool(re.match(r"^for the\b", line, re.I)) and len(line) <= 40 and not TERMINAL_RE.search(line)


def looks_like_ingredient(line: str) -> bool:
    if len(line) > 90 or TERMINAL_RE.search(line) and len(line) > 60:
        return False
    first = re.split(r"[\s,]", line.lower(), maxsplit=1)[0]
    if first in COOK_VERBS or find_durations(line) or NUMBERED_RE.match(line) or STEP_WORD_RE.match(line):
        return False
    return bool(INGREDIENT_RE.match(line))


def looks_like_instruction(line: str) -> bool:
    if looks_like_ingredient(line):
        return False
    first = re.sub(r"[^a-zé]", "", line.split()[0].lower()) if line.split() else ""
    return first in COOK_VERBS or len(line) > 40 or bool(find_durations(line))


def _num_value(text: str) -> float:
    s = re.sub(r"\s+", " ", text.strip().lower())
    half = 0.0
    if s.endswith(" and a half"):
        s = s[: -len(" and a half")]
        half = 0.5
    if s in WORD_NUMBERS:
        return WORD_NUMBERS[s] + half
    total = 0.0
    m = re.match(r"^(\d+(?:[.,]\d+)?)?\s*([½¼¾⅓⅔])?(?:\s*([1-3])/([2-4]))?$", s)
    if m and any(m.groups()):
        if m.group(1):
            total += float(m.group(1).replace(",", "."))
        if m.group(2):
            total += FRACTIONS[m.group(2)]
        if m.group(3):
            total += int(m.group(3)) / int(m.group(4))
        return total + half
    return 0.0


def _unit_seconds(unit: str) -> int:
    u = unit.lower()
    if u.startswith("h"):
        return 3600
    if u.startswith("m"):
        return 60
    return 1


def find_durations(text: str) -> list[dict]:
    """Every timer-worthy duration in text: {start,end,lo,hi,vague,raw,unit}."""
    found = []
    for m in HM_RE.finditer(text):
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60
        found.append({"start": m.start(), "end": m.end(), "lo": secs, "hi": secs, "vague": False,
                      "raw": m.group(0), "unit": "h"})
    for m in DURATION_RE.finditer(text):
        if any(f["start"] <= m.start() < f["end"] for f in found):
            continue
        a, b, unit = m.group("a"), m.group("b"), m.group("u")
        if unit.lower() == "h" and re.match(r"^(an?|half\s+an?)$", a.strip(), re.I):
            continue  # "a h..." is not a duration
        mult = _unit_seconds(unit)
        lo = _num_value(a) * mult
        hi = (_num_value(b) * mult) if b else lo
        if lo <= 0:
            continue
        before = text[max(0, m.start() - 14): m.start()].lower()
        if re.search(r"\b(?:every|each|per)\s*$", before):
            continue
        found.append({"start": m.start(), "end": m.end(), "lo": round(min(lo, hi)), "hi": round(max(lo, hi)),
                      "vague": re.sub(r"\s+", " ", a.strip().lower()) in VAGUE, "raw": m.group(0),
                      "unit": unit.lower()[0]})
    found.sort(key=lambda f: f["start"])
    # combine "1 hour 30 minutes", "2 minutes and 30 seconds"
    merged = []
    for f in found:
        if merged:
            prev = merged[-1]
            gap = text[prev["end"]:f["start"]]
            order = {"h": 0, "m": 1, "s": 2}
            if (order[prev["unit"]] < order[f["unit"]] and re.fullmatch(r"\s*(?:,|and|&)?\s*", gap)):
                prev.update(end=f["end"], lo=prev["lo"] + f["lo"], hi=prev["hi"] + f["hi"],
                            vague=prev["vague"] or f["vague"], raw=text[prev["start"]:f["end"]], unit=f["unit"])
                continue
        merged.append(dict(f))
    return merged


def format_seconds(total: int) -> str:
    total = int(round(total))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hr")
    if m:
        parts.append(f"{m} min")
    if s or not parts:
        parts.append(f"{s} sec")
    return " ".join(parts)


def timer_for(text: str) -> tuple[int, str]:
    durations = find_durations(text)
    if not durations:
        if re.search(r"\bovernight\b", text, re.I):
            return 0, "Overnight - no timer set. Set your own reminder."
        return 0, ""
    best = max(durations, key=lambda d: d["lo"])
    seconds = min(int(best["lo"]), MAX_TIMER_SECONDS)
    notes = []
    if best["vague"]:
        notes.append(f"Recipe says “{best['raw'].strip()}” - timer is an estimate.")
    elif best["hi"] > best["lo"]:
        notes.append(f"Recipe gives {format_seconds(best['lo'])}–{format_seconds(best['hi'])}. "
                     f"Timer uses the shorter time - check, then add time if needed.")
    if re.search(r"\b(?:per|each|on each|on the other)\s+side\b", text, re.I):
        notes.append("Timer covers one side - tap Restart timer for the other side.")
    if len(durations) > 1:
        notes.append("This step mentions more than one time; the longest is used.")
    return seconds, " ".join(notes)


def split_step(text: str) -> list[str]:
    """Split a long step into sub-steps when it holds several separate timed actions."""
    sentences = [s.strip() for s in SPLIT_RE.split(text) if s and s.strip()]
    flags = [bool(find_durations(s)) for s in sentences]
    if sum(flags) < 2:
        return [text]
    chunks, current = [], []
    for sentence, timed in zip(sentences, flags):
        current.append(sentence)
        if timed:
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks[-1] = chunks[-1] + " " + " ".join(current)
    return [_tidy_chunk(c) for c in chunks]


def _tidy_chunk(chunk: str) -> str:
    chunk = chunk.strip().rstrip(",").strip()
    return chunk[:1].upper() + chunk[1:]


def join_wrapped(lines: list[str], strict: bool = False) -> list[str]:
    out: list[str] = []
    for line in lines:
        if out:
            prev = out[-1]
            starts_lower = line[:1].islower()
            unterminated = not TERMINAL_RE.search(prev)
            if (strict and starts_lower and unterminated) or (
                    not strict and unterminated and (starts_lower or line[:1].isdigit() and not NUMBERED_RE.match(line)
                                                     or CONNECTOR_END_RE.search(prev))):
                out[-1] = f"{prev} {line}"
                continue
        out.append(line)
    return out


def _pretty_stem(stem: str) -> str:
    stem = re.sub(r"[_\-]+", " ", stem or "").strip()
    return stem[:1].upper() + stem[1:] if stem else "My recipe"


def _clean_title(hint: str) -> str:
    hint = clean_line(hint)
    hint = hint.split(" | ")[0].strip()
    hint = re.sub(r"\s+(?:recipe)\s*$", "", hint, flags=re.I) if len(hint) > 12 else hint
    return hint[:90]


def analyse(lines, title_hint: str = "", stem: str = "", structured: dict | None = None,
            warnings: list[str] | None = None) -> dict:
    warnings = list(warnings or [])
    if structured:
        return analyse_structured(structured, stem, warnings)

    cleaned = [clean_line(l) for l in lines]
    cleaned = [l for l in cleaned if l and not JUNK_RE.match(l)]
    # lone numbers ("2") are kept only for the numbered-steps pass; elsewhere they are page numbers

    info: dict[str, str] = {}
    entries = []  # (text, kind, section)
    section = None
    for line in cleaned:
        meta = meta_of(line)
        if meta:
            info.setdefault(meta[0], meta[1])
            continue
        if LONE_NUMBER_RE.match(line) and section != "method":
            continue
        kind = heading_kind(line)
        if kind:
            section = kind
            entries.append((line, "head", kind))
        else:
            entries.append((line, "text", section))

    # ---- title
    title = _clean_title(title_hint) if title_hint else ""
    title_index = -1
    if not title:
        for i, (text, kind, sec) in enumerate(entries[:6]):
            if kind != "text" or sec is not None:
                break
            if (3 <= len(text) <= 80 and len(text.split()) <= 12 and not text.endswith(".")
                    and not looks_like_ingredient(text) and not NUMBERED_RE.match(text)
                    and not STEP_WORD_RE.match(text)):
                title, title_index = text, i
                break
    if not title:
        title = _pretty_stem(stem)
    elif title_index < 0:
        for i, (text, kind, sec) in enumerate(entries[:6]):
            if kind == "text" and text.lower() == title.lower():
                title_index = i
                break

    has_method = any(k == "head" and s == "method" for _, k, s in entries)
    has_ing = any(k == "head" and s == "ing" for _, k, s in entries)
    first_method = next((i for i, (_, k, s) in enumerate(entries) if k == "head" and s == "method"), len(entries))

    # ---- ingredients
    if has_ing:
        ing_lines = [t for t, k, s in entries if k == "text" and s == "ing"]
    else:
        ing_lines = [t for i, (t, k, s) in enumerate(entries)
                     if k == "text" and s is None and i != title_index and i < first_method and looks_like_ingredient(t)]
    ingredient_set = set(ing_lines)
    ingredients = join_wrapped(ing_lines, strict=True)[:MAX_INGREDIENTS]

    def in_region(i, text, kind, sec):
        if kind != "text" or i == title_index:
            return False
        if has_method:
            return sec == "method"
        return sec is None and text not in ingredient_set

    # ---- numbered pass
    numbered: list[dict] = []
    current = None
    last_n = 0
    pending_number = None
    for i, (text, kind, sec) in enumerate(entries):
        if not in_region(i, text, kind, sec):
            current, pending_number = None, None
            continue
        n, rest = None, None
        m = STEP_WORD_RE.match(text) or NUMBERED_RE.match(text)
        if m:
            n, rest = int(m.group(1)), m.group(2)
        elif has_method:
            m = BARE_NUMBER_RE.match(text)
            if m and not re.match(rf"^{UNIT_WORDS}\b", m.group(2), re.I):
                n, rest = int(m.group(1)), m.group(2)
            else:
                m = LONE_NUMBER_RE.match(text)
                if m:
                    pending_number = int(m.group(1))
                    continue
        if n is None and pending_number is not None:
            n, rest, pending_number = pending_number, text, None
        if n is not None and (n == last_n + 1 or n == 1):
            current = {"text": rest.strip()}
            numbered.append(current)
            last_n = n
        elif is_subheading(text):
            current = None
        elif current is not None and len(text) > 3 and (has_method or not looks_like_ingredient(text)):
            current["text"] = f"{current['text']} {text}".strip()
    raw_steps = [s["text"] for s in numbered if s["text"]]

    if len(raw_steps) < 2:
        region = []
        for i, (text, kind, sec) in enumerate(entries):
            if in_region(i, text, kind, sec) and not is_subheading(text) and not LONE_NUMBER_RE.match(text):
                region.append(text)
            elif region and region[-1] != "\x00":
                region.append("\x00")  # paragraph break
        paragraphs: list[str] = []
        block: list[str] = []
        for text in region + ["\x00"]:
            if text == "\x00":
                paragraphs.extend(join_wrapped(block))
                block = []
            else:
                block.append(text)
        if has_method:
            raw_steps = paragraphs
        else:
            raw_steps = [p for p in paragraphs if looks_like_instruction(p)]
            if raw_steps:
                warnings.append("No numbered method was found, so the instructions were guessed - "
                                "please check the steps before you start.")

    steps = _build_steps(raw_steps, warnings)
    return {"title": title, "ingredients": ingredients, "info": info, "steps": steps, "warnings": warnings}


def _build_steps(raw_steps: list[str], warnings: list[str]) -> list[dict]:
    steps = []
    for raw in raw_steps:
        raw = re.sub(r"\s+", " ", raw).strip()
        for chunk in split_step(raw):
            seconds, note = timer_for(chunk)
            steps.append({"text": chunk, "seconds": seconds, "note": note})
    if len(steps) > MAX_STEPS:
        warnings.append(f"The recipe had {len(steps)} steps; only the first {MAX_STEPS} were kept.")
        steps = steps[:MAX_STEPS]
    return steps


# ---- schema.org JSON-LD ----------------------------------------------------------------

def _strip_tags(text) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def iso_duration(value) -> str:
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", str(value or "").strip(), re.I)
    if not m or not any(m.groups()):
        return ""
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return format_seconds(d * 86400 + h * 3600 + mi * 60 + s)


def analyse_structured(recipe: dict, stem: str, warnings: list[str]) -> dict:
    raw_steps: list[str] = []

    def collect(node):
        if isinstance(node, str):
            for part in re.split(r"\n+", _strip_tags(node) if "<" in node else node):
                if part.strip():
                    raw_steps.append(clean_line(part))
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, dict):
            if node.get("itemListElement"):
                collect(node["itemListElement"])
            elif node.get("text"):
                collect(_strip_tags(node["text"]))
            elif node.get("name"):
                collect(_strip_tags(node["name"]))

    collect(recipe.get("recipeInstructions"))
    numbered = [re.sub(r"^(?:step\s*)?\d{1,2}[.):]\s+", "", s, flags=re.I) for s in raw_steps]
    ingredients = recipe.get("recipeIngredient") or recipe.get("ingredients") or []
    if isinstance(ingredients, str):
        ingredients = [ingredients]
    info = {}
    yld = recipe.get("recipeYield")
    if isinstance(yld, list):
        yld = yld[0] if yld else ""
    if yld:
        info["serves"] = _strip_tags(yld)
    for key, src in (("prep", "prepTime"), ("cook", "cookTime"), ("total", "totalTime")):
        val = iso_duration(recipe.get(src))
        if val:
            info[key] = val
    name = recipe.get("name")
    title = _clean_title(_strip_tags(name)) if name else _pretty_stem(stem)
    return {"title": title, "ingredients": [_strip_tags(i) for i in ingredients if _strip_tags(i)][:MAX_INGREDIENTS],
            "info": info, "steps": _build_steps(numbered, warnings), "warnings": warnings}


# --------------------------------------------------------------------------------------

def parse_recipe(filename: str, data: bytes) -> dict:
    extracted = extract(filename, data)
    result = analyse(extracted.lines, extracted.title_hint, Path(filename or "").stem,
                     extracted.structured, extracted.warnings)
    result["source"] = extracted.source
    if not result["steps"]:
        raise RecipeError("I couldn't find any method steps in that file. Make sure the recipe has a "
                          "'Method' or 'Instructions' section, or numbered steps.")
    return result
