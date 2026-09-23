"""Run against a local seeded demo: DEMO_PASSWORD=... python tests/e2e_smoke.py.
Not collected by pytest. Uses a temporary browser profile and performs no production writes.
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

base_url = os.getenv("PORTAL_URL", "http://127.0.0.1:8000")
password = os.environ["DEMO_PASSWORD"]
output = Path("test-results")
output.mkdir(exist_ok=True)
with sync_playwright() as p:
    executable = os.getenv("CHROME_EXECUTABLE")
    browser = p.chromium.launch(**({"executable_path": executable} if executable else {}))
    page = browser.new_page(viewport={"width": 1440, "height": 1050})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base_url + "/accounts/login/")
    page.locator("[name=username]").fill("cliente.demo")
    page.locator("[name=password]").fill(password)
    page.get_by_role("button", name="Entrar no portal").click()
    page.wait_for_url("**/t/**/")
    assert page.get_by_role("heading", name="Riscos prioritários").is_visible()
    assert page.locator("body").evaluate("(el)=>el.scrollWidth <= innerWidth")
    page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)
    page.locator('.sidebar nav a[href$="/roadmap/"]').click()
    assert page.get_by_role("heading", name="Roadmap técnico.").is_visible()
    page.screenshot(path=str(output / "roadmap-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("link", name="Visão geral", exact=True).click()
    assert page.locator("body").evaluate("(el)=>el.scrollWidth <= innerWidth")
    page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
    page.get_by_role("link", name="Capacidade", exact=True).click()
    assert page.locator("#metric-chart").is_visible()
    page.get_by_role("button", name="Sair").click()
    page.wait_for_url("**/accounts/login/")
    assert not errors, errors
    browser.close()
print("Desktop, mobile, roadmap, metric chart and logout passed.")
