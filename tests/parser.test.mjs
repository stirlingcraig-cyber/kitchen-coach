// Checks the iPhone/web parser (web/parser.js) gives exactly the same results as the
// Windows/Python parser for every case in tests/fixtures/cases.json.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { analyse, findDurations, formatSeconds, isoDuration } from "../web/parser.js";

const cases = JSON.parse(readFileSync(new URL("./fixtures/cases.json", import.meta.url), "utf8"));

for (const c of cases) {
  test(`parity: ${c.name}`, () => {
    const got = analyse(c.lines, c.title_hint, c.stem, c.structured);
    assert.deepEqual(got, c.expected);
  });
}

test("durations", () => {
  const secs = (t) => findDurations(t).map((d) => d.lo);
  assert.deepEqual(secs("bake for 1 hour 30 minutes"), [5400]);
  assert.deepEqual(secs("stir every 5 minutes"), []);
  assert.deepEqual(secs("about 1½ minutes"), [90]);
  assert.deepEqual(secs("a high heat"), []);
});

test("formatting helpers", () => {
  assert.equal(formatSeconds(5430), "1 hr 30 min 30 sec");
  assert.equal(isoDuration("PT1H15M"), "1 hr 15 min");
});
