"""Render the actual HTML accepted by Mailpit in the isolated browser test harness."""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright

from etl_craft.config import ConnectionProfile, ConnectorConfig, EmailProfile, SourceConfig
from etl_craft.handlers.email_templates import render
from etl_craft.handlers.mail import send_email
from fixtures.email_cases import email_case
from fixtures.services import require

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("outcome", ["FAILED", "SUCCESS", "SLA"])
def test_delivered_email_layout_and_escaping(tmp_path, outcome):
    smtp, api = require("mailpit_smtp"), require("mailpit_api")
    config = ConnectorConfig(
        source=SourceConfig(type="environment"),
        engine=ConnectionProfile("ENGINE", "dev", "jdbc:sqlite:unused.db", "main", "NONE"),
        email=EmailProfile(
            "EMAIL", "dev", smtp.host, smtp.port, "etl@example.com", tls_mode="NONE"
        ),
    )
    data = email_case(outcome)
    subject = data["subject"] + " " + uuid4().hex
    send_email(
        config,
        data["recipients"],
        subject,
        render(config, None, data),
        body_text=render(config, None, data, text=True),
    )
    query = urlencode({"query": f'subject:"{subject}"'})
    deadline = time.monotonic() + 10
    while True:
        with urlopen(f"{api.http_url}/api/v1/search?{query}", timeout=10) as response:
            messages = json.load(response)["messages"]
        if messages or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    assert len(messages) == 1
    with urlopen(f"{api.http_url}/api/v1/message/{messages[0]['ID']}", timeout=10) as response:
        delivered = json.load(response)
    assert delivered["Subject"] == subject
    assert "PRODUCTION" in delivered["Text"]
    output = Path(os.environ.get("ETL_CRAFT_EMAIL_SCREENSHOTS", str(tmp_path / "email")))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (900, 390):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                page.set_content(delivered["HTML"])
                expect(page.get_by_role("heading", level=1)).to_contain_text(
                    "IN-PROGRESS" if outcome == "SLA" else outcome
                )
                assert page.locator("script").count() == 0
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                if outcome == "FAILED":
                    expect(page.locator("pre").first).to_have_text(data["errors"][0])
                page.screenshot(path=str(output / f"{outcome.lower()}-{width}.png"), full_page=True)
                page.close()
        finally:
            browser.close()
