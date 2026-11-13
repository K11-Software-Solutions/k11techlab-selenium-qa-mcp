"""Command line: start the MCP server (default) or run heal-ci."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .version import VERSION

USAGE = """k11-selenium-qa-mcp {v}

Usage:
  k11-selenium-qa-mcp                    start the MCP server on stdio
  k11-selenium-qa-mcp heal-ci [options]  heal broken locators and write an audit report
  k11-selenium-qa-mcp --version

heal-ci options:
  --apply                 edit the source (default: dry run, report only)
  --min-confidence N      0..1, default 0.7
  --config PATH           default .qa-mcp/heal.config.json
  --report-dir PATH       default .qa-mcp/heal-report
  --no-verify             do not re-run healed tests (not recommended)

The project is QA_MCP_ROOT or the current directory.
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .server import serve

        serve()
        return 0
    if argv[0] in ("--version", "-v"):
        print(VERSION)
        return 0
    if argv[0] in ("--help", "-h", "help"):
        print(USAGE.format(v=VERSION))
        return 0
    if argv[0] != "heal-ci":
        print(f"Unknown command: {argv[0]}\n\n" + USAGE.format(v=VERSION), file=sys.stderr)
        return 2

    p = argparse.ArgumentParser(prog="k11-selenium-qa-mcp heal-ci")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--min-confidence", type=float)
    p.add_argument("--config")
    p.add_argument("--report-dir")
    p.add_argument("--no-verify", action="store_true")
    a = p.parse_args(argv[1:])
    if a.min_confidence is not None and not 0 <= a.min_confidence <= 1:
        p.error("--min-confidence must be between 0 and 1")

    from .healci import heal_ci

    root = Path(os.environ.get("QA_MCP_ROOT") or os.getcwd())
    try:
        res = heal_ci(root, apply=a.apply, min_confidence=a.min_confidence, config_path=a.config,
                      report_dir=a.report_dir, verify=not a.no_verify, log=lambda m: print(m, file=sys.stderr))
    except Exception as e:  # noqa: BLE001
        print(f"heal-ci failed: {e}", file=sys.stderr)
        return 1
    c = res["report"]["counts"]
    print(f"healed {c['applied']}, suggested {c['suggested']}, reverted {c['reverted']}, "
          f"needs review {c['needs_review']}, not found {c['not_found']}; report: {res['markdownPath']}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as fh:
            fh.write(f"healed={c['applied']}\nsuggested={c['suggested']}\n"
                     f"report={res['markdownPath']}\nreport_json={res['jsonPath']}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf8") as fh:
            fh.write(Path(res["markdownPath"]).read_text("utf8") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
