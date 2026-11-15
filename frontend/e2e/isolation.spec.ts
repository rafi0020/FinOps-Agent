import { expect, test } from "@playwright/test";
import { ask, csrfHeaders, HARBOR, NORTHWIND_ANALYST, signIn } from "./helpers";

test("a run cannot be opened from another organisation, by URL or by API", async ({ browser }) => {
  const harbor = await (await browser.newContext()).newPage();
  await signIn(harbor, HARBOR.analyst);
  const runId = await ask(harbor, "Margin by region, private to Harbor");
  await expect(harbor.getByText("Completed", { exact: true })).toBeVisible({ timeout: 30_000 });

  const northwind = await (await browser.newContext()).newPage();
  await signIn(northwind, NORTHWIND_ANALYST);
  await northwind.goto(`/ask/?run=${runId}`);
  await expect(northwind.getByText("Run not found.")).toBeVisible();
  for (const path of [`/api/runs/${runId}`, `/api/runs/${runId}/events`, `/api/runs/${runId}/evidence/ev_00000000`]) {
    expect((await northwind.request.get(path)).status()).toBe(404);
  }
  const listed = await (await northwind.request.get("/api/runs?limit=100")).json();
  expect(listed.runs.map((r: { id: string }) => r.id)).not.toContain(runId);
});

test("each organisation sees its own figures on the overview", async ({ browser }) => {
  const read = async (account: readonly [string, string]) => {
    const page = await (await browser.newContext()).newPage();
    await signIn(page, account);
    return (await (await page.request.get("/api/overview?period=2025")).json()).kpis.revenue.value as number;
  };
  const [harbor, northwind] = [await read(HARBOR.viewer), await read(NORTHWIND_ANALYST)];
  expect(harbor).toBeGreaterThan(0);
  expect(northwind).toBeGreaterThan(0);
  expect(harbor).not.toBe(northwind);
});

test("oversized and empty questions are refused before anything runs", async ({ page }) => {
  await signIn(page, HARBOR.analyst);
  const headers = await csrfHeaders(page);
  for (const question of ["", "  ", "x".repeat(2001), "x".repeat(20000)]) {
    expect((await page.request.post("/api/runs", { data: { question }, headers })).status()).toBe(422);
  }
  expect((await page.request.post("/api/runs", { data: { question: "no csrf header" } })).status()).toBe(403);
});
