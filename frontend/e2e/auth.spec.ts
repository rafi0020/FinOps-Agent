import { expect, test } from "@playwright/test";
import { HARBOR, signIn, signInFresh } from "./helpers";

test("a wrong password shows the server's message and does not sign in", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("E-mail").fill("analyst@harbor.demo");
  await page.getByLabel("Password").fill("definitely-wrong-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Incorrect e-mail or password.")).toBeVisible();
  await expect(page).toHaveURL(/\/login\//);
});

test("a signed-out visitor is sent to sign-in", async ({ page }) => {
  await page.goto("/overview/");
  await expect(page).toHaveURL(/\/login\//);
});

for (const [role, hidden, visible] of [
  ["viewer", ["Ask", "Approvals", "Usage", "Administration"], ["Overview", "Investigations", "Alerts", "Data catalogue"]],
  ["analyst", ["Administration"], ["Ask", "Approvals", "Usage"]],
  ["admin", [], ["Ask", "Approvals", "Usage", "Administration"]],
] as const) {
  test(`${role} sees only the sections that role may use`, async ({ page }) => {
    await signIn(page, HARBOR[role]);
    const nav = page.getByRole("navigation", { name: "Main" });
    for (const name of visible) await expect(nav.getByRole("link", { name: new RegExp(`^${name}`) })).toBeVisible(); // a count may follow the label
    for (const name of hidden) await expect(nav.getByRole("link", { name, exact: true })).toHaveCount(0);
    await expect(page.getByText("Revenue", { exact: true }).first()).toBeVisible();
  });
}

test("signing in through the form and signing out ends that session", async ({ page }) => {
  await signInFresh(page, HARBOR.viewer);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login\//);
  await page.goto("/overview/");
  await expect(page).toHaveURL(/\/login\//);
});

test("the page has no horizontal scroll on a phone and the menu opens", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, HARBOR.viewer);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(page.getByRole("link", { name: "Data catalogue" })).toBeVisible();
});
