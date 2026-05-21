from __future__ import annotations

import time
from pathlib import Path

from .config import AppConfig
from .exceptions import ConfigError, LoginRequired, SafetyStop


LOGIN_TEXT_MARKERS = ("登录", "注册", "Sign in", "Log in")
LOGGED_IN_MARKERS = ("我的主页", "个人资料", "退出登录", "submissions")
SECURITY_MARKERS = ("验证码", "安全验证", "行为异常", "访问过于频繁", "captcha", "verify you are human")


class BrowserSession:
    def __init__(self, config: AppConfig):
        self.config = config
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._external_browser = False

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ConfigError(
                "Playwright is not installed. Run: pip install -e . && python -m playwright install chromium"
            ) from exc

        self.playwright = sync_playwright().start()
        if self.config.browser_cdp_url:
            self._connect_existing_chrome()
        else:
            self._launch_persistent_chromium()
        self.context.set_default_timeout(self.config.navigation_timeout_ms)
        self.context.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def _launch_persistent_chromium(self) -> None:
        profile_dir = Path(self.config.browser_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
        )

    def _connect_existing_chrome(self) -> None:
        self._external_browser = True
        self.browser = self.playwright.chromium.connect_over_cdp(self.config.browser_cdp_url)
        if not self.browser.contexts:
            raise ConfigError("CDP browser has no available context.")
        self.context = self.browser.contexts[0]

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context and not self._external_browser:
            self.context.close()
        if self.browser and not self._external_browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def goto_home(self) -> None:
        self.page.goto("https://leetcode.cn/", wait_until="domcontentloaded")
        self.assert_no_security_challenge()

    def wait_for_manual_login(self) -> None:
        self.goto_home()
        if self._external_browser:
            print("已连接到外部 Chrome。请在这个 Chrome 中手动登录 leetcode.cn。")
        else:
            print("浏览器已打开。请在浏览器中手动登录 leetcode.cn。")
        input("登录完成后回到终端按 Enter 继续...")
        if not self.is_logged_in():
            raise LoginRequired("登录态未检测到，请确认当前浏览器已登录 leetcode.cn。")
        print("已检测到登录态。")

    def is_logged_in(self) -> bool:
        self.assert_no_security_challenge()
        try:
            cookies = self.context.cookies("https://leetcode.cn")
        except Exception:
            cookies = []
        cookie_names = {cookie.get("name", "") for cookie in cookies}
        if "LEETCODE_SESSION" in cookie_names:
            return True

        text = self._body_text()
        if any(marker in text for marker in LOGGED_IN_MARKERS):
            return True
        if any(marker in text for marker in LOGIN_TEXT_MARKERS):
            return False
        return False

    def require_login(self) -> None:
        if self.is_logged_in():
            return
        self.goto_home()
        time.sleep(1)
        if not self.is_logged_in():
            raise LoginRequired("当前浏览器 profile 未登录。先运行 python -m lc_auto login。")

    def assert_no_security_challenge(self) -> None:
        if not self.config.stop_on_security_challenge:
            return
        text = self._body_text()
        lower_text = text.lower()
        for marker in SECURITY_MARKERS:
            if marker.lower() in lower_text:
                raise SafetyStop(f"检测到安全/风控提示：{marker}")

    def _body_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=3000)
        except Exception:
            return ""
