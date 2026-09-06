import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { releases } from "./data";
import { draft } from "./draft";
import { strings, type Locale } from "./strings";

const locales = Object.keys(strings) as Locale[];

describe("changelog verify gate", () => {
  it("every label + entry key resolves in every locale", () => {
    const missing: string[] = [];
    for (const locale of locales) {
      for (const r of releases) {
        if (strings[locale][r.labelKey] === undefined) {
          missing.push(`MISSING ${r.labelKey} in ${locale}`);
        }
        for (const k of r.entryKeys) {
          if (strings[locale][k] === undefined) {
            missing.push(`MISSING ${k} in ${locale}`);
          }
        }
      }
    }
    expect(missing, missing.join("\n")).toEqual([]);
  });

  it("every draft entry key resolves in every locale", () => {
    // The gate only validated released entries, so a branch could add a draft
    // key with no string (or ship a flagship feature with no draft entry at
    // all) and cut-release would only discover it after moving the keys into
    // data.ts.
    const missing: string[] = [];
    for (const locale of locales) {
      for (const k of draft.entryKeys) {
        if (strings[locale][k] === undefined) {
          missing.push(`MISSING ${k} in ${locale}`);
        }
      }
    }
    expect(missing, missing.join("\n")).toEqual([]);
  });

  it("data[0].version equals the VERSION file", () => {
    // npm scripts run with cwd = solution/web; VERSION is one level up.
    const versionFile = readFileSync(resolve(process.cwd(), "..", "VERSION"), "utf-8").trim();
    expect(releases[0].version).toBe(versionFile);
  });
});
