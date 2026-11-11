"""Uploads, a task's offset reset and data lookup in a real browser."""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import text
from test_react_ui import open_page, sign_in

from etl_craft.core.actor import Actor, ActorKind, acting_as
from fixtures.metadata import add_pipeline, add_task, finish_run, start_run, task_run

pytestmark = pytest.mark.browser


def shoot(page, name):
    shots = os.environ.get("ETL_CRAFT_UI_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/{name}.png")


@pytest.fixture
def steward(site):
    ctx, url = site
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "CORRECTIONS")
        add_task(
            conn,
            pipeline,
            "check",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
        )
        conn.execute(text("UPDATE CFG_PIPELINES SET STEWARDABLE_FLAG='Y'"))
    return ctx, url


@pytest.fixture
def merge_task(site, tmp_path):
    ctx, url = site
    (tmp_path / "sql_scripts").mkdir()
    (tmp_path / "sql_scripts" / "load.sql").write_text(
        "SELECT 1 AS id WHERE 1 > $$watermark", encoding="utf-8"
    )
    with acting_as(Actor("owner", ActorKind.USER)), ctx.engine.begin() as conn:
        pipeline = add_pipeline(conn, "SALES")
        load = add_task(
            conn,
            pipeline,
            "LOAD",
            "SQL",
            SQL_ACTION="SCD1_MERGE",
            TARGET_OBJECT="wh.sales.orders",
            SCRIPT_FILE="sql_scripts/load.sql",
            WATERMARK_COLUMN="id",
            WATERMARK_TYPE="NUMBER",
            WATERMARK_START="0",
            MERGE_KEY="order_id|line_id",
            MERGE_COMPARE_COLUMNS="amount|status",
        )
        run = start_run(conn, pipeline)
        task_run(conn, load, run)
        finish_run(conn, run)
    return ctx, url


def upload_button(page):
    return page.locator("form").get_by_role("button", name="Upload", exact=True)


def test_a_steward_uploads_a_file_and_sees_it_listed(steward, tmp_path):
    _, url = steward
    data = tmp_path / "corrections.csv"
    data.write_text("id|name\n1|first\n")
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 900})
        sign_in(page, url, "/ui/projects/default/uploads")
        expect(page.get_by_role("heading", name="Uploads")).to_be_visible()
        expect(page.get_by_text("Recent files for CORRECTIONS")).to_be_visible()
        expect(upload_button(page)).to_be_disabled()
        page.get_by_label("File", exact=True).set_input_files(str(data))
        upload_button(page).click()
        received = page.get_by_role("status").filter(has_text=re.compile(r"Upload \d+ received"))
        expect(received).to_be_visible()
        table = page.get_by_role("table", name="Recent files")
        expect(table.get_by_role("cell", name="corrections.csv", exact=True)).to_be_visible()
        expect(
            table.get_by_role("cell", name=re.compile(r"^[0-9]+-corrections\.csv$"))
        ).to_be_visible()
        shoot(page, "uploads")
        assert problems == []
        browser.close()


def test_a_viewer_with_no_upload_grant_is_told_how_to_get_one(steward):
    _, url = steward
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw)
        sign_in(page, url, "/ui/projects/default/uploads", name="alice")
        expect(page.get_by_text("No pipeline takes uploads from you here.")).to_be_visible()
        expect(upload_button(page)).to_have_count(0)
        browser.close()


def test_an_operator_resets_a_watermark_with_a_reason(merge_task):
    _, url = merge_task
    with sync_playwright() as pw:
        browser, page, problems = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/pipelines/SALES/tasks/LOAD")
        expect(page.get_by_role("heading", name="Watermark")).to_be_visible()
        expect(page.get_by_text("Nothing stored yet; the first run starts it.")).to_be_visible()
        shoot(page, "task-offset")
        page.get_by_role("button", name="Reset the watermark").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("starts from the new value")).to_be_visible()
        confirm = dialog.get_by_role("button", name="Reset the watermark")
        expect(confirm).to_be_disabled()
        dialog.get_by_label("New value").fill("42")
        expect(dialog.get_by_label("Record the reset against run")).to_have_value("1")
        dialog.get_by_label("Reason (kept in the audit trail)").fill("replay from 42")
        expect(confirm).to_be_enabled()
        confirm.click()
        done = page.get_by_role("status").filter(has_text="watermark 0 -> 42 (NUMBER)")
        expect(done).to_be_visible()
        expect(page.get_by_text("Nothing stored yet")).to_have_count(0)  # the card shows 42
        assert problems == []
        browser.close()


def test_the_data_lookup_asks_for_every_key_column_and_answers(merge_task):
    _, url = merge_task
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, viewport={"width": 1280, "height": 1000})
        sign_in(page, url, "/ui/projects/default/pipelines/SALES/tasks/LOAD")
        expect(page.get_by_role("heading", name="Data")).to_be_visible()
        look = page.get_by_role("button", name="Look up")
        expect(look).to_be_disabled()
        page.get_by_label("order_id").fill("1001")
        expect(look).to_be_disabled()  # both key columns are needed
        page.get_by_label("line_id").fill("1")
        expect(look).to_be_enabled()
        look.click()
        expect(
            page.get_by_text("Value protection is not enabled").or_(page.get_by_role("alert"))
        ).to_be_visible()
        shoot(page, "task-data")
        browser.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_the_operate_pages_render_cleanly_in_both_themes_and_on_a_phone(merge_task, scheme, width):
    _, url = merge_task
    pages = {
        "uploads": "/ui/projects/default/uploads",
        "task": "/ui/projects/default/pipelines/SALES/tasks/LOAD",
    }
    with sync_playwright() as pw:
        browser, page, problems = open_page(
            pw, color_scheme=scheme, viewport={"width": width, "height": 900}
        )
        sign_in(page, url)
        for name, path in pages.items():
            page.goto(url + path)
            page.wait_for_load_state("networkidle")
            expect(page.locator("main")).to_be_visible()
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 0, f"{name} scrolls sideways by {overflow}px at {width}px"
            shoot(page, f"{name}-{scheme}-{width}")
        assert problems == []
        browser.close()
