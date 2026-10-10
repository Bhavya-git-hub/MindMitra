"""Errors shared by the student-portal use cases. The API maps them to HTTP problems."""


class InvalidInput(Exception):
    """The request is well-formed but not acceptable (answered with 422 and the message)."""
