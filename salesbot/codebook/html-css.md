# HTML and CSS
## Rules
- Start with `<!doctype html>`, `<html lang="en">`, `<meta charset="utf-8">`, `<meta name="viewport" content="width=device-width,initial-scale=1">`.
- Semantic tags: header, nav, main, section, article, footer, button (not clickable divs), label for every input.
- Mobile-first CSS; use flexbox for rows, grid for 2D layouts. Relative units (rem, %, fr). Contrast at least 4.5:1.
- CSS variables for colors on `:root`; dark mode with `@media (prefers-color-scheme: dark)`.
## Template
```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>App</title>
<style>
  :root { --ink: #18212b; --bg: #f7f5f0; --accent: #d2551f; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.5 system-ui, sans-serif; color: var(--ink); background: var(--bg); }
  main { max-width: 720px; margin: 0 auto; padding: 16px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
  button { font: inherit; padding: 10px 14px; border-radius: 8px; border: 0; background: var(--accent); color: #fff; }
  input { font: inherit; padding: 10px; border: 1px solid #ccc; border-radius: 8px; width: 100%; }
</style></head>
<body><main>
  <h1>Title</h1>
  <form id="form" class="row"><label for="q">Search</label><input id="q" name="q" required><button>Go</button></form>
  <div id="out" class="grid"></div>
</main><script>/* JS here */</script></body></html>
```
Centering: `display:grid; place-items:center`. Sticky header: `position:sticky; top:0`. Truncate: `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`.
## Pitfalls
- Missing viewport meta = tiny text on phones. Images need `alt` and `max-width:100%`.
- `z-index` only works on positioned elements. Margins collapse vertically; use gap/padding.
