"""Build tests/fixtures/cases.json: analysis inputs + the Python parser's expected output.

The JavaScript parser (web/parser.js) is checked against the same file by tests/parser.test.mjs,
so the Windows (Python) and iPhone (JavaScript) builds always read recipes the same way.
Run after changing the analysis rules:  python tests/build_fixtures.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recipe_parser as rp  # noqa: E402

SYNTHETIC = {
    "original_bug_decimal_ingredients": [
        "Beef stew", "1.5 kg beef", "2 onions", "1. Brown the beef for 10 minutes.",
        "2. Add the onions and cook for 5 mins.", "3. Simmer for 2 hours."],
    "unnumbered_method_wrapped": [
        "Tomato Soup", "Ingredients", "1 tbsp oil", "1 onion, chopped", "Method",
        "Fry the onion in the oil over a low heat for", "10 minutes until soft.",
        "Add the tomatoes and simmer for 20 mins.", "Blend until smooth and serve."],
    "no_headings_prose": [
        "Quick Omelette", "3 eggs", "knob of butter",
        "Beat the eggs with a pinch of salt in a jug.",
        "Melt the butter in a frying pan and pour in the eggs, cooking for 2 minutes until just set.",
        "Fold and serve straight away."],
    "step_word_and_lone_numbers": [
        "Bread", "Method", "Step 1", "Mix the flour and yeast.", "2", "Knead for 10 minutes.",
        "3", "Prove for 1 hour until doubled.", "Notes", "Keeps for 2 days."],
    "durations_mix": [
        "Durations", "Method", "1. Roast for half an hour.", "2. Braise for an hour.",
        "3. Slow cook for 1½ hours.", "4. Rest for 1 1/2 hours.", "5. Bake for 2 hrs 15 mins.",
        "6. Steam for 1h30.", "7. Blitz for 45 secs.", "8. Marinate overnight.",
        "9. Simmer for 20 minutes, stirring every 5 minutes.", "10. Cook for several minutes.",
        "11. Leave for twenty minutes.", "12. Fry for 3-4 minutes on each side."],
    "multi_timer_split": [
        "Curry", "Method",
        "1. Heat the oil. Fry the onions for 8 minutes until golden. Add the spices and cook for 1 minute. "
        "Stir in the tomatoes and simmer for 15 minutes. Season to taste.",
        "2. Boil the rice for 10 minutes, then steam for 5 minutes."],
    "meta_and_subheadings": [
        "Lasagne", "Serves: 6", "Prep time: 30 mins", "Cook time: 1 hr", "Ingredients", "For the sauce:",
        "500 g mince", "Method", "For the sauce", "1) Brown the mince for 10 minutes.",
        "2) Add the passata and simmer for 30 minutes.", "To serve", "3) Bake for 40 minutes until bubbling."],
}


def main():
    cases = []
    for name, lines in SYNTHETIC.items():
        cases.append({"name": name, "lines": lines, "title_hint": "", "stem": name, "structured": None})
    for f in sorted((ROOT / "tests" / "samples").iterdir()):
        ex = rp.extract(f.name, f.read_bytes())
        if ex.source == "pdf":
            continue  # PDF line breaks differ between pypdf and pdf.js; covered by the browser test
        cases.append({"name": f.name, "lines": ex.lines, "title_hint": ex.title_hint, "stem": f.stem,
                      "structured": ex.structured})
    for c in cases:
        c["expected"] = rp.analyse(c["lines"], c["title_hint"], c["stem"], c["structured"])
    out = ROOT / "tests" / "fixtures" / "cases.json"
    out.write_text(json.dumps(cases, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {out}")


if __name__ == "__main__":
    main()
