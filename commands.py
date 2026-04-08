import argparse
import sys
import logging
from pathlib import Path
from abc import ABC, abstractmethod

from core.portability import create_backup, restore_backup, create_clone

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
