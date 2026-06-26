import { describe, it, expect } from "vitest";
import { mkdtempSync } from "node:fs";
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
});
