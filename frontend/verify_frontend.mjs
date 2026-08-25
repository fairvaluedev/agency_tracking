import { chromium } from 'playwright';
import fs from 'fs';

const SCREENSHOT_DIR = '/home/fdv/.claude/jobs/6769a01d/tmp/screenshots';
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

const consoleErrors = [];

function report(label, ok, detail) {
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ' — ' + detail : ''}`);
}

async function main() {
  const browser = await chromium.launch({
    args: ['--no-sandbox'],
    executablePath: `${process.env.HOME}/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`,
  });
  const page = await browser.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (res) => {
    if (res.status() >= 400) consoleErrors.push(`HTTP ${res.status()} ${res.url()}`);
  });

  await page.goto('http://localhost:5173');
  await page.waitForSelector('text=Agency Tracking', { timeout: 15000 });
  await page.screenshot({ path: `${SCREENSHOT_DIR}/01-login.png` });
  report('Login page rendered', true);

  // --- Intake demo user ---
  await page.fill('input[type=email]', 'intake-demo@example.com');
  await page.fill('input[type=password]', 'AgencyDemo!2026xz');
  await page.click('button[type=submit]');
  await page.waitForSelector('text=Intake — Register a Candidate', { timeout: 15000 });
  await page.screenshot({ path: `${SCREENSHOT_DIR}/02-intake-form.png` });
  report('Intake screen shown for Recruitment/Intake user', true);

  const tag = Date.now();

  await page.getByLabel('Full name', { exact: true }).fill(`Playwright Demo ${tag}`);
  await page.getByLabel('Nationality (Country)', { exact: true }).fill('Ethiopia');
  await page.getByLabel('Phone', { exact: true }).fill('+251900000999');
  await page.getByLabel('Address', { exact: true }).fill('Addis Ababa');
  await page.getByLabel('National ID', { exact: true }).fill(`NID-${tag}`);
  await page.getByLabel('Labor ID', { exact: true }).fill(`LAB-${tag}`);
  await page.getByLabel('Target Job', { exact: true }).fill('Housemaid');
  await page.getByLabel('Salary Amount', { exact: true }).fill('150');
  await page.getByLabel('Emergency Contact Name', { exact: true }).fill('Emergency Contact');
  await page.getByLabel('Emergency Contact Phone', { exact: true }).fill('+251900000998');
  await page.getByLabel('Passport Number', { exact: true }).fill(`PASS-${tag}`);
  await page.getByLabel('Passport Issue Place', { exact: true }).fill('Addis Ababa');
  await page.getByLabel('Passport Issue Date', { exact: true }).fill('2024-01-01');
  await page.getByLabel('Passport Expiry Date', { exact: true }).fill('2029-01-01');
  await page.locator('label:has-text("Date of Birth") input').fill('1998-01-01');
  await page.locator('label:has-text("Education") input').fill('High School');

  await page.screenshot({ path: `${SCREENSHOT_DIR}/03-intake-filled.png` });
  await page.click('button[type=submit]');

  try {
    await page.waitForSelector('text=is now', { timeout: 15000 });
    const resultText = await page.locator('p:has-text("is now")').innerText();
    report('Applicant created + registered via real API', /Registered/.test(resultText), resultText);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/04-intake-result.png` });

    const genCvButton = page.locator('button:has-text("Generate CV")');
    if (await genCvButton.count()) {
      await genCvButton.click();
      await page.waitForFunction(
        () => document.body.innerText.includes('CV Generated'),
        { timeout: 15000 },
      );
      report('CV generation moved Applicant to CV Generated', true);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/05-cv-generated.png` });
    } else {
      report('Generate CV button present', false, 'button not found');
    }
  } catch (e) {
    report('Applicant created + registered via real API', false, String(e));
    await page.screenshot({ path: `${SCREENSHOT_DIR}/04-intake-error.png` });
  }

  // --- Sign out, then Foreign Agency demo user ---
  await page.click('button:has-text("Sign out")');
  await page.waitForSelector('text=Agency Tracking', { timeout: 15000 });

  await page.fill('input[type=email]', 'agency-demo@example.com');
  await page.fill('input[type=password]', 'AgencyDemo!2026xz');
  await page.click('button[type=submit]');

  try {
    await page.waitForSelector('text=Portal — Available Candidates', { timeout: 15000 });
    report('Portal screen shown for Foreign Agency user', true);
    await page.waitForSelector('text=Demo Candidate Kuwait Final', { timeout: 15000 });
    report('Seeded candidate visible in portal catalog', true);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/06-portal-catalog.png` });

    const card = page.locator('.candidate-card', { hasText: 'Demo Candidate Kuwait Final' });
    await card.locator('button').click();
    await page.waitForSelector('text=Selected:', { timeout: 15000 });
    const selectedText = await page.locator('p.success').innerText();
    report('Candidate selection created a Placement via real API', /Placement PLM-/.test(selectedText), selectedText);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/07-portal-selected.png` });

    const stillListed = await page.locator('text=Demo Candidate Kuwait Final').count();
    report('Selected candidate disappeared from catalog after reload', stillListed === 0, `count=${stillListed}`);
  } catch (e) {
    report('Portal flow', false, String(e));
    await page.screenshot({ path: `${SCREENSHOT_DIR}/06-portal-error.png` });
  }

  report('No console/page errors', consoleErrors.length === 0, consoleErrors.join(' | '));

  await browser.close();
}

main().catch((e) => {
  console.error('FATAL', e);
  process.exit(1);
});
