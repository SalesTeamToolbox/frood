#!/usr/bin/env python3
"""
Agent42 E2E Test Runner

Self-improving test runner that:
  1. Discovers current codebase state (endpoints, tools, views, etc.)
  2. Runs all test suites against a live Agent42 instance
  3. Reports coverage gaps (untested endpoints, tools, views)
  4. Generates a coverage manifest for tracking growth over time

Usage:
    python -m tests.e2e.runner                    # run all suites
    python -m tests.e2e.runner --suite ui         # run one suite
    python -m tests.e2e.runner --suite api        # run one suite
    python -m tests.e2e.runner --discover         # show codebase manifest only
    python -m tests.e2e.runner --coverage         # show coverage gaps
    python -m tests.e2e.runner --headed           # run with visible browser
    python -m tests.e2e.runner --url http://x:80  # custom base URL
"""

import argparse
import json
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import config, AGENT42_ROOT
from .discovery import build_manifest


# ---------------------------------------------------------------------------
# Test result types
# ---------------------------------------------------------------------------

class TestResult:
    def __init__(self, name: str, suite: str):
        self.name = name
        self.suite = suite
        self.passed = False
        self.skipped = False
        self.error: str | None = None
        self.duration: float = 0.0
        self.screenshots: list[str] = []
        self.covers: list[str] = []  # what endpoints/features this test covers

    def __repr__(self):
        status = "PASS" if self.passed else ("SKIP" if self.skipped else "FAIL")
        return f"[{status}] {self.suite}/{self.name} ({self.duration:.1f}s)"


# ---------------------------------------------------------------------------
# Suite registry — suites self-register here
# ---------------------------------------------------------------------------

_SUITES: dict[str, "type"] = {}


def register_suite(name: str):
    """Decorator to register a test suite class."""
    def decorator(cls):
        _SUITES[name] = cls
        return cls
    return decorator


class BaseSuite:
    """Base class for all E2E test suites."""

    name: str = "base"

    def __init__(self):
        self.results: list[TestResult] = []

    def setup(self):
        """Called once before the suite runs."""

    def teardown(self):
        """Called once after the suite finishes."""

    def run_all(self) -> list[TestResult]:
        """Discover and run all test_ methods."""
        self.setup()
        test_methods = sorted(
            m for m in dir(self) if m.startswith("test_") and callable(getattr(self, m))
        )
        for method_name in test_methods:
            result = TestResult(name=method_name, suite=self.name)
            start = time.time()
            try:
                method = getattr(self, method_name)
                method(result)
                result.passed = True
            except SkipTest as e:
                result.skipped = True
                result.error = str(e)
            except Exception as e:
                result.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            result.duration = time.time() - start
            self.results.append(result)
        self.teardown()
        return self.results


class SkipTest(Exception):
    """Raise to skip a test."""


def assert_contains(output: str, expected: str, msg: str = ""):
    """Assert that output contains expected substring."""
    if expected.lower() not in output.lower():
        raise AssertionError(
            f"{msg or 'Missing expected content'}: "
            f"expected '{expected}' in output:\n{output[:500]}"
        )


def assert_not_contains(output: str, unexpected: str, msg: str = ""):
    """Assert that output does NOT contain unexpected substring."""
    if unexpected.lower() in output.lower():
        raise AssertionError(
            f"{msg or 'Found unexpected content'}: "
            f"found '{unexpected}' in output:\n{output[:500]}"
        )


def assert_snapshot_has(output: str, element_pattern: str, msg: str = ""):
    """Assert snapshot output contains an element matching pattern."""
    if element_pattern.lower() not in output.lower():
        raise AssertionError(
            f"{msg or 'Element not found in snapshot'}: "
            f"expected '{element_pattern}' in:\n{output[:1000]}"
        )


# ---------------------------------------------------------------------------
# Coverage analysis
# ---------------------------------------------------------------------------

def compute_coverage(results: list[TestResult], manifest):
    """Compute what % of discovered features are tested."""
    covered_paths = set()
    for r in results:
        for c in r.covers:
            covered_paths.add(c)

    endpoint_paths = {f"{e.method} {e.path}" for e in manifest.endpoints}
    tested_endpoints = covered_paths & endpoint_paths
    untested_endpoints = endpoint_paths - covered_paths

    return {
        "total_endpoints": len(endpoint_paths),
        "tested_endpoints": len(tested_endpoints),
        "untested_endpoints": sorted(untested_endpoints),
        "total_tools": len(manifest.tools),
        "total_task_types": len(manifest.task_types),
        "total_skills": len(manifest.skills),
        "total_views": len(manifest.frontend_views),
        "total_channels": len(manifest.channels),
        "coverage_pct": (
            round(len(tested_endpoints) / len(endpoint_paths) * 100, 1)
            if endpoint_paths else 0
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agent42 E2E Test Runner")
    parser.add_argument("--suite", help="Run a specific suite (ui, api, harness, coding)")
    parser.add_argument("--discover", action="store_true", help="Show codebase manifest")
    parser.add_argument("--coverage", action="store_true", help="Show coverage gaps")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--url", help="Override base URL")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    if args.headed:
        config.headed = True
    if args.url:
        config.base_url = args.url

    # Build manifest
    manifest = build_manifest()

    if args.discover:
        print("=== Agent42 Codebase Manifest ===\n")
        print(f"Endpoints:  {len(manifest.endpoints)}")
        for e in manifest.endpoints:
            auth = " [auth]" if e.auth_required else " [public]"
            print(f"  {e.method:6s} {e.path}{auth}")
        print(f"\nTools:      {len(manifest.tools)}")
        for t in manifest.tools:
            print(f"  {t.name} ({t.class_name}) — {t.file}")
        print(f"\nTask Types: {len(manifest.task_types)}")
        for tt in manifest.task_types:
            print(f"  {tt}")
        print(f"\nSkills:     {len(manifest.skills)}")
        for s in manifest.skills:
            print(f"  {s}")
        print(f"\nViews:      {len(manifest.frontend_views)}")
        for v in manifest.frontend_views:
            print(f"  {v}")
        print(f"\nChannels:   {len(manifest.channels)}")
        for c in manifest.channels:
            print(f"  {c}")
        return

    # Import suites to trigger registration
    from . import suite_ui  # noqa: F401
    from . import suite_api  # noqa: F401
    from . import suite_harness  # noqa: F401
    from . import suite_coding  # noqa: F401

    # Select suites
    if args.suite:
        if args.suite not in _SUITES:
            print(f"Unknown suite: {args.suite}. Available: {', '.join(_SUITES)}")
            sys.exit(1)
        suites_to_run = {args.suite: _SUITES[args.suite]}
    else:
        suites_to_run = _SUITES

    # Run
    all_results: list[TestResult] = []
    print(f"{'='*60}")
    print(f"Agent42 E2E Tests — {datetime.now(timezone.utc).isoformat()}")
    print(f"Target: {config.base_url}")
    print(f"Suites: {', '.join(suites_to_run)}")
    print(f"Manifest: {len(manifest.endpoints)} endpoints, "
          f"{len(manifest.tools)} tools, {len(manifest.task_types)} task types")
    print(f"{'='*60}\n")

    for suite_name, suite_cls in suites_to_run.items():
        print(f"--- Suite: {suite_name} ---")
        suite = suite_cls()
        results = suite.run_all()
        all_results.extend(results)
        for r in results:
            status = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
            icon = {"PASS": "+", "SKIP": "~", "FAIL": "!"}[status]
            print(f"  [{icon}] {r.name} ({r.duration:.1f}s)")
            if r.error and not r.skipped:
                for line in r.error.split("\n")[:5]:
                    print(f"      {line}")
        print()

    # Summary
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed and not r.skipped)
    skipped = sum(1 for r in all_results if r.skipped)
    total = len(all_results)

    print(f"{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")

    # Coverage
    coverage = compute_coverage(all_results, manifest)
    print(f"API Coverage: {coverage['tested_endpoints']}/{coverage['total_endpoints']} "
          f"endpoints ({coverage['coverage_pct']}%)")
    if coverage["untested_endpoints"] and (args.coverage or not args.json):
        print(f"\nUntested endpoints ({len(coverage['untested_endpoints'])}):")
        for ep in coverage["untested_endpoints"][:20]:
            print(f"  - {ep}")
        if len(coverage["untested_endpoints"]) > 20:
            print(f"  ... and {len(coverage['untested_endpoints']) - 20} more")
    print(f"{'='*60}")

    # Save results
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": config.base_url,
        "summary": {"total": total, "passed": passed, "failed": failed, "skipped": skipped},
        "coverage": coverage,
        "manifest_snapshot": {
            "endpoints": len(manifest.endpoints),
            "tools": len(manifest.tools),
            "task_types": len(manifest.task_types),
            "skills": len(manifest.skills),
            "views": len(manifest.frontend_views),
        },
        "results": [
            {
                "name": r.name,
                "suite": r.suite,
                "passed": r.passed,
                "skipped": r.skipped,
                "error": r.error,
                "duration": round(r.duration, 2),
                "covers": r.covers,
            }
            for r in all_results
        ],
    }

    report_path = Path(config.output_dir) / f"e2e-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport saved: {report_path}")

    if args.json:
        print(json.dumps(report, indent=2))

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
