#!/usr/bin/env bash
# audit-code-secrets.sh — scan local pour secrets oubliés dans le repo
#
# Wrapper gitleaks + regex custom (clés API, tokens, passwords typiques).
# Complète gitleaks par des patterns spécifiques aux usages probables
# de HedgeX (Stripe, OpenAI, Anthropic, Hetzner, Supabase, Tuta…).
#
# Usage : ./scripts/audit-code-secrets.sh           # scan tout l'historique
#         ./scripts/audit-code-secrets.sh --staged  # scan staged uniquement
#         ./scripts/audit-code-secrets.sh --quiet   # silencieux si OK

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

R=$'\033[0;31m'; G=$'\033[0;32m'; Y=$'\033[1;33m'; B=$'\033[0;34m'; X=$'\033[0m'

MODE="full"
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --staged) MODE="staged" ;;
    --quiet) QUIET=1 ;;
    --help|-h)
      cat <<EOF
Usage : $0 [--staged] [--quiet] [--help]

Scan le repo (ou seulement les modifs staged) pour secrets oubliés.

Combine :
  - gitleaks detect (full history) ou gitleaks protect --staged
  - Regex custom : Stripe, OpenAI, Anthropic, Hetzner, Supabase, etc.

Code retour :
  0 = aucun secret détecté
  1 = secrets trouvés (à corriger)
EOF
      exit 0
      ;;
  esac
done

ERRORS=0

[[ $QUIET -eq 0 ]] && echo "${B}━━━ audit-code-secrets ($MODE) ━━━${X}"

# ─── 1. gitleaks ────────────────────────────────────────────────────
if ! command -v gitleaks &>/dev/null; then
  echo "${R}❌ gitleaks non installé. sudo dnf install gitleaks${X}"
  exit 1
fi

if [[ "$MODE" == "staged" ]]; then
  if gitleaks protect --staged --no-banner --redact 2>&1; then
    [[ $QUIET -eq 0 ]] && echo "${G}✅ gitleaks (staged) : aucun secret${X}"
  else
    echo "${R}❌ gitleaks a détecté un secret dans les modifs staged${X}"
    ERRORS=$((ERRORS+1))
  fi
else
  if gitleaks detect --no-banner --redact 2>&1 | grep -v "no leaks found\|no leaks present\|^$" | head -50; then
    : # output already shown
  fi
  if gitleaks detect --no-banner --redact &>/dev/null; then
    [[ $QUIET -eq 0 ]] && echo "${G}✅ gitleaks (full) : aucun secret${X}"
  else
    echo "${R}❌ gitleaks a détecté des secrets (voir output ci-dessus)${X}"
    ERRORS=$((ERRORS+1))
  fi
fi

# ─── 2. Regex custom — patterns spécifiques HedgeX ──────────────────
[[ $QUIET -eq 0 ]] && echo
[[ $QUIET -eq 0 ]] && echo "${B}─── Scan regex custom ───${X}"

# Patterns suspects
declare -A PATTERNS=(
  ["OpenAI API"]='sk-[A-Za-z0-9]{32,}'
  ["Anthropic API"]='sk-ant-[A-Za-z0-9_-]{20,}'
  ["Stripe live key"]='sk_live_[A-Za-z0-9]{20,}'
  ["Stripe test key"]='sk_test_[A-Za-z0-9]{20,}'
  ["GitHub PAT"]='ghp_[A-Za-z0-9]{30,}'
  ["GitHub fine-grained"]='github_pat_[A-Za-z0-9_]{50,}'
  ["AWS Access Key"]='AKIA[A-Z0-9]{16}'
  ["Slack token"]='xox[baprs]-[A-Za-z0-9-]{10,}'
  # ["Hetzner Cloud API"]='[a-zA-Z0-9]{64}' — retiré (faux positifs SHA-256 / package-lock)
  # Hetzner détectable via gitleaks (règle contextuelle hcloud / HCLOUD_TOKEN)
  ["Supabase service key"]='eyJhbGciOiJIUzI1NiI[A-Za-z0-9._-]{100,}'  # JWT-like
  ["Private key PEM"]='-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----'
)

# Fichiers à scanner (exclude gitignored, .git, node_modules)
FILES=$(git ls-files | grep -vE '^(node_modules|\.git/|tâches/|html2pdf|tailwind\.css)' || true)

CUSTOM_FOUND=0
for label in "${!PATTERNS[@]}"; do
  pattern="${PATTERNS[$label]}"
  matches=$(echo "$FILES" | xargs -d '\n' grep -lE "$pattern" 2>/dev/null || true)
  if [[ -n "$matches" ]]; then
    echo "${R}❌ $label détecté dans :${X}"
    echo "$matches" | sed 's/^/   /'
    CUSTOM_FOUND=1
  fi
done

if [[ $CUSTOM_FOUND -eq 0 ]]; then
  [[ $QUIET -eq 0 ]] && echo "${G}✅ Regex custom : aucun pattern suspect${X}"
else
  ERRORS=$((ERRORS+CUSTOM_FOUND))
fi

# ─── 3. Fichiers sensibles oubliés ──────────────────────────────────
[[ $QUIET -eq 0 ]] && echo
[[ $QUIET -eq 0 ]] && echo "${B}─── Scan fichiers sensibles ───${X}"

SENSITIVE_PATTERNS=(
  "*.pem"
  "*.key"
  "*.p12"
  "*.pfx"
  ".env"
  ".env.local"
  ".env.production"
  "id_rsa"
  "id_ed25519"
  "credentials.json"
  "config.json"
)

SENSITIVE_FOUND=0
for pat in "${SENSITIVE_PATTERNS[@]}"; do
  tracked=$(git ls-files "$pat" 2>/dev/null || true)
  if [[ -n "$tracked" ]]; then
    echo "${R}❌ Fichier sensible tracké : $tracked${X}"
    SENSITIVE_FOUND=1
    ERRORS=$((ERRORS+1))
  fi
done

if [[ $SENSITIVE_FOUND -eq 0 ]]; then
  [[ $QUIET -eq 0 ]] && echo "${G}✅ Aucun fichier sensible tracké${X}"
fi

# ─── Conclusion ─────────────────────────────────────────────────────
[[ $QUIET -eq 0 ]] && echo "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
if [[ $ERRORS -gt 0 ]]; then
  echo "${R}❌ $ERRORS catégorie(s) en erreur${X}"
  exit 1
fi
[[ $QUIET -eq 0 ]] && echo "${G}✅ Aucun secret détecté${X}"
exit 0
