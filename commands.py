import argparse
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from core.portability import create_backup, create_clone, restore_backup

logger = logging.getLogger("frood")


class CommandHandler(ABC):
    """Abstract base class for command handlers."""

    @abstractmethod
    def run(self, args: argparse.Namespace):
        pass


class BackupCommandHandler(CommandHandler):
    """Handles the 'backup' subcommand."""

    def run(self, args: argparse.Namespace):
        base = str(Path.cwd())
        try:
            path = create_backup(
                base_path=base,
                output_path=args.output,
                include_worktrees=args.include_worktrees,
            )
            print(f"Backup created: {path}")
        except Exception as e:
            logger.error("Backup failed: %s", e)
            print(f"Error: {e}")
            sys.exit(1)


class RestoreCommandHandler(CommandHandler):
    """Handles the 'restore' subcommand."""

    def run(self, args: argparse.Namespace):
        try:
            manifest = restore_backup(
                archive_path=args.archive,
                target_path=args.target,
                skip_secrets=args.skip_secrets,
            )
            print(f"Restored backup to {args.target}")
            print(f"  Archive created: {manifest.created_at}")
            print(f"  Categories: {', '.join(manifest.categories)}")
            print(f"  Files: {manifest.file_count}")
        except Exception as e:
            logger.error("Restore failed: %s", e)
            print(f"Error: {e}")
            sys.exit(1)


class CloneCommandHandler(CommandHandler):
    """Handles the 'clone' subcommand."""

    def run(self, args: argparse.Namespace):
        base = str(Path.cwd())
        try:
            path = create_clone(
                base_path=base,
                output_path=args.output,
                include_skills=args.include_skills,
            )
            print(f"Clone package created: {path}")
            print("  Next steps on the target node:")
            print("  1. Extract the archive")
            print("  2. Rename .env.template to .env and fill in secrets")
            print("  3. Run: bash setup.sh")
        except Exception as e:
            logger.error("Clone failed: %s", e)
            print(f"Error: {e}")
            sys.exit(1)


class CliSetupCommandHandler(CommandHandler):
    """Handles the 'cli-setup' subcommand and its sub-actions.

    Sub-actions (per CMD-01..CMD-09 locked in 01-CONTEXT.md):
      detect          — JSON report of installed CLIs + current wiring state
      claude-code     — wire Frood MCP into ~/.claude/settings.json
      opencode [path] — wire Frood MCP into project opencode.json + AGENTS.md
                        (path optional; overrides manifest auto-detect)
      all             — wire every CLI flagged enabled in manifest
      unwire <cli>    — reverse the wire operation on one CLI

    Idempotency, backup semantics, and byte-identical round-trip guarantees
    live in ``core/cli_setup.py`` (Plan 03). This handler is a thin forwarder
    that dispatches to those functions and renders their return dicts as JSON
    to stdout. Core exceptions bubble up as exit-code 1; missing sub-action or
    missing required args exit 2.
    """

    def run(self, args: argparse.Namespace):
        import json

        from core.cli_setup import (
            OpenCodeSetup,
            detect_all,
            unwire_cli,
            wire_cli,
        )
        from core.user_frood_dir import load_manifest

        action = getattr(args, "cli_setup_action", None)
        if action is None:
            print(
                "Error: sub-action required (detect | claude-code | opencode | all | unwire)",
                file=sys.stderr,
            )
            sys.exit(2)

        try:
            if action == "detect":
                result = detect_all()
                print(json.dumps(result, indent=2, default=str))
            elif action == "claude-code":
                result = wire_cli("claude-code")
                print(json.dumps(result, indent=2, default=str))
            elif action == "opencode":
                manifest = load_manifest()
                project_paths = None
                path_arg = getattr(args, "path", None)
                if path_arg:
                    project_paths = [Path(path_arg)]
                adapter = OpenCodeSetup(project_paths=project_paths, manifest=manifest)
                result = adapter.wire()
                print(json.dumps(result, indent=2, default=str))
            elif action == "all":
                manifest = load_manifest()
                results: dict = {}
                for cli_name, cli_cfg in manifest.get("clis", {}).items():
                    if cli_cfg.get("enabled", False):
                        results[cli_name] = wire_cli(cli_name, manifest=manifest)
                print(json.dumps(results, indent=2, default=str))
            elif action == "unwire":
                cli_name = getattr(args, "cli", None)
                if not cli_name:
                    print(
                        "Error: unwire requires a CLI name (claude-code | opencode)",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                result = unwire_cli(cli_name)
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"Error: unknown sub-action '{action}'", file=sys.stderr)
                sys.exit(2)
        except SystemExit:
            raise
        except Exception as e:
            logger.error("cli-setup %s failed: %s", action, e)
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
