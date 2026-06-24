import { describe, it, expect } from "vitest";
import { compareVersions } from "./semver";

describe("compareVersions", () => {
  it("orders by major, minor, patch", () => {
    expect(compareVersions("1.0.0", "1.0.1")).toBe(-1);
    expect(compareVersions("1.2.0", "1.1.9")).toBe(1);
    expect(compareVersions("2.0.0", "1.9.9")).toBe(1);
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
  });

  it("ignores suffixes and treats non-numeric as 0", () => {
    expect(compareVersions("1.0.0-rc1", "1.0.0")).toBe(0);
    expect(compareVersions("1.0", "1.0.0")).toBe(0);
    expect(compareVersions("x.y.z", "0.0.0")).toBe(0);
  });
});
