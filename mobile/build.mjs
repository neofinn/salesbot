// Builds www/: the sign-in page (index.html), and the MyOps page itself (app.html, the same page as the
// claude.ai artifact) running on the phone runtime in src/native.js.
import { build } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

mkdirSync("www", { recursive: true });
const common = { bundle: true, format: "iife", target: "es2020", minify: true, legalComments: "none" };
await build({ ...common, entryPoints: ["src/login.js"], outfile: "www/login.js" });
await build({ ...common, entryPoints: ["src/native.js"], outfile: "www/native.js" });
copyFileSync("www-src/index.html", "www/index.html");
// Web version (the same app in any browser): an install manifest and icon.
copyFileSync("assets/logo.png", "www/icon.png");
writeFileSync("www/manifest.webmanifest", JSON.stringify({
  name: "MyOps", short_name: "MyOps", start_url: "./index.html", scope: "./", display: "standalone",
  background_color: "#ffffff", theme_color: "#ffffff",
  icons: [{ src: "icon.png", sizes: "1024x1024", type: "image/png", purpose: "any maskable" }],
}, null, 2));

let page = readFileSync("../artifact/salesbot.html", "utf8");
// Wording that only fits claude.ai: on the phone the team runs on the owner's chosen AI.
const swaps = [
  ["Claude didn't answer (", "The AI didn't answer ("],
  ['session_expired: "Your session expired. Sign in to claude.ai again."', 'session_expired: "Your session expired. Open Account and sign in again.", bad_key: "Your AI platform rejected the key. Open Account > Change AI and reconnect.", network: "No connection to the AI service. Check your internet and send again.", upstream_error: "The AI service had a problem. Send again in a moment."'],
  ['not_granted: "Claude access was declined for this page, so the team can\'t work. Reload the page to be asked again."', 'not_granted: "The AI is not connected. Open Account > Change AI."'],
  ["Team on duty · saved to this page", "Team on duty · synced to your account"],
];
for (const [a, b] of swaps) {
  if (!page.includes(a)) throw new Error(`build: expected text not found in the page: ${a.slice(0, 60)}`);
  page = page.replace(a, b);
}
writeFileSync("www/app.html", `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icon.png"><link rel="apple-touch-icon" href="icon.png">
<script src="native.js"></script>
</head><body>
${page}
</body></html>
`);
console.log("www/ built");
