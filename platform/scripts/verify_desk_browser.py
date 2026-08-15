"""PUI-01 Desk browser verification against the real runtime.

Not part of the test suite: this is the four-viewport acceptance run required by
`docs/plans/track-00-prototype-runtime-delivery.md`.  It drives the installed
Chrome against a live API and dev server, so it needs both running and is
invoked manually.  Component tests and curl cannot replace it: page-level
overflow, right-edge clipping and console errors only appear in a real browser.
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5173/desk"
VIEWPORTS = (
    ("1440", 1440, 900),
    ("1024", 1024, 768),
    ("768", 768, 1024),
    ("320", 320, 640),
)
SECTIONS = (
    "数据健康",
    "最新 Screen 排名变化",
    "组合偏离与风险",
    "Timing Shadow",
    "重大事件/公告流",
    "因子审核与待处理",
    "运行异常",
)
# Figma sample values that must never reach the runtime.
DESIGN_FIXTURES = ("94.2", "贵州茅台", "600519.SH", "五粮液", "28.1", "-1.62", "wind_terminal")


def run() -> int:
    results: dict[str, dict[str, object]] = {}
    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for name, width, height in VIEWPORTS:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            console: list[str] = []
            requests: list[str] = []
            page.on(
                "console",
                lambda message: console.append(f"{message.type}: {message.text}")
                if message.type in ("error", "warning")
                else None,
            )
            page.on(
                "response",
                lambda response: requests.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None,
            )
            page.goto(URL, wait_until="networkidle")
            page.wait_for_selector("text=今日研究态势 / Platform Pulse", timeout=15_000)

            metrics = page.evaluate(
                """() => ({
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth,
                    bodyScrollWidth: document.body.scrollWidth,
                })"""
            )
            overflow = metrics["scrollWidth"] > metrics["clientWidth"]

            found = [label for label in SECTIONS if page.get_by_role("region", name=label).count()]
            missing = [label for label in SECTIONS if label not in found]

            body_text = page.inner_text("body")
            leaked = [value for value in DESIGN_FIXTURES if value in body_text]

            # Right-edge clipping: any element extending past the viewport.
            clipped = page.evaluate(
                """(width) => Array.from(document.querySelectorAll('*'))
                    .filter((node) => {
                        const box = node.getBoundingClientRect()
                        return box.width > 0 && box.right > width + 1
                    })
                    .slice(0, 5)
                    .map((node) => `${node.tagName}.${node.className}`.slice(0, 80))""",
                width,
            )

            blockers = page.locator(".deskSection__blocker dt").all_inner_texts()

            results[name] = {
                "viewport": f"{width}x{height}",
                "scrollWidth": metrics["scrollWidth"],
                "clientWidth": metrics["clientWidth"],
                "page_level_overflow": overflow,
                "sections_found": len(found),
                "sections_missing": missing,
                "design_fixture_leaks": leaked,
                "clipped_elements": clipped,
                "blocker_codes": sorted(set(blockers)),
                "console_errors_warnings": console,
                "http_4xx_5xx": requests,
            }

            if overflow:
                failures.append(f"{name}: page-level horizontal overflow")
            if missing:
                failures.append(f"{name}: missing sections {missing}")
            if leaked:
                failures.append(f"{name}: DESIGN FIXTURE leak {leaked}")
            if clipped:
                failures.append(f"{name}: right-edge clipping {clipped}")
            if console:
                failures.append(f"{name}: console {console}")
            if requests:
                failures.append(f"{name}: network {requests}")

            page.screenshot(path=f"/tmp/desk-{name}.png", full_page=True)
            context.close()

        # Explicit failure and recovery at 1440.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.route("**/api/desk", lambda route: route.fulfill(status=503, body="desk store offline"))
        page.goto(URL, wait_until="networkidle")
        failure_visible = page.get_by_text("今日工作台读取失败").count() > 0
        page.unroute("**/api/desk")
        page.reload(wait_until="networkidle")
        recovered = page.get_by_text("今日研究态势 / Platform Pulse").count() > 0
        results["failure_recovery"] = {
            "explicit_failure_rendered": failure_visible,
            "recovered_after_retry": recovered,
        }
        if not failure_visible:
            failures.append("explicit 503 did not render a failure state")
        if not recovered:
            failures.append("page did not recover after the route was restored")
        context.close()

        # Keyboard and accessible-name check at 1440.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("text=今日研究态势 / Platform Pulse", timeout=15_000)
        page.keyboard.press("Tab")
        first_focus = page.evaluate(
            "() => { const a = document.activeElement; return a ? `${a.tagName}:${(a.getAttribute('aria-label') || a.textContent || '').trim().slice(0, 40)}` : null }"
        )
        region_names = page.evaluate(
            """() => Array.from(document.querySelectorAll('section[aria-label]'))
                .map((node) => node.getAttribute('aria-label'))"""
        )
        statuses = page.evaluate(
            """() => Array.from(document.querySelectorAll('[role="status"], [role="alert"]'))
                .map((node) => ({ role: node.getAttribute('role'), live: node.getAttribute('aria-live') }))"""
        )
        results["accessibility"] = {
            "first_tab_focus": first_focus,
            "region_accessible_names": region_names,
            "live_regions": statuses,
        }
        context.close()
        browser.close()

    print(json.dumps(results, ensure_ascii=False, indent=1))
    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for item in failures:
            print(f" - {item}", file=sys.stderr)
        return 1
    print("\nALL VIEWPORT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
