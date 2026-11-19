"""
LLM-specific exceptions.

This module defines all custom exceptions used in the LLM provider system.
"""

from typing import Any


class ContextOverflowError(Exception):
    """
    Raised when the input text exceeds the model's context window.

    This typically occurs when a chunk is too large for the model to process
    in a single request.
    """
    pass


class RepetitionLoopError(Exception):
    """
    Raised when the model enters a repetition loop.

    This can occur with "thinking" models that get stuck repeating the same
    phrase or pattern, indicating the model has likely exceeded its effective
    context window or encountered an issue.
    """
    pass


class RateLimitError(Exception):
    """
    Raised when the API returns HTTP 429 (Too Many Requests) and all retry
    attempts with backoff have been exhausted.

    This signals the translation pipeline to auto-pause and save a checkpoint
    so the user can resume later.

    Attributes:
        retry_after: Suggested wait time in seconds (from Retry-After header),
                     or None if not provided by the API.
        provider: Name of the LLM provider that was rate-limited.
        partial_result: Best-effort, already-reassembled payload carrying the
                        work completed before the rate limit hit, so the caller
                        can persist it instead of discarding it. Its type is
                        defined by whoever raises (or re-raises) the error;
                        None when the raiser has nothing to hand over.
    """

    def __init__(self, message: str, retry_after: int = None, provider: str = None,
                 partial_result: Any = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.provider = provider
        self.partial_result = partial_result


# Exit code of translate.py when a run is aborted by BillingExhaustedError. The
# queue runner (host side, no src.core import) mirrors this value to pause the
# book instead of finalizing a partial output.
BILLING_EXHAUSTED_EXIT_CODE = 3


class BillingExhaustedError(Exception):
    """
    Raised when the provider account has no spendable credit left.

    Providers signal this as HTTP 402 (Payment Required), "prepayment credits
    are depleted", "insufficient balance" or an equivalent billing error.
    Retrying cannot help and the per-chunk fallback would silently save the
    source text as if it were translated, so the translation pipeline must let
    this propagate and stop the run. Top up the provider wallet and resume from
    the saved checkpoint.

    Attributes:
        provider: Name of the LLM provider that ran out of credit.
    """

    def __init__(self, message: str, provider: str = None):
        super().__init__(message)
        self.provider = provider
