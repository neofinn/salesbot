"""Stock research: real prices (Yahoo Finance) and financials (SEC EDGAR), technical and
fundamental analysis, and a scan for stocks near a breakout. Research only, not advice."""

from . import filters
from .screener import analyze, scan

__all__ = ["analyze", "filters", "scan"]
