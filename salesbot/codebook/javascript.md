# JavaScript (ES2020+, browser and Node)
## Rules
- `const` by default, `let` when reassigned, never `var`. `===` not `==`. Semicolons consistently.
- camelCase variables/functions, PascalCase classes. Arrow functions for callbacks.
- Always `await` promises inside `async` functions and wrap with try/catch. `fetch` does not throw on 404: check `res.ok`.
- DOM: `textContent` for text (safe); `innerHTML` only with trusted strings (XSS risk).
## Templates
```js
async function getJson(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

const $ = (sel) => document.querySelector(sel);
function el(tag, props = {}, ...kids) {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...kids.filter((k) => k != null));
  return n;
}

document.addEventListener("DOMContentLoaded", () => {
  $("#form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    try { const out = await getJson("/api/items", { method: "POST", body: JSON.stringify(data) }); render(out); }
    catch (err) { $("#msg").textContent = err.message; }
  });
});
```
Arrays: `map`, `filter`, `reduce`, `find`, `some`, `every`, `sort((a, b) => a - b)` (default sort is text!).
Objects: spread `{...a, b: 1}`, `Object.entries(o)`, optional chaining `a?.b?.c`, nullish `x ?? def`.
Storage: `localStorage.setItem(k, JSON.stringify(v))`; `JSON.parse(localStorage.getItem(k) || "null")` in try/catch.
Node: `import fs from "node:fs/promises"; await fs.readFile(p, "utf8")`; Express `app.get("/", (req, res) => res.json({}))`.
## Pitfalls
- `this` in callbacks: use arrow functions. Floating point: `0.1 + 0.2 !== 0.3`; money in integer cents.
- `parseInt(x, 10)` always with radix; `Number("")` is 0. Dates: months are 0-based in `new Date(y, m, d)`.
- forEach ignores `await`; use `for (const x of arr) await f(x)` or `Promise.all(arr.map(f))`.
