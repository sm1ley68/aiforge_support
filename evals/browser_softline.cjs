const assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const base = process.env.SOFTLINE_BASE_URL || "http://127.0.0.1:8000";
const managerToken = process.env.MANAGER_TOKEN;
const catalogQuery = process.env.BROWSER_CATALOG_QUERY || "Артикул DEMO-MAIL-12";
const expectedSource = process.env.BROWSER_EXPECTED_SOURCE || "https://example.com/demo-mail-basic";

async function main() {
  assert(managerToken, "MANAGER_TOKEN is required for the browser acceptance run");
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const messages = page.locator("#chat-messages");

    async function send(text) {
      await page.locator("#message").fill(text);
      await page.locator("#send").click();
    }

    await page.goto(base);
    await page.waitForLoadState("networkidle");
    await send(catalogQuery);
    await messages.locator("a").filter({ hasText: /источник|карточк|demo|mdaemon/i }).first()
      .waitFor({ timeout: 10_000 });
    assert((await messages.locator("a").evaluateAll((links) => links.map((link) => link.href)))
      .includes(expectedSource), "catalog link is absent from the rendered chat");

    await page.reload();
    await messages.getByText(catalogQuery, { exact: true }).waitFor();

    await send("Позовите менеджера, пожалуйста.");
    await messages.getByText("Передал ваше обращение менеджеру.", { exact: true }).waitFor();

    await page.goto(base + "/manager");
    await page.waitForLoadState("networkidle");
    await page.locator("#manager-token").fill(managerToken);
    await page.locator("#manager-sign-in").click();
    await page.locator("#queue-list .case-link").first().click();
    const details = page.locator("#case-detail");
    await details.getByText(catalogQuery, { exact: true }).waitFor();
    assert.equal(await details.getByText("Позовите менеджера, пожалуйста.", { exact: false }).count() > 0, true);
    assert.deepEqual(errors, []);
    console.log("Browser acceptance: catalog source, restored chat, and manager handoff passed.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
