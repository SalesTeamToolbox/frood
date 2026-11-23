#!/usr/bin/env bash
# Enable GitHub secret scanning + push protection on a repo.
#   github-harden.sh <owner/repo>           apply, then print the resulting state
#   github-harden.sh --check <owner/repo>   read-only
set -euo pipefail

check=0
if [ "${1:-}" = "--check" ]; then check=1; shift; fi
repo="${1:-}"
if ! [[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "usage: github-harden.sh [--check] <owner/repo>" >&2
  exit 2
fi

if [ "$check" -eq 0 ]; then
  gh api -X PATCH "repos/$repo" \
    -f 'security_and_analysis[secret_scanning][status]=enabled' \
    -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled' >/dev/null
fi

state="$(gh api "repos/$repo" --jq '.security_and_analysis | {secret_scanning: .secret_scanning.status, push_protection: .secret_scanning_push_protection.status}')"
echo "$repo: $state"
if [ "$check" -eq 1 ] && ! grep -q '"secret_scanning":"enabled"' <<<"$state"; then exit 1; fi
if [ "$check" -eq 1 ] && ! grep -q '"push_protection":"enabled"' <<<"$state"; then exit 1; fi
exit 0
