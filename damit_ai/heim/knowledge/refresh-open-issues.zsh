#!/usr/bin/env zsh
# refresh-open-issues.zsh — snapshot the open GitHub issues of the suite repos into
# OPEN-ISSUES.md, so Heim can see the current known-bug list (the RAG never reads GitHub).
#
#   ./refresh-open-issues.zsh                 # default repos below
#   ./refresh-open-issues.zsh owner/repo ...  # explicit repo list
#
# Needs the `gh` CLI, authenticated. Writes OPEN-ISSUES.md next to this script.
set -e
HERE=${0:A:h}
OUT="$HERE/OPEN-ISSUES.md"
REPOS=(${@:-nickdbendickson/DWR_Plugins nickdbendickson/crest nickdbendickson/damit})

{
  echo "# Open issues (snapshot)"
  echo
  echo "_Generated $(date -u +%Y-%m-%dT%H:%MZ) by refresh-open-issues.zsh. Re-run to refresh._"
  echo
  for repo in $REPOS; do
    echo "## $repo"
    echo
    # issues only (exclude PRs); title + labels + first line of the body
    gh issue list --repo "$repo" --state open --limit 100 \
       --json number,title,labels,body 2>/dev/null \
    | python3 -c '
import json,sys
rows=json.load(sys.stdin)
if not rows:
    print("_No open issues._\n"); sys.exit()
for r in rows:
    labs=",".join(l["name"] for l in r.get("labels",[]))
    first=(r.get("body") or "").strip().splitlines()
    first=first[0] if first else ""
    tag=f" [{labs}]" if labs else ""
    print(f"- #{r[\"number\"]} {r[\"title\"]}{tag}")
    if first:
        print(f"    {first[:300]}")
print()
' || echo "_(could not read $repo — is it attached / accessible?)_\n"
  done
} > "$OUT"
echo "Wrote $OUT"
