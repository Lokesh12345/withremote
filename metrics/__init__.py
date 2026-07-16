"""Canonical revenue metrics service (Problem Statement 2).

Computes ONE canonical "collected revenue" number over an arbitrary date range
across multiple sources, using an allow-list of statuses that count. The same
number is exposed through a summary endpoint and a breakdown endpoint, and the
codebase is structured so a second, divergent computation is caught.
"""

__version__ = "0.1.0"
