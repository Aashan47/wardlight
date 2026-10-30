"""Errors the stores raise; main.py maps them to 404 and 422."""


class NotFound(Exception):
    pass


class BadInput(Exception):
    pass
