#!/usr/bin/env bash
# Install public-guard for the current user (idempotent).
#   install.sh           copy guard.py + hooks to ~/.config/public-guard, set core.hooksPath
#   install.sh --check   report drift only; exit 1 if anything is out of date
# Never overwrites an existing denylist.txt.
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$HOME/.config/public-guard"
mode="install"
[ "${1:-}" = "--check" ] && mode="check"

drift=0
note() { echo "$*"; }
need() { drift=1; note "DRIFT: $*"; }

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "WARNING: gitleaks is not installed; pushes to public repos will be BLOCKED until you install it." >&2
fi

sync_file() { # <src> <dst> <mode>
  if [ -f "$2" ] && cmp -s "$1" "$2" && [ "$(stat -c %a "$2")" = "$3" ]; then return 0; fi
  if [ "$mode" = "check" ]; then need "$2 differs from $1"; return 0; fi
  mkdir -p "$(dirname "$2")"
  install -m "$3" "$1" "$2"
  note "installed $2"
}

sync_file "$src/guard.py" "$dest/guard.py" 755
for h in "$src"/hooks/*; do
  sync_file "$h" "$dest/hooks/$(basename "$h")" 755
done

want="$dest/hooks"
have="$(git config --global --get core.hooksPath || true)"
if [ "$have" != "$want" ]; then
  if [ "$mode" = "check" ]; then
    need "core.hooksPath is '${have:-<unset>}', want '$want'"
  else
    git config --global core.hooksPath "$want"
    note "set git core.hooksPath=$want"
  fi
fi

user="${USER:-$(id -un)}"
deny="$dest/denylist.txt"
if [ ! -f "$deny" ]; then
  if [ "$mode" = "check" ]; then
    need "$deny is missing"
  else
    mkdir -p "$dest"
    {
      echo "# public-guard private denylist. NEVER commit this file to any repo."
      echo "# One entry per line. '#' starts a comment. Plain entries are case-insensitive literals;"
      echo "# 're:<python regex>' entries are regular expressions."
      echo "# Matched against added lines, commit messages and added file paths of every push to a PUBLIC repo."
      echo "# Add: customer names, private hostnames, internal domains, personal emails, vendor ids."
      echo
      echo "# --- seeded for this machine ---"
      echo "$HOME"
      echo "re:\\b${user}\\b"
      echo "C:\\Users\\${user}"
      echo "C:/Users/${user}"
      echo "C:\\\\Users\\\\${user}"
    } > "$deny"
    chmod 600 "$deny"
    note "created $deny (edit it: add your private names/domains)"
  fi
elif [ "$mode" = "install" ]; then
  chmod 600 "$deny"
fi

pr="$dest/private-remotes.txt"
if [ ! -f "$pr" ] && [ "$mode" = "install" ]; then
  mkdir -p "$dest"
  {
    echo "# Non-GitHub remote URLs (one per line) that are PRIVATE and need no scanning."
    echo "# GitHub remotes are looked up with 'gh api' instead; unknown means public."
  } > "$pr"
fi

if [ "$mode" = "check" ]; then
  if [ "$drift" -eq 0 ]; then note "public-guard: up to date"; else exit 1; fi
fi
