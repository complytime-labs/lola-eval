import { describe, it, expect } from "vitest";
import request from "supertest";
import { app } from "../src/server.js";

describe("server", () => {
  it("returns hello world on /", async () => {
    const res = await request(app).get("/");
    expect(res.status).toBe(200);
    expect(res.body.hello).toBe("world");
  });
});
