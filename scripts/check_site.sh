#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Verify an assembled GitHub Pages site: every local href/src/url() resolves
# and nothing is loaded from a third party. Usage: scripts/check_site.sh DIR
set -euo pipefail

site="${1:?usage: check_site.sh DIR}"
test -s "${site}/index.html"

status=0
while IFS= read -r ref; do
  [[ -z "${ref}" ]] && continue
  if [[ ! -e "${site}/${ref}" ]]; then
    echo "error: missing ${ref}" >&2
    status=1
  fi
done < <(
  {
    grep -ohE '(href|src)="[^"#:]+"' "${site}"/*.html | sed -E 's/.*="([^"]+)"/\1/'
    grep -ohE 'url\("[^":)]+"\)' "${site}"/*.css | sed -E 's/url\("([^"]+)"\)/\1/'
  } | sort -u
)

if grep -qE 'https?://[^" ]*(googleapis|gstatic|cdnjs|jsdelivr|unpkg|esm\.sh)' \
  "${site}"/*.html "${site}"/*.css "${site}"/*.js; then
  echo "error: the site must not load third-party resources" >&2
  status=1
fi

exit "${status}"
