#!/usr/bin/env bash
# Install public-guard for the current user (idempotent).
#   install.sh           copy guard.py + hooks to ~/.config/public-guard, set core.hooksPath
#   install.sh --check   report drift only; exit 1 if anything is out of date
#   install.sh --system  PRINT (do not run) the sudo commands that make the setup root-owned
# Never overwrites an existing denylist.txt.
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$HOME/.config/public-guard"
mode="install"
[ "${1:-}" = "--check" ] && mode="check"
if [ "${1:-}" = "--system" ]; then
  cat <<SYS
# Run these yourself (public-guard never runs sudo). They put the hooks, the git config and the
# private-remotes list where an agent running as your user cannot edit them.
sudo install -d -o root -g root -m 755 /usr/local/lib/public-guard/hooks
sudo install -o root -g root -m 755 "$src/guard.py" /usr/local/lib/public-guard/guard.py
sudo install -o root -g root -m 755 "$src"/hooks/* /usr/local/lib/public-guard/hooks/
sudo git config --system core.hooksPath /usr/local/lib/public-guard/hooks     # writes /etc/gitconfig
sudo install -d -o root -g root -m 755 /etc/public-guard
sudo sh -c 'test -e /etc/public-guard/private-remotes.txt || printf "# Non-GitHub remote URLs that are PRIVATE, one per line\n" > /etc/public-guard/private-remotes.txt'
sudo chown root:root /etc/public-guard/private-remotes.txt && sudo chmod 644 /etc/public-guard/private-remotes.txt
# Per-user data stays in ~/.config/public-guard (denylist.txt, tools.json); run install.sh (no flag) first.
# Unset the per-user setting so only the system one applies:  git config --global --unset core.hooksPath
SYS
  exit 0
fi

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

# Absolute paths of the helper binaries, recorded now so guard.py never searches PATH.
resolve_tool() {
  local name="$1" c
  for c in "/usr/bin/$name" "/usr/local/bin/$name"; do
    if [ -x "$c" ]; then echo "$c"; return 0; fi
  done
  while IFS= read -r c; do
    case "$c" in /tmp/*|/var/tmp/*|/dev/shm/*) continue ;; esac
    if [ -x "$c" ]; then echo "$c"; return 0; fi
  done < <(type -ap "$name" 2>/dev/null)
  return 0
}
gl="$(resolve_tool gitleaks)"
ghp="$(resolve_tool gh)"
tools="$(python3 - "$gl" "$ghp" <<'PY'
import json, sys
print(json.dumps({"gitleaks": sys.argv[1] or None, "gh": sys.argv[2] or None}))
PY
)"
if [ "$mode" = "check" ]; then
  if [ ! -f "$dest/tools.json" ] || [ "$(cat "$dest/tools.json")" != "$tools" ]; then
    need "$dest/tools.json missing or stale (want $tools)"
  fi
else
  mkdir -p "$dest"
  if [ ! -f "$dest/tools.json" ] || [ "$(cat "$dest/tools.json")" != "$tools" ]; then
    printf '%s\n' "$tools" > "$dest/tools.json.tmp"
    chmod 600 "$dest/tools.json.tmp"
    mv "$dest/tools.json.tmp" "$dest/tools.json"
    note "recorded tool paths in $dest/tools.json: $tools"
  fi
fi

if [ "$mode" = "check" ]; then
  if [ "$drift" -eq 0 ]; then note "public-guard: up to date"; else exit 1; fi
fi
