"""Administration exposes custom roles and wide bindings on desktop and mobile."""

import re

import pytest
from playwright.sync_api import expect, sync_playwright
from test_react_ui import open_page, shoot, sign_in

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
def test_administration_roles_create_bind_and_revoke(site, scheme, width):
    _, url = site
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 1000}
        )
        sign_in(page, url, "/ui/admin?tab=roles")
        expect(page.get_by_role("tab", name="Roles", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        table = page.get_by_role("table", name="Roles", exact=True)
        expect(table.get_by_role("row").filter(has_text="CAN_MANAGE")).to_be_visible()
        page.get_by_role("button", name="Describe role CAN_MANAGE", exact=True).click()
        details = page.get_by_role("dialog")
        expect(details.get_by_text("run", exact=True)).to_be_visible()
        expect(details.get_by_text("config apply", exact=True)).to_be_visible()
        details.get_by_role("list").focus()
        expect(details.get_by_role("list")).to_be_focused()
        page.keyboard.press("Escape")
        expect(details).not_to_be_visible()
        describe = page.get_by_role("button", name="Describe role CAN_MANAGE", exact=True)
        expect(describe).to_be_focused()
        describe.click()
        expect(details).to_have_css("opacity", "1")
        expect(details.get_by_role("list")).to_have_css("font-size", "14px")
        shoot(page, f"admin-role-commands-{scheme}-{width}")
        details.get_by_role("button", name="Close", exact=True).click()
        expect(details).not_to_be_visible()
        shoot(page, f"admin-roles-overview-{scheme}-{width}")
        page.get_by_role("button", name="Create role", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Role name, such as data-analyst", exact=False).fill("runner")
        dialog.get_by_label("Description", exact=False).fill("Runs approved loads")
        dialog.get_by_role("button", name="Create role", exact=True).click()
        row = table.get_by_role("row").filter(has_text="runner")
        expect(row).to_contain_text("None yet")
        page.get_by_role("button", name="Add command", exact=True).click()
        dialog.get_by_label(re.compile(r"^Role")).select_option("runner")
        dialog.get_by_label("Command, such as run or pool set", exact=False).fill("run")
        dialog.get_by_role("button", name="Add command", exact=True).click()
        expect(row).to_contain_text("run")
        page.get_by_label(re.compile(r"^Reach")).select_option("PROD")
        page.get_by_role("button", name="Grant access", exact=True).click()
        dialog.get_by_label(re.compile(r"^Account\b")).fill("alice")
        dialog.get_by_label(re.compile(r"^Role")).select_option("runner")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Production support")
        dialog.get_by_role("button", name="Grant access", exact=True).click()
        binding = (
            page.get_by_role("table", name="Access to every PROD project")
            .get_by_role("row")
            .filter(has_text="account alice")
        )
        expect(binding).to_contain_text("runner")
        expect(binding).to_contain_text("every PROD project")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        dismiss = page.get_by_role("button", name="Dismiss", exact=True)
        for _ in range(dismiss.count()):
            dismiss.first.click()
        shoot(page, f"admin-roles-{scheme}-{width}")
        binding.get_by_role("button", name="Revoke", exact=True).click()
        dialog.get_by_label("Reason (kept in the audit trail)").fill("Support ended")
        dialog.get_by_role("button", name="Revoke", exact=True).click()
        expect(binding).to_have_count(0)
        dismiss.click()
        page.get_by_label("Account", exact=True).fill("alice")
        page.get_by_label("Command", exact=True).fill("run")
        page.get_by_label("Project (optional)", exact=True).fill("default")
        page.get_by_role("button", name="Explain access", exact=True).click()
        expect(page.get_by_role("status").filter(has_text="Refused")).to_be_visible()
        page.get_by_role("button", name="Remove command", exact=True).click()
        dialog.get_by_label(re.compile(r"^Role")).select_option("runner")
        dialog.get_by_label("Command to remove", exact=False).fill("run")
        dialog.get_by_role("button", name="Remove command", exact=True).click()
        expect(row).to_contain_text("None yet")
        row.get_by_role("button", name="Disable", exact=True).click()
        dialog.get_by_role("button", name="Disable", exact=True).click()
        expect(row).to_contain_text("Disabled")
        assert problems == []
        browser.close()
