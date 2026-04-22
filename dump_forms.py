"""Quick dump of ALL tabs HTML - fills required fields to advance."""
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

# Fill required fields on Basics
page.locator('#piece_title').fill("TEST DUMP - DELETE ME")
page.locator('#piece_short_description').fill("Test")
time.sleep(1)

# Save Basics HTML
html = page.content()
with open('prx-tab1-basics.html', 'w') as f:
    f.write(html)
print("Saved Basics HTML")

# Click Save and Continue
page.locator('input[value="Save and Continue"]').click()
page.wait_for_load_state("networkidle")
time.sleep(3)

# DETAILS TAB
print(f"\nNow on: {page.url}")
html = page.content()
with open('prx-tab2-details.html', 'w') as f:
    f.write(html)
print("Saved Details HTML")

# Save and Continue to Permissions
page.locator('input[value="Save and Continue"]').click()
page.wait_for_load_state("networkidle")
time.sleep(3)

# PERMISSIONS TAB
print(f"\nNow on: {page.url}")
html = page.content()
with open('prx-tab3-permissions.html', 'w') as f:
    f.write(html)
print("Saved Permissions HTML")

# Save and Continue to Publish
page.locator('input[value="Save and Continue"]').click()
page.wait_for_load_state("networkidle")
time.sleep(3)

# PUBLISH TAB
print(f"\nNow on: {page.url}")
html = page.content()
with open('prx-tab4-publish.html', 'w') as f:
    f.write(html)
print("Saved Publish HTML")

print("\nDone! DON'T publish - just close browser.")
print("Then: git add prx-tab*.html && git commit -m 'tab dumps' && git push")
input("Press Enter to close...")
browser.close()
pw.stop()
