"""Signing in to VigiFlow and handing over the page.

The email-driven process needs exactly two things from VigiFlow: a signed-in
browser, and the page to read reports from. Everything else the client used to
do belonged to the filter-driven process and went with it.

Sign-in is delegated to Azure AD B2C, so opening VigiFlow redirects to the
identity provider and a successful sign-in redirects back.
"""

from __future__ import annotations

import logging

from vigiflow_tasks.config import VigiFlowConfig
from vigiflow_tasks.vigiflow import locators as loc
from vigiflow_tasks.vigiflow.base import VigiFlowError

LOGGER = logging.getLogger(__name__)

# The redirect chain through the identity provider is slower than a page load,
# and the application shell can take a while to paint after it.
LOGIN_TIMEOUT_MS = 60_000


class BrowserVigiFlowClient:
    """Opens one browser for the whole run and reuses the session."""

    def __init__(self, config: VigiFlowConfig):
        self.config = config
        self._page = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "BrowserVigiFlowClient":
        from robocorp import browser

        browser.configure(
            browser_engine="chromium",
            headless=self.config.headless,
            slowmo=self.config.slowmo_ms,
            # Off, not "only-on-failure". A failure screenshot of a report
            # page is the whole case in a picture, embedded in log.html.
            # The only screenshots this process keeps are of pages that
            # turned out not to be reports.
            screenshot="off",
        )
        self._page = browser.page()
        self._page.set_default_timeout(self.config.timeout_ms)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # robocorp.browser closes its context when the task ends. Closing the
        # page here keeps repeated local runs from stacking up windows.
        if self._page is not None:
            try:
                self._page.close()
            except Exception:  # pragma: no cover - best effort cleanup
                LOGGER.debug("Ignoring error while closing the page", exc_info=True)
            self._page = None

    @property
    def page(self):
        if self._page is None:
            raise VigiFlowError("Use the client as a context manager before calling it")
        return self._page

    # -- authentication ----------------------------------------------------

    def login(self) -> None:
        """Sign in through Azure AD B2C and wait to land back on VigiFlow.

        Success is judged by returning to the application host, not by finding
        an element. Every page in the redirect chain looks loaded, so an
        element check fires on the wrong one.

        B2C also rejects a password without navigating, so a refusal looks
        exactly like a slow page. :meth:`_login_problem` reads the inline
        message it leaves behind, which is the difference between "wrong
        password" and "the network is slow".
        """
        self.page.goto(self.config.url, wait_until="domcontentloaded")

        # The redirect to the identity provider happens in JavaScript, so the
        # first document to finish loading is the application shell, not the
        # page we end up on. Waiting for whichever of the two outcomes appears
        # is what makes this reliable.
        outcome = f"{loc.LOGIN_PASSWORD}, {loc.LOGIN_SUCCESS_MARKER}"
        try:
            self.page.wait_for_selector(outcome, timeout=LOGIN_TIMEOUT_MS)
        except Exception as err:
            raise VigiFlowError(
                f"Neither the sign-in form nor the application appeared at "
                f"{self.config.url} within {LOGIN_TIMEOUT_MS // 1000}s."
            ) from err

        if not self.page.locator(loc.LOGIN_PASSWORD).count():
            LOGGER.info("Already signed in, the session was still valid")
            return

        try:
            self.page.fill(loc.LOGIN_USERNAME, self.config.username)
            self.page.fill(loc.LOGIN_PASSWORD, self.config.password)
            # Not guarded, and deliberately so: this is the Sign in button on
            # the identity provider, not a control inside VigiFlow. The guard's
            # denylist describes VigiFlow's own page.
            self.page.click(loc.LOGIN_SUBMIT)
        except Exception as err:
            raise VigiFlowError(
                "Could not complete the sign-in form. The identity provider may "
                "have changed."
            ) from err

        try:
            self.page.wait_for_url(f"**{loc.APP_HOST}/**", timeout=LOGIN_TIMEOUT_MS)
        except Exception as err:
            raise VigiFlowError(
                f"Sign-in did not return to {loc.APP_HOST}. {self._login_problem()}"
            ) from err

        self._wait_for_application()
        LOGGER.info("Signed in to VigiFlow at %s", self.config.url)

    def _wait_for_application(self) -> None:
        """Wait for the application shell after the redirect.

        The shell can be slow to paint, and a slow load is not a failed
        sign-in. One reload is allowed before giving up, which has been enough
        every time it has been needed.
        """
        if not loc.LOGIN_SUCCESS_MARKER:
            return
        try:
            self.page.wait_for_selector(loc.LOGIN_SUCCESS_MARKER, timeout=LOGIN_TIMEOUT_MS)
            return
        except Exception:
            LOGGER.warning("Application slow to appear; reloading once")

        try:
            self.page.reload(wait_until="domcontentloaded")
            self.page.wait_for_selector(loc.LOGIN_SUCCESS_MARKER, timeout=LOGIN_TIMEOUT_MS)
        except Exception as err:
            raise VigiFlowError(
                f"Signed in and back on {loc.APP_HOST}, but the application never "
                f"finished loading ({loc.LOGIN_SUCCESS_MARKER} absent after "
                f"{2 * LOGIN_TIMEOUT_MS // 1000}s)."
            ) from err

    def _login_problem(self) -> str:
        """Whatever the sign-in page is complaining about, for the error message."""
        for selector in loc.LOGIN_ERROR_MARKERS:
            try:
                element = self.page.locator(selector)
                if element.count():
                    text = element.first.inner_text().strip()
                    if text:
                        return f"The sign-in page says: {text}"
            except Exception:
                continue
        return "Check the credentials in the vault."
