import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// Harbor Trade uses the server's default model. With LLM_PROVIDER=stub that is the built-in script, so these
// journeys exercise the whole stack (API, worker, database, live events, UI) without calling a model.
export const HARBOR = {
  admin: ["admin@harbor.demo", "Admin#Demo2026"],
  analyst: ["analyst@harbor.demo", "Analyst#Demo2026"],
  viewer: ["viewer@harbor.demo", "Viewer#Demo2026"],
} as const;
export const NORTHWIND_ANALYST = ["analyst@northwind.demo", "Analyst#Demo2026"] as const;
export const ACCOUNTS = [HARBOR.admin, HARBOR.analyst, HARBOR.viewer, NORTHWIND_ANALYST];
export const AUTH_DIR = "e2e/.auth";

/** Open the app as this account, using the session created once in global setup. */
export async function signIn(page: Page, [email]: readonly [string, string]) {
  const state = JSON.parse(readFileSync(`${AUTH_DIR}/${email}.json`, "utf8"));
  await page.context().addCookies(state.cookies);
  await page.goto("/overview/");
  await expect(page).toHaveURL(/\/overview\//);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

/** Sign in through the form, creating a new session (for tests that end the session). */
export async function signInFresh(page: Page, [email, password]: readonly [string, string]) {
  await page.goto("/login/");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/overview\//);
}

export async function csrfHeaders(page: Page) {
  const me = await (await page.request.get("/api/auth/me")).json();
  return { "X-CSRF-Token": me.csrf_token as string };
}

export async function ask(page: Page, question: string): Promise<string> {
  await page.goto("/ask/");
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask the agent" }).click();
  await expect(page).toHaveURL(/run=/);
  return new URL(page.url()).searchParams.get("run")!;
}
