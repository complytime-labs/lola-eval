import { describe, it, expect } from "vitest";
import { mkdtempSync, readFileSync, unlinkSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import OpencodeProvider from "../../src/lola_eval/_data/providers/opencode_provider.js";

const REPO = resolve(import.meta.dirname, "../..");

function setupEnv(mode) {
  const xdgState = mkdtempSync(join(tmpdir(), "state-"));
  const xdgCache = mkdtempSync(join(tmpdir(), "cache-"));
  return {
    XDG_STATE_HOME: xdgState,
    XDG_CACHE_HOME: xdgCache,
    LOLA_TEST_SETS_DIR: `${REPO}/examples/default/.lola-eval/test_sets`,
    PATH: `${REPO}/tests/fixtures/fake-opencode:${process.env.PATH}`,
    HOME: process.env.HOME,
    FAKE_MODE: mode,
  };
}

describe("OpencodeProvider", () => {
  it("success path returns envelope", async () => {
    const env = setupEnv("success");
    Object.assign(process.env, env);
    const p = new OpencodeProvider({});
    const r = await p.callApi("fix the bug", {
      vars: {
        target_cli: "opencode",
        target_model: "google/gemini-2.5-pro",
        pack_id: "none",
        task_id: "case-001-fix-bug",
        task_version: "1",
        rubric_version: "1",
        exec_mode: "autonomous",
        invocation: "passive",
        judge_cli: "opencode",
        judge_model: "claude-sonnet-4-6",
        timeout_seconds: 30,
      },
    });
    const env2 = JSON.parse(r.output);
    expect(env2.exit_status).toBe("success");
  });

  it("crash path returns envelope with exit_status=target_error", async () => {
    const env = setupEnv("crash");
    Object.assign(process.env, env);
    const p = new OpencodeProvider({});
    const r = await p.callApi("fix the bug", {
      vars: {
        target_cli: "opencode",
        target_model: "google/gemini-2.5-pro",
        pack_id: "none",
        task_id: "case-001-fix-bug",
        task_version: "1",
        rubric_version: "1",
        exec_mode: "autonomous",
        invocation: "passive",
        judge_cli: "opencode",
        judge_model: "claude-sonnet-4-6",
        timeout_seconds: 30,
      },
    });
    const env2 = JSON.parse(r.output);
    expect(env2.exit_status).toBe("target_error");
    // The CLI's stderr is the usual diagnosis (bad model id, rejected
    // flag, …); it must travel in the envelope, not just the console.
    expect(env2.error_message).toMatch(/crashed/);
  });

  it("user-scope branch sets HOME and OPENCODE_CONFIG_DIR to per-cell homedir", async () => {
    const env = setupEnv("success");
    const dumpPath = join(tmpdir(), `fake-env-dump-${Date.now()}.txt`);
    env.FAKE_ENV_DUMP = dumpPath;
    Object.assign(process.env, env);
    try {
      const p = new OpencodeProvider({});
      const r = await p.callApi("fix the bug", {
        vars: {
          target_cli: "opencode",
          target_model: "google/gemini-2.5-pro",
          pack_id: "none",
          task_id: "case-001-fix-bug",
          task_version: "1",
          rubric_version: "1",
          exec_mode: "autonomous",
          invocation: "passive",
          judge_cli: "opencode",
          judge_model: "claude-sonnet-4-6",
          timeout_seconds: 30,
          install_scope: "user",
        },
      });
      const envelope = JSON.parse(r.output);
      expect(envelope.exit_status).toBe("success");

      expect(existsSync(dumpPath)).toBe(true);
      const dump = readFileSync(dumpPath, "utf8").trim();

      const homeMatch = dump.match(/HOME=(\S+)/);
      const configDirMatch = dump.match(/OPENCODE_CONFIG_DIR=(\S+)/);
      expect(homeMatch).not.toBeNull();
      expect(configDirMatch).not.toBeNull();

      const agentHome = homeMatch[1];
      const agentConfigDir = configDirMatch[1];

      // OPENCODE_CONFIG_DIR must equal <HOME>/.opencode
      expect(agentConfigDir).toBe(agentHome + "/.opencode");

      // HOME must be under the per-cell home root inside XDG_CACHE_HOME
      const cacheHome = env.XDG_CACHE_HOME;
      expect(agentHome.startsWith(cacheHome + "/lola-eval/home/")).toBe(true);
    } finally {
      delete process.env.FAKE_ENV_DUMP;
      if (existsSync(dumpPath)) unlinkSync(dumpPath);
    }
  });

  it("pre_run failure yields setup_error", async () => {
    const env = setupEnv("success");
    Object.assign(process.env, env);
    const p = new OpencodeProvider({});
    const r = await p.callApi("fix the bug", {
      vars: {
        target_cli: "opencode",
        target_model: "google/gemini-2.5-pro",
        pack_id: "none",
        task_id: "case-001-fix-bug",
        task_version: "1",
        rubric_version: "1",
        exec_mode: "autonomous",
        invocation: "passive",
        judge_cli: "opencode",
        judge_model: "claude-sonnet-4-6",
        timeout_seconds: 30,
        pre_run: "exit 7",
      },
    });
    const env2 = JSON.parse(r.output);
    expect(env2.exit_status).toBe("setup_error");
    expect(env2.error_message).toMatch(/pre_run/);
  });

  it("logs the full opencode command on failure", async () => {
    const env = setupEnv("crash");
    Object.assign(process.env, env);
    const writes = [];
    const orig = process.stderr.write.bind(process.stderr);
    process.stderr.write = (chunk, ...rest) => {
      writes.push(String(chunk));
      return orig(chunk, ...rest);
    };
    try {
      const p = new OpencodeProvider({});
      await p.callApi("fix the bug", {
        vars: {
          target_cli: "opencode",
          target_model: "google/gemini-2.5-pro",
          pack_id: "none",
          task_id: "case-001-fix-bug",
          task_version: "1",
          rubric_version: "1",
          exec_mode: "autonomous",
          invocation: "passive",
          judge_cli: "opencode",
          judge_model: "claude-sonnet-4-6",
          timeout_seconds: 30,
        },
      });
    } finally {
      process.stderr.write = orig;
    }
    const logged = writes.join("");
    expect(logged).toMatch(/command:.*opencode run/); // full argv logged
    expect(logged).toMatch(/OPENCODE_CONFIG_DIR/); // clean-room env logged
  });

  it("does not set XDG_CONFIG_HOME (redirect retired; bwrap isolates instead)", async () => {
    const env = setupEnv("success");
    // Ensure no ambient XDG_CONFIG_HOME leaks into the child so the dump
    // reflects only what the provider sets (nothing).
    delete process.env.XDG_CONFIG_HOME;
    const dumpPath = join(tmpdir(), `fake-env-dump-xdg-${Date.now()}.txt`);
    env.FAKE_ENV_DUMP = dumpPath;
    Object.assign(process.env, env);
    try {
      const p = new OpencodeProvider({});
      const r = await p.callApi("fix the bug", {
        vars: {
          target_cli: "opencode",
          target_model: "google/gemini-2.5-pro",
          pack_id: "none",
          task_id: "case-001-fix-bug",
          task_version: "1",
          rubric_version: "1",
          exec_mode: "autonomous",
          invocation: "passive",
          judge_cli: "opencode",
          judge_model: "claude-sonnet-4-6",
          timeout_seconds: 30,
        },
      });
      expect(JSON.parse(r.output).exit_status).toBe("success");

      const dump = readFileSync(dumpPath, "utf8").trim();
      // The redirect is gone: the child sees no XDG_CONFIG_HOME value.
      const xdgMatch = dump.match(/XDG_CONFIG_HOME=(\S+)/);
      expect(xdgMatch).toBeNull();
    } finally {
      delete process.env.FAKE_ENV_DUMP;
      if (existsSync(dumpPath)) unlinkSync(dumpPath);
    }
  });

  it("wraps the opencode spawn in bubblewrap and passes --pure (when supported)", async () => {
    const { detectBwrapSupport } = await import(
      "../../src/lola_eval/_data/providers/lib/sandbox.js"
    );
    // crash mode makes the provider log the full spawned argv + sandbox status.
    const env = setupEnv("crash");
    Object.assign(process.env, env);
    const writes = [];
    const orig = process.stderr.write.bind(process.stderr);
    process.stderr.write = (chunk, ...rest) => {
      writes.push(String(chunk));
      return orig(chunk, ...rest);
    };
    let r;
    try {
      const p = new OpencodeProvider({});
      r = await p.callApi("fix the bug", {
        vars: {
          target_cli: "opencode",
          target_model: "google/gemini-2.5-pro",
          pack_id: "none",
          task_id: "case-001-fix-bug",
          task_version: "1",
          rubric_version: "1",
          exec_mode: "autonomous",
          invocation: "passive",
          judge_cli: "opencode",
          judge_model: "claude-sonnet-4-6",
          timeout_seconds: 30,
        },
      });
    } finally {
      process.stderr.write = orig;
    }
    // Envelope stays valid regardless of sandbox availability.
    expect(JSON.parse(r.output).exit_status).toBe("target_error");
    const logged = writes.join("");
    const commandLine = logged
      .split("\n")
      .find((l) => /command:\s*opencode run/.test(l));
    expect(commandLine).toBeDefined();
    // --pure is always added (drops external plugins even on the fallback path).
    expect(commandLine).toContain("--pure");
    // The bwrap wrap only when bubblewrap is usable on this host; the
    // `spawned:` echo shows the real engine (bwrap, behind setpriv if present).
    if (detectBwrapSupport()) {
      expect(logged).toMatch(/sandbox:.*bubblewrap/);
      expect(logged).toMatch(/spawned:.*bwrap/);
    } else {
      expect(logged).toMatch(/sandbox:.*disabled/);
      expect(logged).toMatch(/spawned:\s*opencode run/);
    }
  });

  it("logs the sandbox status on the success path, not only on failure", async () => {
    // A fully-unsandboxed suite must be visible per-cell — not hidden behind a
    // single one-time warning that only the first cell emits.
    const env = setupEnv("success");
    Object.assign(process.env, env);
    const writes = [];
    const orig = process.stderr.write.bind(process.stderr);
    process.stderr.write = (chunk, ...rest) => {
      writes.push(String(chunk));
      return orig(chunk, ...rest);
    };
    let r;
    try {
      const p = new OpencodeProvider({});
      r = await p.callApi("fix the bug", {
        vars: {
          target_cli: "opencode",
          target_model: "google/gemini-2.5-pro",
          pack_id: "none",
          task_id: "case-001-fix-bug",
          task_version: "1",
          rubric_version: "1",
          exec_mode: "autonomous",
          invocation: "passive",
          judge_cli: "opencode",
          judge_model: "claude-sonnet-4-6",
          timeout_seconds: 30,
        },
      });
    } finally {
      process.stderr.write = orig;
    }
    expect(JSON.parse(r.output).exit_status).toBe("success");
    expect(writes.join("")).toMatch(/sandbox:\s*(bubblewrap|disabled)/);
  });

  it("passes --auto and not --dangerously-skip-permissions to opencode", async () => {
    // crash mode makes the provider log the full spawned argv
    // ("command: opencode <args>"), the real seam for asserting the flag.
    const env = setupEnv("crash");
    Object.assign(process.env, env);
    const writes = [];
    const orig = process.stderr.write.bind(process.stderr);
    process.stderr.write = (chunk, ...rest) => {
      writes.push(String(chunk));
      return orig(chunk, ...rest);
    };
    try {
      const p = new OpencodeProvider({});
      await p.callApi("fix the bug", {
        vars: {
          target_cli: "opencode",
          target_model: "google/gemini-2.5-pro",
          pack_id: "none",
          task_id: "case-001-fix-bug",
          task_version: "1",
          rubric_version: "1",
          exec_mode: "autonomous",
          invocation: "passive",
          judge_cli: "opencode",
          judge_model: "claude-sonnet-4-6",
          timeout_seconds: 30,
        },
      });
    } finally {
      process.stderr.write = orig;
    }
    const commandLine = writes
      .join("")
      .split("\n")
      .find((l) => /command:\s*opencode run/.test(l));
    expect(commandLine).toBeDefined();
    expect(commandLine).toContain("--auto");
    expect(commandLine).not.toContain("--dangerously-skip-permissions");
  });
});
