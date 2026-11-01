"""The administration page in a real browser: post an announcement and create a token once."""

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.browser
PASSWORD = "correct horse battery"


def test_an_admin_posts_an_announcement_ends_it_and_creates_a_token(site):
    _, url = site
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(ignore_https_errors=True).new_page()
        page.goto(url + "/signin?return_to=%2Fui%2Fadmin%3Ftab%3Dannouncements")
        page.get_by_label("Account name", exact=True).fill("owner")
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/ui/admin?tab=announcements")
        page.wait_for_load_state("load")
        page.get_by_label("Message").fill("Upgrade tonight")
        page.get_by_label("Level").select_option("WARNING")
        page.get_by_label("Reason (recorded)").fill("upgrade")
        page.get_by_role("button", name="Post", exact=True).click()
        expect(page.locator("#admin-result")).to_contain_text("Request recorded.")
        page.reload()
        expect(page.locator(".announcement")).to_contain_text("Upgrade tonight")
        page.get_by_role("button", name="End", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Reason (recorded with the request)").fill("done")
        dialog.get_by_role("button", name="Request", exact=True).click()
        expect(page.locator("#result")).to_contain_text("End")
        page.reload()
        expect(page.locator(".announcement")).to_have_count(0)
        page.get_by_role("link", name="Tokens", exact=True).click()
        page.wait_for_url("**tab=tokens")
        page.wait_for_load_state("load")
        page.get_by_label("Name", exact=True).fill("loader")
        page.get_by_role("button", name="Create token", exact=True).click()
        expect(page.locator("#created-token")).not_to_be_empty()
        page.get_by_role("link", name="Accounts", exact=True).click()
        page.wait_for_url("**tab=accounts")
        page.wait_for_load_state("load")
        page.get_by_role("button", name="Disable", exact=True).last.click()
        expect(dialog.get_by_label("Reason (recorded with the request)")).to_be_hidden()
        browser.close()


def test_erasure_previews_before_confirming_and_never_displays_key(site):
    import json

    _, url = site
    private = "private-person-key"
    requests, confirmations = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(ignore_https_errors=True).new_page()
        page.goto(url + "/signin?return_to=%2Fui%2Fadmin%3Ftab%3Derasure%26project%3Ddefault")
        page.get_by_label("Account name", exact=True).fill("owner")
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/ui/admin?tab=erasure&project=default")
        page.wait_for_load_state("load")

        def erasure(route):
            requests.append(route.request.post_data_json)
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "schema": "etl-craft/erasure/1",
                        "dry_run": requests[-1].get("dry_run", False),
                        "tables": [
                            {
                                "table": "warehouse.ds.people",
                                "column": "person",
                                "key_hmac": "a" * 64,
                                "rows": 2,
                            }
                        ],
                        "unfollowed": [
                            {
                                "table": "warehouse.ds.hashed",
                                "reason": "Hash expression",
                                "remedy": "Register its identifier column as a further entry",
                            }
                        ],
                    }
                ),
            )

        page.route("**/api/v1/projects/default/erasure", erasure)
        apply = page.get_by_role("button", name="Register and erase", exact=True)
        expect(apply).to_be_disabled()
        page.get_by_label("First table (catalog.schema.table)").fill("ds.people")
        page.get_by_label("Identifier column", exact=True).fill("person")
        page.get_by_label("Identifier value (private)").fill(private)
        page.get_by_label("Reason (recorded)").fill("request")
        page.get_by_role("button", name="Preview erasure").click()
        expect(page.locator("#admin-result")).to_contain_text("warehouse.ds.hashed")
        expect(apply).to_be_enabled()
        assert requests[-1]["dry_run"] is True
        for theme, width in (("light", 1280), ("dark", 1280), ("light", 390)):
            page.emulate_media(color_scheme=theme)
            page.set_viewport_size({"width": width, "height": 960})
            page.screenshot(path=f"/tmp/erasure-admin-{theme}-{width}.png", full_page=True)
            assert private not in page.content()
            assert private not in page.locator("body").inner_text()

        def confirm(dialog):
            confirmations.append(dialog.message)
            dialog.accept()

        page.on("dialog", confirm)
        apply.click()
        expect(page.locator("#admin-result")).to_contain_text("Request recorded.")
        assert confirmations == ["Erase ds.people.person?"]
        assert not requests[-1].get("dry_run", False)
        expect(apply).to_be_disabled()
        assert private not in page.content()
        browser.close()
