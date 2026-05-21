class LCAutoError(Exception):
    """Base error for lc_auto."""


class ConfigError(LCAutoError):
    """Configuration is invalid or incomplete."""


class LoginRequired(LCAutoError):
    """The browser profile is not logged in."""


class SafetyStop(LCAutoError):
    """Automation stopped because a safety or platform challenge was detected."""


class PageStructureError(LCAutoError):
    """The target page structure could not be parsed safely."""


class LLMError(LCAutoError):
    """The configured model provider failed."""
