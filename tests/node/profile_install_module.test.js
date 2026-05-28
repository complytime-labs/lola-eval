import { describe, it, expect } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyProfile } from "../../src/lola_eval/_data/providers/lib/profile_setup.js";

function makeModule(root, name, skill) {
  const moduleDir = join(root, name);
  mkdirSync(join(moduleDir, "skills", skill), { recursive: true });
  writeFileSync(join(moduleDir, "skills", skill, "SKILL.md"), `# ${skill}`);
  return moduleDir;
}

describe("applyProfile install_modules", () => {
  it("scaffolds every module in the list into the workdir project config", () => {
    const root = mkdtempSync(join(tmpdir(), "instmods-"));
    const modA = makeModule(root, "mod-a", "greet");
    const modB = makeModule(root, "mod-b", "salute");
    const workdir = join(root, "wd");
    mkdirSync(workdir, { recursive: true });

    applyProfile(
      workdir,
      "claude-code",
      { profile_setup_json: JSON.stringify({ install_modules: [modA, modB] }) },
      root,
    );

    expect(existsSync(join(workdir, ".claude", "skills", "greet", "SKILL.md"))).toBe(true);
    expect(existsSync(join(workdir, ".claude", "skills", "salute", "SKILL.md"))).toBe(true);
  });

  it("resolves module paths relative to profilesDir", () => {
    const root = mkdtempSync(join(tmpdir(), "instmods-rel-"));
    makeModule(root, "rel-mod", "greet");
    const workdir = join(root, "wd");
    mkdirSync(workdir, { recursive: true });

    applyProfile(
      workdir,
      "claude-code",
      { profile_setup_json: JSON.stringify({ install_modules: ["rel-mod"] }) },
      root,
    );

    expect(existsSync(join(workdir, ".claude", "skills", "greet", "SKILL.md"))).toBe(true);
  });
});
