#!/usr/bin/env python
"""Retired onboarding entry point; identity changes require the proposal gate."""
from __future__ import annotations

import sys


def main() -> int:
    print("Legacy onboarding cannot change People/Self.md.", file=sys.stderr)
    print("For a new vault, use: twinaatma init <path>", file=sys.stderr)
    print(
        "For an existing vault, ask your host to propose a Self update. "
        "Review and approve the proposal yourself in your own terminal.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
