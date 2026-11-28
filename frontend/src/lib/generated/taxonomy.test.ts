import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// @ts-expect-error: a plain ES module script without types.
import { OUT_FILE, render } from "../../../scripts/gen-taxonomy.mjs";
import { canonicalSkill, suggestSkills } from "../skills";
import { COUNTRY_CODES, INDUSTRIES, SKILLS } from "./taxonomy";

describe("taxonomy generated from the backend data", () => {
  it("is up to date (run `npm run gen:taxonomy` if this fails)", () => {
    const committed = readFileSync(OUT_FILE as string, "utf8").replace(/\r\n/g, "\n");
    expect(committed).toBe((render as () => string)());
  });

  it("parses every skills.yaml entry (none skipped by the line parser)", () => {
    const yaml = readFileSync(resolve(__dirname, "../../../../backend/app/ingest/data/skills.yaml"), "utf8");
    // Every indented "Name: ..." line under a category is an entry.
    const entries = yaml.split(/\r?\n/).filter((line) => /^ {2}\S.*:/.test(line));
    expect(SKILLS).toHaveLength(entries.length);
  });

  it("has the skills, industries and countries the API compares against", () => {
    expect(SKILLS).toContain("PostgreSQL");
    expect(SKILLS).toContain("C++");
    expect(INDUSTRIES).toContain("fintech");
    expect(COUNTRY_CODES).toContain("IN");
    expect(COUNTRY_CODES).toContain("NO");
  });
});

describe("skills are normalised the way the backend does", () => {
  it.each([
    ["postgres", "PostgreSQL"],
    ["  Apache   Airflow ", "Airflow"],
    ["golang", "Go"],
    ["k8s", "Kubernetes"],
    ["PYTHON", "Python"],
    ["Our  in-house  tool", "Our in-house tool"],
  ])("%s -> %s", (typed, stored) => {
    expect(canonicalSkill(typed)).toBe(stored);
  });

  it("suggests taxonomy names, best match first, without ones already chosen", () => {
    expect(suggestSkills("post", [])[0]).toBe("PostgreSQL");
    expect(suggestSkills("post", ["PostgreSQL"])).not.toContain("PostgreSQL");
    expect(suggestSkills("", [])).toEqual([]);
  });
});
