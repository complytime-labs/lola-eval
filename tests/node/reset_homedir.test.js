import { test, expect } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, chmodSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { installPack, reset } from "../../src/lola_eval/_data/providers/lib/reset.js";

test("installPack passes HOME, LOLA_MODULE_SOURCE, LOLA_INSTALL_SCOPE to the script", async () => {
  const dir = mkdtempSync(join(tmpdir(), "rh-"));
  const script = join(dir, "stub.sh");
  const out = join(dir, "env.txt");
  writeFileSync(
    script,
    `#!/usr/bin/env bash\n{ echo "HOME=$HOME"; echo "SRC=$LOLA_MODULE_SOURCE"; echo "SCOPE=$LOLA_INSTALL_SCOPE"; } > "${out}"\n`,
  );
  chmodSync(script, 0o755);
  const homedir = join(dir, "home");
  mkdirSync(homedir);
  await installPack({
    packId: "project-user",
    targetCli: "claude-code",
    workdir: join(dir, "wd"),
    scriptPath: script,
    moduleSource: "/abs/mod",
    installScope: "user",
    homedir,
  });
  const env = readFileSync(out, "utf8");
  expect(env).toContain(`HOME=${homedir}`);
  expect(env).toContain("SRC=/abs/mod");
  expect(env).toContain("SCOPE=user");
});

test("installPack still short-circuits packId=none", async () => {
  const dir = mkdtempSync(join(tmpdir(), "rh-"));
  await installPack({ packId: "none", targetCli: "claude-code", workdir: dir });
  expect(true).toBe(true); // no throw, no spawn
});

test("reset passes HOME (homedir) to the script", async () => {
  const dir = mkdtempSync(join(tmpdir(), "rh-"));
  const script = join(dir, "reset-stub.sh");
  const out = join(dir, "reset-env.txt");
  writeFileSync(script, `#!/usr/bin/env bash\necho "HOME=$HOME" > "${out}"\nexit 0\n`);
  chmodSync(script, 0o755);
  const homedir = join(dir, "home");
  mkdirSync(homedir);
  await reset({
    taskId: "t",
    targetCli: "claude-code",
    workdir: join(dir, "wd"),
    scriptPath: script,
    homedir,
  });
  expect(readFileSync(out, "utf8")).toContain(`HOME=${homedir}`);
});

test("reset passes cacheHome as XDG_CACHE_HOME so the script does not re-derive it from the overridden HOME", async () => {
  // Regression: the provider computes workdir under the real host cache,
  // but reset() overrides HOME to the per-cell sandbox home. reset.sh
  // re-derived xdg_cache from ${XDG_CACHE_HOME:-$HOME/.cache} — using the
  // sandbox HOME — and rejected the legitimate workdir (exit 2). Passing
  // cacheHome pins XDG_CACHE_HOME to the same root the provider used.
  const dir = mkdtempSync(join(tmpdir(), "rh-"));
  const script = join(dir, "reset-stub.sh");
  const out = join(dir, "reset-env.txt");
  writeFileSync(
    script,
    `#!/usr/bin/env bash\necho "XDG_CACHE_HOME=$XDG_CACHE_HOME" > "${out}"\nexit 0\n`,
  );
  chmodSync(script, 0o755);
  const homedir = join(dir, "home");
  mkdirSync(homedir);
  const cacheHome = join(dir, "real-cache");
  await reset({
    taskId: "t",
    targetCli: "claude-code",
    workdir: join(dir, "wd"),
    scriptPath: script,
    homedir,
    cacheHome,
  });
  expect(readFileSync(out, "utf8")).toContain(`XDG_CACHE_HOME=${cacheHome}`);
});
