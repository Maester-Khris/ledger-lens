import { expect, test } from '@playwright/test';

// Public demo (spec P5 + P8): the first-five-minutes journey. One real chat turn (OpenAI), so a run costs a few cents.
const STARTER = 'What is the fee schedule in the Tremblay agreement?';

test('a guest picks a starter, opens its citation in the app, and leaves feedback', async ({ page, context }) => {
  await page.goto('/chat');
  await expect(page.getByText('The only contract with billing records to compare against.')).toBeVisible();
  await page.getByRole('button', { name: STARTER }).click();
  await expect(page.getByText(/citation\(s\)/)).toBeVisible({ timeout: 120_000 });

  await page.getByRole('button', { name: 'Open page →' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(context.pages()).toHaveLength(1); // the page opened in the app, not in a new tab
  await page.getByRole('button', { name: 'Close viewer' }).click();

  await page.getByRole('button', { name: 'Good answer' }).click();
  await expect(page.getByText('Feedback saved')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Good answer' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByLabel('Add a comment (optional)').fill('Playwright check: the citation opened on the right page.');
  await page.getByRole('button', { name: 'Send comment' }).click();
  await expect(page.getByText('Comment saved')).toBeVisible();
});
