"""
PRX Form Diagnostic
===================
Opens PRX, navigates through each tab, and dumps the form HTML
so we can see the exact field names and structure.
"""
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

# BASICS TAB
print("\n=== BASICS TAB ===")
print("Dumping form elements...")

# Get all form inputs
elements = page.evaluate("""
    () => {
        const results = [];
        // Inputs
        document.querySelectorAll('input, select, textarea, button').forEach(el => {
            results.push({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                value: el.value || '',
                placeholder: el.placeholder || '',
                visible: el.offsetParent !== null,
                text: el.textContent?.substring(0, 100) || '',
                className: el.className?.substring(0, 100) || '',
            });
        });
        // Labels
        document.querySelectorAll('label').forEach(el => {
            results.push({
                tag: 'LABEL',
                for: el.htmlFor || '',
                text: el.textContent?.trim().substring(0, 100) || '',
                visible: el.offsetParent !== null,
                className: el.className?.substring(0, 100) || '',
            });
        });
        return results;
    }
""")

with open('prx-basics-elements.txt', 'w') as f:
    for el in elements:
        f.write(str(el) + '\n')
print(f"Saved {len(elements)} elements to prx-basics-elements.txt")

# Click series checkbox and see what happens
print("\nClicking series checkbox...")
page.evaluate("""
    () => {
        const labels = Array.from(document.querySelectorAll('label'));
        const seriesLabel = labels.find(l => l.textContent.includes('Add this piece'));
        if (seriesLabel) {
            seriesLabel.click();
            return 'clicked label';
        }
        return 'no label found';
    }
""")
time.sleep(2)

# Dump series area
series_html = page.evaluate("""
    () => {
        const sel = document.querySelector('#piece_series_id');
        if (sel) {
            return {
                html: sel.outerHTML.substring(0, 2000),
                parent: sel.parentElement?.outerHTML.substring(0, 2000),
                visible: sel.offsetParent !== null,
                display: window.getComputedStyle(sel).display,
                parentDisplay: window.getComputedStyle(sel.parentElement).display,
            };
        }
        return 'no series select found';
    }
""")
print(f"Series dropdown: {series_html}")

with open('prx-series-debug.txt', 'w') as f:
    f.write(str(series_html))

# Save and Continue to Details
page.locator('input[value*="Save and Continue"], button:has-text("Save and Continue")').first.click()
page.wait_for_load_state("networkidle")
time.sleep(2)

# DETAILS TAB
print("\n=== DETAILS TAB ===")

details_elements = page.evaluate("""
    () => {
        const results = [];
        document.querySelectorAll('input, select, textarea, button, a').forEach(el => {
            results.push({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                value: el.value?.substring(0, 50) || '',
                placeholder: el.placeholder || '',
                visible: el.offsetParent !== null,
                text: el.textContent?.trim().substring(0, 100) || '',
                href: el.href?.substring(0, 100) || '',
                className: el.className?.substring(0, 100) || '',
            });
        });
        document.querySelectorAll('label').forEach(el => {
            results.push({
                tag: 'LABEL',
                for: el.htmlFor || '',
                text: el.textContent?.trim().substring(0, 100) || '',
                visible: el.offsetParent !== null,
            });
        });
        return results;
    }
""")

with open('prx-details-elements.txt', 'w') as f:
    for el in details_elements:
        f.write(str(el) + '\n')
print(f"Saved {len(details_elements)} elements to prx-details-elements.txt")

page.screenshot(path="prx-details-diagnostic.png")

# Save and Continue to Permissions
page.locator('input[value*="Save and Continue"], button:has-text("Save and Continue")').first.click()
page.wait_for_load_state("networkidle")
time.sleep(2)

# PERMISSIONS TAB
print("\n=== PERMISSIONS TAB ===")

perms_elements = page.evaluate("""
    () => {
        const results = [];
        document.querySelectorAll('input, select, textarea, button').forEach(el => {
            results.push({
                tag: el.tagName,
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                value: el.value?.substring(0, 50) || '',
                visible: el.offsetParent !== null,
                text: el.textContent?.trim().substring(0, 100) || '',
                checked: el.checked || false,
                className: el.className?.substring(0, 100) || '',
            });
        });
        document.querySelectorAll('label').forEach(el => {
            results.push({
                tag: 'LABEL',
                for: el.htmlFor || '',
                text: el.textContent?.trim().substring(0, 100) || '',
                visible: el.offsetParent !== null,
            });
        });
        return results;
    }
""")

with open('prx-permissions-elements.txt', 'w') as f:
    for el in perms_elements:
        f.write(str(el) + '\n')
print(f"Saved {len(perms_elements)} elements to prx-permissions-elements.txt")

page.screenshot(path="prx-permissions-diagnostic.png")

print("\nDone! Check the .txt files for element details.")
print("Press Enter to close browser...")
input()
browser.close()
pw.stop()
