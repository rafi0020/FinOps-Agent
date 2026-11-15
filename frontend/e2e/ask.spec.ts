import { expect, test } from "@playwright/test";
import { ask, csrfHeaders, HARBOR, signIn } from "./helpers";

test("an analyst asks a question, watches the trail, and opens the evidence behind the report", async ({ page }) => {
  await signIn(page, HARBOR.analyst);
  await ask(page, "Show gross margin by region for the latest two quarters");

  const trail = page.getByRole("list", { name: "What the agent did" });
  await expect(trail.getByText("analyst@harbor.demo asked")).toBeVisible();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({ timeout: 30_000 });
  for (const step of ["Ran a query", "Calculated", "Recorded a finding", "Wrote the report"]) await expect(trail.getByText(step, { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Answer" })).toBeVisible();
  await expect(page.getByText("every figure traced")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();

  // Open the stored query result from the evidence table.
  await page.getByRole("table").last().getByRole("button").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("SQL that ran")).toBeVisible();
  await expect(drawer.getByText("FROM order_lines", { exact: false })).toBeVisible();
  await expect(drawer.getByRole("columnheader", { name: "region" })).toBeVisible();
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toHaveCount(0);
});

test("a finished run can be saved, found and re-opened from Investigations", async ({ page }) => {
  await signIn(page, HARBOR.analyst);
  await ask(page, "Margin by region, for saving");
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({ timeout: 30_000 });
  const title = `Margin check ${Date.now()}`;
  await page.getByLabel("Investigation title").fill(title);
  await page.getByRole("button", { name: "Save investigation" }).click();
  await expect(page.getByText("Saved to Investigations.")).toBeVisible();

  await page.goto("/investigations/");
  await page.getByLabel("Search").fill(title);
  await page.getByRole("link", { name: "Margin by region, for saving" }).click();
  await expect(page.getByRole("heading", { name: "Answer" })).toBeVisible();
});

test("reloading in the middle of a run keeps the trail", async ({ page }) => {
  await signIn(page, HARBOR.analyst);
  await ask(page, "Margin by region, reload test");
  await page.reload();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("list", { name: "What the agent did" }).getByText("Wrote the report")).toBeVisible();
});

test("a viewer cannot reach the Ask form but can read a saved result", async ({ page }) => {
  await signIn(page, HARBOR.viewer);
  const refused = await page.request.post("/api/runs", { data: { question: "anything at all" }, headers: await csrfHeaders(page) });
  expect(refused.status()).toBe(403);
  await page.goto("/investigations/");
  await expect(page.getByRole("heading", { name: "Investigations" })).toBeVisible();
});
