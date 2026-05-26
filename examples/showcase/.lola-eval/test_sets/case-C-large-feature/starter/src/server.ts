import express from "express";

export const app = express();

app.get("/", (_req, res) => {
  res.json({ hello: "world" });
});

// TODO: model adds GET /status here

if (process.env.NODE_ENV !== "test") {
  app.listen(3000);
}
