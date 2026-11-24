// What to record for the FinOps Agent demo. Run with the stack up and a model connected (see README, "Adding an AI model").
const PASSWORDS = { admin: "Admin#Demo2026", analyst: "Analyst#Demo2026", viewer: "Viewer#Demo2026" };
const email = (role) => `${role}@northwind.demo`;

async function ask(page, h, question, until = "Completed") {
  await page.goto("/ask/");
  await h.settle(400);
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask the agent" }).click();
  await page.waitForURL(/run=/);
  await page.getByText(until, { exact: true }).first().waitFor({ timeout: 240_000 });
  await h.settle(1500);
}

/** Open every handle in the Evidence table so each figure's drawer is recorded. */
async function openAllEvidence(page, h) {
  const buttons = page.getByRole("table").last().getByRole("button");
  const n = await buttons.count();
  for (let i = 0; i < n; i++) {
    await buttons.nth(i).click();
    const opened = await page.getByRole("dialog").getByText("SQL that ran").waitFor({ timeout: 8000 }).then(() => true, () => false);
    await h.settle(600);
    if (opened) await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    else await page.keyboard.press("Escape");
  }
}

export default {
  project: "finops-agent",
  baseUrl: process.env.DEMO_BASE_URL ?? "http://localhost:3100",
  loginPath: "/login/",
  loginApi: "/api/auth/login",
  logoutApi: "/api/auth/logout",
  crawlStart: "/overview/",
  crawlMax: 25,
  crawlSkip: /\/ask\/\?run=/,
  sequence: [/^\/api\/runs\/[^/]+$/],
  users: [
    { email: email("analyst"), password: PASSWORDS.analyst, label: "Analyst" },
    { email: email("admin"), password: PASSWORDS.admin, label: "Administrator" },
    { email: email("viewer"), password: PASSWORDS.viewer, label: "Viewer" },
  ],
  journeys: {
    [email("analyst")]: async (page, h) => {
      await ask(page, h, "Why did gross margin fall in the West region in Q3 2026?");
      // Open the evidence behind a figure, then save the answer as an investigation.
      await openAllEvidence(page, h);
      await page.getByLabel("Investigation title").fill("West gross margin, Q3 2026");
      await page.getByRole("button", { name: "Save investigation" }).click();
      await page.getByText("Saved to Investigations.").waitFor();
      await h.settle(800);
      await ask(page, h, "Show gross margin by region for the latest two quarters");
      await openAllEvidence(page, h);
      await ask(page, h, "Show me Harbor Trade's revenue.");
      await ask(page, h, "Alert me if West gross margin drops below 25% in a quarter.", "Waiting for approval");
    },
  },
  after: {
    [email("admin")]: async (page, h) => {
      await page.goto("/approvals/");
      await h.settle(800);
      const card = page.getByRole("article").filter({ hasText: "West gross margin" }).first();
      await h.mute(async () => {
        await card.getByRole("button", { name: "Approve" }).click();
        await page.getByText("Approved. The agent will carry it out.").waitFor({ timeout: 30_000 });
        await h.settle(4000);
      });
      await page.goto("/alerts/");
      await h.settle(1000);
      await page.getByRole("button", { name: "Check rules now" }).click().catch(() => {});
      await h.settle(2500);
    },
  },
};
