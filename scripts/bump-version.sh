#!/usr/bin/env bash
# bump-version.sh — bumpe <title> index.html ET CACHE_VERSION sw.js ensemble
#
# Élimine la cause #1 des régressions cache utilisateur en V2 :
# bumper le title sans bumper sw.js → cache SW invalidé, utilisateurs
# coincés sur l'ancienne version.
#
# Usage : ./scripts/bump-version.sh
#         ./scripts/bump-version.sh --auto patch   # non-interactif
#         ./scripts/bump-version.sh --auto minor
#         ./scripts/bump-version.sh --auto major
#         ./scripts/bump-version.sh --help

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INDEX="$REPO_ROOT/index.html"
SW="$REPO_ROOT/sw.js"

# Couleurs
R=$'\033[0;31m'; G=$'\033[0;32m'; Y=$'\033[1;33m'; B=$'\033[0;34m'; X=$'\033[0m'

# --help ?
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<EOF
Usage : $0 [--auto {patch|minor|major}]

Bumpe la version dans :
  - <title>Menu IG Bas — VX.Y.Z</title>     (index.html)
  - const CACHE_VERSION = "menu-ig-bas-vX.Y.Z";   (sw.js)

Sans --auto : menu interactif.
Avec --auto patch|minor|major : non-interactif.

Le script git-add les 2 fichiers à la fin (commit à faire manuellement).
EOF
  exit 0
fi

# Sanity check fichiers
[[ ! -f "$INDEX" ]] && { echo "${R}❌ index.html introuvable${X}"; exit 1; }
[[ ! -f "$SW" ]]    && { echo "${R}❌ sw.js introuvable${X}"; exit 1; }

# Extraction version courante
CURRENT_TITLE=$(grep -oE '<title>Menu IG Bas — V[0-9]+\.[0-9]+\.[0-9]+</title>' "$INDEX" | grep -oE 'V[0-9]+\.[0-9]+\.[0-9]+')
CURRENT_CACHE=$(grep -oE 'CACHE_VERSION = "menu-ig-bas-v[0-9]+\.[0-9]+\.[0-9]+"' "$SW" | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+')

if [[ -z "$CURRENT_TITLE" ]]; then
  echo "${R}❌ Impossible de parser la version dans <title> de index.html${X}"
  exit 1
fi
if [[ -z "$CURRENT_CACHE" ]]; then
  echo "${R}❌ Impossible de parser CACHE_VERSION dans sw.js${X}"
  exit 1
fi

# Comparaison title vs cache (warning si désynchro déjà)
TITLE_NUM="${CURRENT_TITLE#V}"
CACHE_NUM="${CURRENT_CACHE#v}"

echo "${B}État actuel :${X}"
echo "  index.html title : $CURRENT_TITLE"
echo "  sw.js cache_ver  : $CURRENT_CACHE"

if [[ "$TITLE_NUM" != "$CACHE_NUM" ]]; then
  echo "${Y}⚠️  Désynchronisation détectée. On va aligner sur la plus haute.${X}"
fi

# Détermine la version de base (la plus haute des 2 en cas de désync)
IFS='.' read -r T_MAJOR T_MINOR T_PATCH <<< "$TITLE_NUM"
IFS='.' read -r C_MAJOR C_MINOR C_PATCH <<< "$CACHE_NUM"

# Comparaison naïve (suffit pour notre cas)
if [[ "$TITLE_NUM" > "$CACHE_NUM" ]]; then
  BASE_MAJOR=$T_MAJOR; BASE_MINOR=$T_MINOR; BASE_PATCH=$T_PATCH
else
  BASE_MAJOR=$C_MAJOR; BASE_MINOR=$C_MINOR; BASE_PATCH=$C_PATCH
fi

BASE_VERSION="$BASE_MAJOR.$BASE_MINOR.$BASE_PATCH"
echo "  Base de bump     : $BASE_VERSION"
echo

# Mode auto ou interactif ?
if [[ "${1:-}" == "--auto" ]]; then
  CHOICE="$2"
else
  echo "${B}Type de bump ?${X}"
  echo "  [1] patch  ($BASE_VERSION → $BASE_MAJOR.$BASE_MINOR.$((BASE_PATCH+1)))"
  echo "  [2] minor  ($BASE_VERSION → $BASE_MAJOR.$((BASE_MINOR+1)).0)"
  echo "  [3] major  ($BASE_VERSION → $((BASE_MAJOR+1)).0.0)"
  echo "  [q] quit"
  read -p "Choix : " choice_input

  case "$choice_input" in
    1|patch) CHOICE="patch" ;;
    2|minor) CHOICE="minor" ;;
    3|major) CHOICE="major" ;;
    q|Q) echo "Annulé."; exit 0 ;;
    *) echo "${R}❌ Choix invalide${X}"; exit 1 ;;
  esac
fi

# Calcul nouvelle version
case "$CHOICE" in
  patch) NEW_MAJOR=$BASE_MAJOR; NEW_MINOR=$BASE_MINOR; NEW_PATCH=$((BASE_PATCH+1)) ;;
  minor) NEW_MAJOR=$BASE_MAJOR; NEW_MINOR=$((BASE_MINOR+1)); NEW_PATCH=0 ;;
  major) NEW_MAJOR=$((BASE_MAJOR+1)); NEW_MINOR=0; NEW_PATCH=0 ;;
  *) echo "${R}❌ Type invalide : $CHOICE${X}"; exit 1 ;;
esac

NEW_VERSION="$NEW_MAJOR.$NEW_MINOR.$NEW_PATCH"
NEW_TITLE="V$NEW_VERSION"
NEW_CACHE="v$NEW_VERSION"

echo
echo "${B}Bump $CHOICE → $NEW_VERSION${X}"

# Remplacement index.html
sed -i "s|<title>Menu IG Bas — V[0-9]\+\.[0-9]\+\.[0-9]\+</title>|<title>Menu IG Bas — $NEW_TITLE</title>|" "$INDEX"

# Remplacement sw.js
sed -i "s|CACHE_VERSION = \"menu-ig-bas-v[0-9]\+\.[0-9]\+\.[0-9]\+\"|CACHE_VERSION = \"menu-ig-bas-$NEW_CACHE\"|" "$SW"

# Vérification post-sed
NEW_TITLE_CHECK=$(grep -oE '<title>Menu IG Bas — V[0-9]+\.[0-9]+\.[0-9]+</title>' "$INDEX" | grep -oE 'V[0-9]+\.[0-9]+\.[0-9]+')
NEW_CACHE_CHECK=$(grep -oE 'CACHE_VERSION = "menu-ig-bas-v[0-9]+\.[0-9]+\.[0-9]+"' "$SW" | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+')

if [[ "$NEW_TITLE_CHECK" != "$NEW_TITLE" ]]; then
  echo "${R}❌ Échec sed sur index.html (title = $NEW_TITLE_CHECK)${X}"
  exit 1
fi
if [[ "$NEW_CACHE_CHECK" != "$NEW_CACHE" ]]; then
  echo "${R}❌ Échec sed sur sw.js (cache = $NEW_CACHE_CHECK)${X}"
  exit 1
fi

echo "${G}✅ index.html : $NEW_TITLE${X}"
echo "${G}✅ sw.js      : $NEW_CACHE${X}"

# Git add
git -C "$REPO_ROOT" add index.html sw.js
echo "${G}✅ git add index.html sw.js${X}"
echo
echo "${B}Prochaines étapes :${X}"
echo "  1. Modifier les fichiers de la release (recettes, code, FAQ…)"
echo "  2. git add <fichiers>"
echo "  3. git commit -m \"$NEW_TITLE — <message>\""
