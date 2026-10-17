#!/usr/bin/env python3
"""Run inside the prepared BackBox environment as its ordinary user.

Uses the actual PATH launchers and default browser discovery. The page is a
generated data URL. No external website, scan, exploit or sandbox-disable flag
is used. Selenium must already be installed by the full BackBox metapackage.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from selenium import webdriver
from selenium.webdriver.chrome.service import Service


def main():
    if os.geteuid() == 0:
        raise SystemExit("Run as the ordinary environment user")
    versions = {}
    for executable in ("chromium", "chromium-browser", "chromedriver"):
        result = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True, timeout=30)
        versions[executable] = {"path": shutil.which(executable), "version": result.stdout.strip()}
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    with tempfile.TemporaryDirectory(prefix="flagship browser ") as profile:
        options.add_argument("--user-data-dir=" + profile)
        with webdriver.Chrome(service=Service(shutil.which("chromedriver")), options=options) as browser:
            browser.get("data:text/html,<title>FlagshipOS browser automation</title>"
                        "<button id='proof' onclick=\"this.textContent='local-round-trip-passed'\">Click</button>")
            browser.find_element("id", "proof").click()
            actual = browser.find_element("id", "proof").text
            if actual != "local-round-trip-passed" or browser.title != "FlagshipOS browser automation":
                raise RuntimeError("Local browser interaction did not produce the expected result")
            observed = {"version": browser.capabilities["browserVersion"], "title": browser.title, "result": actual}
    payload = json.loads(Path("/usr/local/share/flagship/chromium-payload.json").read_text())
    if observed["version"] != payload["version"]:
        raise RuntimeError("Running browser differs from the recorded payload")
    print(json.dumps({"passed": True, "uid": os.geteuid(), "versions": versions,
                      "payload": payload, "browser": observed, "sandbox_disabling_flags": [],
                      "scope": "Real PATH launchers, default browser discovery and local Selenium interaction"}, indent=2))


if __name__ == "__main__":
    main()
