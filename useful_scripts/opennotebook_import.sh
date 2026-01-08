#!/usr/bin/env bash
# opennotebook_import.sh
# Upload all PDFs in a directory to an Open Notebook server into a target notebook.
# - Supports dry-run
# - Handles duplicates by appending _1 to the "title" sent to the API and listing them at the end
# - Reports HTTP errors and exit codes
#
# Requirements: curl; jq (preferred) or python3 for JSON parsing fallback
#
# Example:
#   ./opennotebook_import.sh -server=http://100.77.164.86:5005 -notebook=service_kb_new -dir="/path/to/PDF" -dry-run

set -u -o pipefail

SCRIPT_NAME=$(basename "$0")
VERSION="1.0.0"

# Defaults
SERVER="http://100.77.164.86:5005"
NOTEBOOK_NAME="service_kb_new"
SCAN_DIR="."
DRY_RUN=0
EMBED="true"
ASYNC="true"
RECURSIVE=0
TOKEN="${OPEN_NOTEBOOK_TOKEN:-}"
TIMEOUT=30

# Globals for reporting
declare -a FILES_PROCESSED=()
declare -a FILES_SUCCESS=()
declare -a FILES_ERRORS=()
declare -a FILES_DUPLICATES=()

# Utility: print usage
usage() {
  cat <<EOF
${SCRIPT_NAME} v${VERSION}
Upload all PDFs in a directory to an Open Notebook notebook via API.

Flags:
  -server=URL           Open Notebook API base (default: ${SERVER})
  -notebook=NAME        Notebook name to upload into (default: ${NOTEBOOK_NAME})
  -dir=PATH             Directory to scan (default: current directory)
  -dry-run              Show what would be uploaded, do not POST
  -embed=true|false     Ask server to embed content (default: ${EMBED})
  -async=true|false     Process asynchronously on server (default: ${ASYNC})
  -recursive            Recurse into subdirectories (default: off)
  -token=TOKEN          Bearer token if your API is protected (defaults to OPEN_NOTEBOOK_TOKEN env)
  -timeout=SECONDS      HTTP timeout for API calls (default: ${TIMEOUT})
  -h|-help|--help       Show help

Notes:
- Base URL should NOT include /api. This script adds endpoint paths.
- Duplicates (same base name as an existing or earlier file) are sent with a title suffixed by _1 and reported at the end.
EOF
}

# Parse CLI args
for arg in "$@"; do
  case $arg in
    -server=*) SERVER="${arg#*=}" ;;
    -notebook=*) NOTEBOOK_NAME="${arg#*=}" ;;
    -dir=*) SCAN_DIR="${arg#*=}" ;;
    -dry-run) DRY_RUN=1 ;;
    -embed=*) EMBED="${arg#*=}" ;;
    -async=*) ASYNC="${arg#*=}" ;;
    -recursive) RECURSIVE=1 ;;
    -token=*) TOKEN="${arg#*=}" ;;
    -timeout=*) TIMEOUT="${arg#*=}" ;;
    -h|-help|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 2 ;;
  esac
done

# Normalize server: prepend http:// if missing scheme
if [[ ! "$SERVER" =~ ^https?:// ]]; then
  SERVER="http://${SERVER}"
fi

API_BASE="${SERVER%/}/api"

# Detect parser: jq or python
have_jq() { command -v jq >/dev/null 2>&1; }
have_python() { command -v python3 >/dev/null 2>&1; }

json_get_notebook_id_by_name() {
  local json="$1" name="$2"
  if have_jq; then
    echo "$json" | jq -r --arg n "$name" '.[] | select(.name==$n) | .id' | head -n1
  elif have_python; then
    python3 - "$name" <<'PY'
import json,sys
name=sys.argv[1]
try:
  data=json.load(sys.stdin)
except Exception:
  sys.exit(1)
for item in data if isinstance(data,list) else []:
  if item.get('name')==name:
    print(item.get('id',''))
    sys.exit(0)
PY
  else
    echo "" # no parser
  fi
}

json_get_source_titles_for_notebook() {
  local json="$1"
  if have_jq; then
    echo "$json" | jq -r '.[] | .title // empty'
  elif have_python; then
    python3 - <<'PY'
import json,sys
try:
  data=json.load(sys.stdin)
except Exception:
  sys.exit(0)
if isinstance(data,list):
  for it in data:
    t=it.get('title')
    if t:
      print(t)
PY
  else
    :
  fi
}

# HTTP helpers
build_auth_header() {
  if [[ -n "$TOKEN" ]]; then
    echo "Authorization: Bearer ${TOKEN}"
  fi
}

curl_json() {
  local url="$1"; shift
  local auth
  auth=$(build_auth_header)
  if [[ -n "$auth" ]]; then
    curl -sS --fail --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" -H "$auth" -H 'Accept: application/json' "$url" "$@"
  else
    curl -sS --fail --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" -H 'Accept: application/json' "$url" "$@"
  fi
}

# Resolve notebook ID
NOTEBOOK_ID=""
resolve_notebook_id() {
  local url="${API_BASE}/notebooks?limit=1000"
  local body
  if ! body=$(curl_json "$url"); then
    echo "Warning: could not query notebooks at $url. Proceeding without server-side duplicate checks." >&2
    return 1
  fi
  NOTEBOOK_ID=$(json_get_notebook_id_by_name "$body" "$NOTEBOOK_NAME" || true)
  if [[ -z "$NOTEBOOK_ID" ]]; then
    echo "Error: Notebook named '$NOTEBOOK_NAME' not found on server $SERVER" >&2
    return 2
  fi
  return 0
}

# Get existing titles for duplicate detection
EXISTING_TITLES=()
fetch_existing_titles() {
  [[ -z "$NOTEBOOK_ID" ]] && return 0
  local url="${API_BASE}/sources?notebook_id=${NOTEBOOK_ID}&limit=10000"
  local body
  if ! body=$(curl_json "$url"); then
    echo "Warning: could not list existing sources at $url" >&2
    return 0
  fi
  mapfile -t EXISTING_TITLES < <(json_get_source_titles_for_notebook "$body")
}

is_in_array() {
  local needle="$1"; shift
  local s
  for s in "$@"; do [[ "$s" == "$needle" ]] && return 0; done
  return 1
}

# Discover PDF files
collect_pdfs() {
  local dir="$1"
  if [[ $RECURSIVE -eq 1 ]]; then
    find "$dir" -type f -iname "*.pdf" | sort -V
  else
    find "$dir" -maxdepth 1 -type f -iname "*.pdf" | sort -V
  fi
}

# Main upload logic
process_file() {
  local file_path="$1"
  local base fname title final_title
  FILES_PROCESSED+=("$file_path")
  fname=$(basename "$file_path")
  base="${fname%.pdf}"
  title="$base"

  # Duplicate detection: within batch and vs server existing titles
  # Maintain a local map of seen titles
  if [[ -z "${SEEN_TITLES[*]:-}" ]]; then declare -gA SEEN_TITLES=(); fi

  local need_suffix=0
  if is_in_array "$title" "${EXISTING_TITLES[@]:-}"; then need_suffix=1; fi
  if [[ -n "${SEEN_TITLES[$title]:-}" ]]; then need_suffix=1; fi

  if [[ $need_suffix -eq 1 ]]; then
    final_title="${title}_1"
    FILES_DUPLICATES+=("$fname -> ${final_title}.pdf")
  else
    final_title="$title"
  fi
  SEEN_TITLES["$final_title"]=1

  if [[ $DRY_RUN -eq 1 ]]; then
    printf "DRY-RUN: would upload '%s' to notebook '%s' (id: %s) with title '%s' embed=%s async=%s\n" \
      "$file_path" "$NOTEBOOK_NAME" "${NOTEBOOK_ID:-?}" "$final_title" "$EMBED" "$ASYNC"
    return 0
  fi

  # Real upload
  local url="${API_BASE}/sources"
  local auth
  auth=$(build_auth_header)

  # Build curl -F call
  local http_code output
  # We want status code and body; use -w and capture
  if [[ -n "$auth" ]]; then
    output=$(curl -sS -o /tmp/resp.$$ -w "%{http_code}" --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" \
      -H "$auth" -F type=upload -F "notebooks=[\"${NOTEBOOK_ID}\"]" \
      -F "title=${final_title}" -F "embed=${EMBED}" -F "async_processing=${ASYNC}" \
      -F "file=@${file_path};type=application/pdf" "${url}" 2>/tmp/err.$$ || true)
  else
    output=$(curl -sS -o /tmp/resp.$$ -w "%{http_code}" --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" \
      -F type=upload -F "notebooks=[\"${NOTEBOOK_ID}\"]" \
      -F "title=${final_title}" -F "embed=${EMBED}" -F "async_processing=${ASYNC}" \
      -F "file=@${file_path};type=application/pdf" "${url}" 2>/tmp/err.$$ || true)
  fi
  http_code="$output"
  if [[ "$http_code" =~ ^2 ]]; then
    FILES_SUCCESS+=("$fname (${http_code})")
  else
    local err_body err_stderr
    err_body=$(cat /tmp/resp.$$ 2>/dev/null || true)
    err_stderr=$(cat /tmp/err.$$ 2>/dev/null || true)
    FILES_ERRORS+=("$fname -> HTTP ${http_code} | ${err_body:-$err_stderr}")
  fi
  rm -f /tmp/resp.$$ /tmp/err.$$ || true
}

main() {
  # Resolve notebook/server state for better reporting; allow continuing if unreachable in dry-run
  if ! resolve_notebook_id; then
    if [[ $DRY_RUN -ne 1 ]]; then
      echo "Fatal: cannot resolve notebook id; aborting." >&2
      exit 1
    fi
  else
    fetch_existing_titles || true
  fi

  local list_cmd=(collect_pdfs "$SCAN_DIR")
  mapfile -t pdfs < <("${list_cmd[@]}")
  if [[ ${#pdfs[@]} -eq 0 ]]; then
    echo "No PDF files found in ${SCAN_DIR}" >&2
    exit 0
  fi

  local f
  for f in "${pdfs[@]}"; do
    process_file "$f"
  done

  echo "\nSummary"
  echo "  Server: $SERVER"
  echo "  API base: $API_BASE"
  echo "  Notebook: ${NOTEBOOK_NAME} (id: ${NOTEBOOK_ID:-unknown})"
  echo "  Directory: ${SCAN_DIR}"
  echo "  Dry-run: $DRY_RUN"
  echo "  Files discovered: ${#pdfs[@]}"
  echo "  Success: ${#FILES_SUCCESS[@]}"
  echo "  Errors: ${#FILES_ERRORS[@]}"
  echo "  Duplicates renamed: ${#FILES_DUPLICATES[@]}"

  if [[ ${#FILES_ERRORS[@]} -gt 0 ]]; then
    echo "\nErrors:"
    printf '  - %s\n' "${FILES_ERRORS[@]}"
  fi
  if [[ ${#FILES_DUPLICATES[@]} -gt 0 ]]; then
    echo "\nDuplicates (title suffixes applied):"
    printf '  - %s\n' "${FILES_DUPLICATES[@]}"
  fi
}

main "$@"
