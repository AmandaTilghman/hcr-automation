"""Quick dump of Details + Permissions tab HTML."""
import time
import yaml
from playwright.sync_api import sync_playwright

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

prx = cfg['prx']
pw = sync_playwright().start()
browser = pw.chromium.launch(headless=False)
page = browser.new_page()

# Login
print("Logging in...")
page.goto("https://exchange.prx.org/login", wait_until="networkidle")
page.locator('input[name="login"], input[name="email"], input[type="email"], input[name="user[login]"]').first.fill(prx['username'])
page.locator('input[name="password"], input[type="password"], input[name="user[password]"]').first.fill(prx['password'])
page.locator('input[type="submit"], button[type="submit"]').first.click()
page.wait_for_load_state("networkidle")
print("Logged in.")

# Go to create new piece
page.goto("https://exchange.prx.org/pieces/new", wait_until="networkidle")
time.sleep(2)

# Skip Basics - just Save and Continue
print("Skipping Basics...")
page.locator('input[value*="Save and Continue"], button:has-text("Save and Continue")').first.click()
page.wait_for_load_state("networkidle")
time.sleep(2)

# DETAILS TAB - dump full page HTML
print("\n=== DETAILS TAB ===")
html = page.content()
with open('prx-details-full.html', 'w') as f:
    f.write(html)
print("Saved full HTML to prx-details-full.html")

# Save and Continue to Permissions
page.locator('input[value*="Save and Continue"], button:has-text("Save and Continue")').first.click()
page.wait_for_load_state("networkidle")
time.sleep(2)

# PERMISSIONS TAB - dump full page HTML
print("\n=== PERMISSIONS TAB ===")
html = page.content()
with open('prx-permissions-full.html', 'w') as f:
    f.write(html)
print("Saved full HTML to prx-permissions-full.html")

print("\nDone! Press Enter to close.")
input()
browser.close()
pw.stop()
