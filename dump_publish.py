"""Dump the Publish tab HTML from an existing piece."""
import time, yaml
from playwright.sync_api import sync_playwright

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

prx = cfg['prx']
pw = sync_playwright().start()
browser = pw.chromium.launch(headless=False)
page = browser.new_page()

print("Logging in...")
page.goto("https://exchange.prx.org/login", wait_until="networkidle")
page.locator('input[name="login"], input[name="email"], input[type="email"], input[name="user[login]"]').first.fill(prx['username'])
page.locator('input[name="password"], input[type="password"], input[name="user[password]"]').first.fill(prx['password'])
page.locator('input[type="submit"], button[type="submit"]').first.click()
page.wait_for_load_state("networkidle")
print("Logged in.")

# Go to the latest piece's edit page — Publish tab
page.goto("https://exchange.prx.org/pieces/616227-untitled-april-22-2026/edit", wait_until="networkidle")
time.sleep(3)

# Click "Publish" tab in nav
page.evaluate("""
    () => {
        const links = document.querySelectorAll('a');
        for (const a of links) {
            if (a.textContent.trim() === 'Publish' && a.closest('.create-piece-step')) {
                a.click();
                return 'clicked publish tab';
            }
        }
        return 'not found';
    }
""")
time.sleep(5)

print(f"URL: {page.url}")
html = page.content()
with open('prx-publish-real.html', 'w') as f:
    f.write(html)
print("Saved to prx-publish-real.html")

# Also find anything that looks like a publish button
buttons = page.evaluate("""
    () => {
        const results = [];
        document.querySelectorAll('input, button, a').forEach(el => {
            const text = (el.value || el.textContent || '').trim();
            if (text.toLowerCase().includes('publish')) {
                results.push({
                    tag: el.tagName,
                    text: text,
                    id: el.id,
                    class: el.className,
                    href: el.href || '',
                    type: el.type || '',
                    name: el.name || '',
                });
            }
        });
        return results;
    }
""")
print("\\nPublish-related elements:")
for b in buttons:
    print(f"  {b}")

input("\\nPress Enter to close...")
browser.close()
pw.stop()
