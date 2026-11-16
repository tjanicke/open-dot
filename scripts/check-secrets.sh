#!/usr/bin/env bash
# Quick local check for things that must never be published: keys, tokens, passwords,
# private keys, .env files and licensed PDFs. Run before every push:
#   bash scripts/check-secrets.sh
# Or install as a pre-commit hook (runs on staged files automatically):
#   ln -s ../../scripts/check-secrets.sh .git/hooks/pre-commit
# Matches are shown cut short so a real secret is not printed in full.
set -u
if [ "${GIT_INDEX_FILE:-}" != "" ] || [ "$(basename "$0")" = "pre-commit" ]; then
  mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM)
elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t FILES < <(git ls-files --cached --others --exclude-standard)
else
  mapfile -t FILES < <(find . -type f -not -path './.git/*')
fi

PATTERNS=(
  # key = value assignments
  '(api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|passw(or)?d)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+_.-]{8,}'
  # well-known key formats
  'AKIA[0-9A-Z]{16}'
  'ghp_[A-Za-z0-9]{30,}'
  'github_pat_[A-Za-z0-9_]{30,}'
  'sk-[A-Za-z0-9]{20,}'
  'xox[abpr]-[A-Za-z0-9-]{10,}'
  'AIza[0-9A-Za-z_-]{35}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  # HTTP auth headers with a literal token
  'Authorization[^A-Za-z0-9]{1,6}(Basic|Bearer|ApiKey|Token)[[:space:]]+[A-Za-z0-9+/=_.-]{12,}'
  # nginx header set to a long literal (shared-secret headers)
  'proxy_set_header[[:space:]]+[A-Za-z0-9_-]+[[:space:]]+"?[^"$[:space:];]{20,}'
  # curl config files: user = "name:password" and header = "Name: value"
  '^[[:space:]]*user[[:space:]]*=[[:space:]]*"[^"]+:[^"]{6,}"'
  '^[[:space:]]*header[[:space:]]*=[[:space:]]*"[A-Za-z0-9_-]+:[[:space:]]*[^"$]{16,}"'
  # Elasticsearch API key JSON
  '"encoded"[[:space:]]*:[[:space:]]*"[A-Za-z0-9+/=]{20,}"'
)
# Lines that only read a secret at run time, placeholders, and standard proxy headers
ALLOW='getpass|environ|getenv|input\(|\$\{?[A-Z_]+|CHANGE_ME|proxy_set_header[[:space:]]+(Host|X-Forwarded-[A-Za-z]+|X-Real-IP|Upgrade|Connection)[[:space:]]'

bad=0
for f in "${FILES[@]}"; do
  [ -f "$f" ] || continue
  case "$f" in
    *.env.example) ;;
    *.env|*.env.*|.env) echo "BLOCKED  $f  (.env files hold secrets)"; bad=1 ;;
    *.pdf) echo "BLOCKED  $f  (PDFs may be licensed reference material)"; bad=1 ;;
    *.pem|*.key|*.p12|*.pfx) echo "BLOCKED  $f  (key file)"; bad=1 ;;
  esac
  for p in "${PATTERNS[@]}"; do
    m=$(grep -IEi -e "$p" "$f" 2>/dev/null | grep -viE "$ALLOW" | grep -IEoi -e "$p" | head -3)
    if [ -n "$m" ]; then
      while IFS= read -r x; do echo "FOUND    $f: ${x:0:24}…"; done <<< "$m"
      bad=1
    fi
  done
done
if [ $bad -ne 0 ]; then echo; echo "Possible secrets found. Remove them before committing."; exit 1; fi
echo "No secrets found in ${#FILES[@]} files."
