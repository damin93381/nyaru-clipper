import { expect, test } from "@playwright/test";

test("keeps legacy routes dark while workstation navigation has a three-pixel focus ring", async ({ page }) => {
  // Given: the legacy entry route and the workstation shell in one production-like browser session.
  await page.goto("/");
  const legacyBaseline = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);

  await page.goto("/workstation");
  const queueLink = page.getByRole("link", { name: "处理队列" });

  // When: keyboard focus reaches the workstation queue navigation.
  await queueLink.focus();

  // Then: legacy global styling is intact and focus is the required tokenized 3px outline.
  await expect(queueLink).toBeFocused();
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(legacyBaseline);
  expect(await queueLink.evaluate((link) => getComputedStyle(link).outlineWidth)).toBe("3px");
  expect(await queueLink.evaluate((link) => getComputedStyle(link).outlineStyle)).toBe("solid");
});
