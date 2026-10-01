import { expect, test } from '@playwright/test';

// Public demo (DEMO_MODE, spec P2+P9): a guest approves an AI-proposed fee correction. The ledger checks it,
// nothing is recorded, and only that guest sees it. One real chat turn (OpenAI), so a run costs a few cents.
const QUESTION =
  'Compare the Tremblay agreement fee schedule with its billing schedule and propose the correction for the annual fee gap.';
const DEMO_POSTINGS = 'Your demo postings (not recorded)';

test('a demo guest approves an AI correction that is checked but never recorded', async ({ page, browser }) => {
  await test.step('uploads are off', async () => {
    await page.goto('/documents');
    await expect(page.getByText('Uploads are off in the public demo.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Upload document/ })).toHaveCount(0);
  });

  await test.step('the agent proposes a correction and the guest approves it', async () => {
    await page.goto('/chat');
    await page.getByLabel('Ask about your indexed contracts').fill(QUESTION);
    await page.getByRole('button', { name: 'Send message' }).click();
    const approve = page.getByRole('button', { name: 'Approve (demo, not recorded)' });
    await expect(approve).toBeVisible({ timeout: 120_000 });
    await approve.click();
    await expect(page.getByText(/Demo posting, not recorded\./)).toBeVisible();
  });

  await test.step('the ledger lists it as a demo posting and offers no reversal', async () => {
    await page.goto('/ledger');
    await expect(page.getByText(DEMO_POSTINGS)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reverse posting' })).toHaveCount(0);
  });

  await test.step('another visitor (a new guest) sees none of it', async () => {
    const other = await browser.newContext();
    const otherPage = await other.newPage();
    await otherPage.goto('/ledger');
    await expect(otherPage.getByRole('heading', { name: /Postings/ })).toBeVisible();
    await otherPage.waitForLoadState('networkidle'); // the demo postings section loads after the page
    await expect(otherPage.getByText(DEMO_POSTINGS)).toHaveCount(0);
    await other.close();
  });
});

test('nonsense gets an explicit refusal with a system reason', async ({ page }) => {
  await page.goto('/chat');
  await page.getByLabel('Ask about your indexed contracts').fill('fee fee banana tier tier');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('No answer')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/System · indexed contracts/)).toBeVisible();
});
