# Bash / shell
## Rules
- Start with `#!/usr/bin/env bash` and `set -euo pipefail`.
- Quote every variable: `"$var"`, `"$@"`. Use `[[ ... ]]` for tests, `$(...)` not backticks.
- Check commands exist: `command -v jq >/dev/null || { echo "need jq" >&2; exit 1; }`.
## Template
```bash
#!/usr/bin/env bash
set -euo pipefail
usage() { echo "usage: $0 -i INPUT [-o OUTPUT]" >&2; exit 2; }
in="" out="out.txt"
while getopts "i:o:h" opt; do
  case "$opt" in i) in="$OPTARG";; o) out="$OPTARG";; *) usage;; esac
done
[[ -n "$in" && -f "$in" ]] || usage
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  printf '%s\n' "${line^^}" >>"$tmp"
done <"$in"
mv "$tmp" "$out"
echo "wrote $out"
```
Loops: `for f in *.log; do ...; done`. Arithmetic: `$(( a + b ))`. Defaults: `${VAR:-default}`.
JSON: `curl -fsS "$url" | jq -r '.items[].name'`. Cron: `crontab -e`, `*/15 * * * * /path/script.sh >>/var/log/x.log 2>&1`.
## Pitfalls
- Spaces around `=` break assignment (`a = 1` is wrong). `[ $x = y ]` breaks when x is empty: quote it.
- Pipes hide failures without `pipefail`. `cd` can fail: `cd dir || exit 1`. Never `rm -rf "$dir/"` with an unchecked var.
