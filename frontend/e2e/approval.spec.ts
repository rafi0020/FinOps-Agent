import { expect, test } from "@playwright/test";
import { ask, csrfHeaders, HARBOR, signIn } from "./helpers";

test("an analyst's alert proposal waits for an administrator, who approves it, and the rule appears", async ({ browser }) => {
  const analyst = await (await browser.newContext()).newPage();
  await signIn(analyst, HARBOR.analyst);
  const runId = await ask(analyst, "Alert me if gross margin falls below 50% in a quarter");
  await expect(analyst.getByText("Waiting for approval", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(analyst.getByText("Nothing has been changed.", { exact: false })).toBeVisible();

  // The analyst cannot approve their own request.
  const approvals = await (await analyst.request.get("/api/approvals")).json();
  const mine = approvals.approvals.find((a: { run_id: string }) => a.run_id === runId);
  const selfApprove = await analyst.request.post(`/api/approvals/${mine.id}/decide`, { data: { decision: "approved" }, headers: await csrfHeaders(analyst) });
  expect(selfApprove.status()).toBe(403);

  const admin = await (await browser.newContext()).newPage();
  await signIn(admin, HARBOR.admin);
  await admin.goto("/approvals/");
  const card = admin.getByRole("article").filter({ hasText: "Alert me if gross margin falls below 50%" }).first();
  await expect(card.getByText("analyst@harbor.demo")).toBeVisible();
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(admin.getByText("Approved. The agent will carry it out.")).toBeVisible();

  await expect(analyst.getByText("Completed", { exact: true })).toBeVisible({ timeout: 30_000 });
  await admin.goto("/alerts/");
  await expect(admin.getByText("Gross margin below 50.0%, per quarter").first()).toBeVisible();
  await admin.getByRole("button", { name: "Check rules now" }).click();
  await expect(admin.getByText(/2026-Q3/).first()).toBeVisible();
});

test("a rejected proposal creates no rule and the agent reports it", async ({ browser }) => {
  const analyst = await (await browser.newContext()).newPage();
  await signIn(analyst, HARBOR.analyst);
  await ask(analyst, "Alert me about margin, to be rejected");
  await expect(analyst.getByText("Waiting for approval", { exact: true })).toBeVisible({ timeout: 30_000 });

  const admin = await (await browser.newContext()).newPage();
  await signIn(admin, HARBOR.admin);
  await admin.goto("/approvals/");
  const card = admin.getByRole("article").filter({ hasText: "to be rejected" }).first();
  await card.getByLabel("Reason").fill("Not needed");
  await card.getByRole("button", { name: "Reject" }).click();

  await expect(analyst.getByText("Completed", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(analyst.getByText("An administrator rejected this action: Not needed")).toBeVisible();
});
