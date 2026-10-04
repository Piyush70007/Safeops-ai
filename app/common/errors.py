"""Domain errors. The API layer maps them to HTTP status codes in one place (app/main.py)."""


class NotFound(Exception):
    """A requested resource does not exist (404)."""


class Conflict(Exception):
    """A business rule prevents the operation, e.g. not enough stock (409)."""


class DependencyUnavailable(Exception):
    """A database or downstream service failed. Honest, retryable failure (503)."""

    def __init__(self, dependency: str, reason: str) -> None:
        super().__init__(f"{dependency} unavailable: {reason}")
        self.dependency = dependency
        self.reason = reason
