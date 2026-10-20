"""Embed the code book chapters into the MyOps page (artifact/salesbot.html) as a JSON block, so the
claude.ai app and the phone app give coding bots the same knowledge. Run after editing salesbot/codebook."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
page = ROOT / "artifact" / "salesbot.html"
chapters = {p.stem: p.read_text(encoding="utf-8") for p in sorted((ROOT / "salesbot" / "codebook").glob("*.md"))}
blob = json.dumps(chapters, ensure_ascii=False).replace("<", "\\u003c")
block = f'<script type="application/json" id="codebook">{blob}</script>'
html = page.read_text(encoding="utf-8")
if 'id="codebook"' in html:
    html = re.sub(r'<script type="application/json" id="codebook">.*?</script>', lambda _: block, html, count=1, flags=re.S)
else:
    html = html.replace("<script>", block + "\n<script>", 1)
page.write_text(html, encoding="utf-8")
print(f"embedded {len(chapters)} chapters ({len(blob)} chars)")
