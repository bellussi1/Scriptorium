"""Structured record of why an LLM request returned no response.

Providers catch their transport errors and return None so the translator can
retry. Before this record existed the exception was logged by the provider and
then lost, so the translator could only say "LLM API request failed". A provider
now stores an LLMFailure on itself before returning None, and the translator
reads it back through LLMClient.last_failure.
"""
from dataclasses import dataclass
from typing import Optional

_MAX_MESSAGE_CHARS = 300


@dataclass(frozen=True)
class LLMFailure:
    """The exception behind a request that produced no response.

    Attributes:
        provider: Provider name, e.g. "ollama".
        kind: Provider classification: "timeout", "http", "json" or "unexpected".
        error_type: Python class name of the exception, e.g. "ReadTimeout".
        message: Exception or server message, truncated for the log.
        status: HTTP status code when the failure carried one, else None.
    """

    provider: str
    kind: str
    error_type: str
    message: str
    status: Optional[int] = None

    @classmethod
    def from_exception(
        cls,
        provider: str,
        kind: str,
        exc: BaseException,
        message: Optional[str] = None,
        status: Optional[int] = None,
    ) -> "LLMFailure":
        text = str(exc) if message is None else message
        return cls(
            provider=provider,
            kind=kind,
            error_type=type(exc).__name__,
            message=(text or "").strip()[:_MAX_MESSAGE_CHARS],
            status=status,
        )

    def describe(self) -> str:
        """One log line: provider, exception type, HTTP status and message."""
        status = f" (HTTP {self.status})" if self.status is not None else ""
        message = f": {self.message}" if self.message else ""
        return f"{self.provider} {self.error_type}{status}{message}"
