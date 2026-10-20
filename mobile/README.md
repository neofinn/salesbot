# MyOps phone app (Android and iOS)

A self-contained phone app: the whole MyOps team (the same page as the claude.ai artifact) runs on the
phone. There is no MyOps server to run. AI calls go straight from the phone to the platform you connect.

## Two sign-ins
1. **MyOps account:** email and password, or Google. Accounts live in the MyOps Supabase project. Your
   team, chats, notes, videos and apps sync to your account (table `user_docs`, each person sees only
   their own rows), so a second phone picks up where you left off.
2. **Your AI:** **Sign in with OpenRouter** (a real login: one account for Claude, GPT, Gemini, Grok,
   Llama, Qwen and more), or an API key for Anthropic Claude, OpenAI, Google Gemini, xAI Grok, DeepSeek,
   Mistral, Groq, Kimi (Moonshot), Alibaba Qwen, Perplexity, Together AI or Cohere, or your own Ollama server. The key is
   checked, you pick a model, and it stays on the phone; it is never uploaded. OpenAI, Anthropic and
   Google don't let other apps sign in with a ChatGPT, Claude or Gemini subscription, which is why those
   take an API key.

The **Account** button in the app shows who is signed in and which AI is in use, and lets you change AI
or sign out.

## OpenClaw (formerly Clawdbot)
OpenClaw is your own agent with a real browser. In the app, **Account > Connect OpenClaw** offers:
- **On my computer** (Mac, Linux, Windows with WSL2) or **on a cloud server** (any Ubuntu VPS, 24/7):
  install [Tailscale](https://tailscale.com/download) there and on the phone, then run
  `curl -fsSL https://bsvahyfzpfnhkyzgmoow.supabase.co/functions/v1/openclaw-setup | bash`
  ([source](../integrations/openclaw/myops-link.sh)). It installs OpenClaw with the official installer if
  needed, turns on the Gateway's OpenAI-compatible endpoint with a strong token, serves it privately over
  Tailscale (never the open internet), tests it, and prints a QR code and a pairing code. Scan the QR code
  with the phone's camera, or paste the pairing code.
- **Link existing OpenClaw** (yours, or a hosted one such as Kimi Claw if it gives you a Gateway address
  and token): paste a pairing code, or the address and token.

Linked OpenClaw gives the Manager a `browse` action for web research (read-only: no logins, purchases,
posts or messages). To run the whole team on OpenClaw instead, pick **OpenClaw (Clawdbot)** at sign-in
step 2 and paste the same pairing code.

## Cloud servers (24/7)
**Account > Connect OpenClaw > Create a cloud server** creates a server on your own Hetzner or DigitalOcean
account (your API token stays on the phone) and sets it up at first boot: Tailscale (private access only),
OpenClaw with your Anthropic or Gemini key, and the MyOps server app running the team in the background.
Progress shows in the app (reported to your account by the server with a one-time secret through the
`server-report` function). When it is ready, **Link its OpenClaw** connects it, and the MyOps server app
opens at `https://<server>.<tailnet>.ts.net:8443` from any device on your Tailscale network. **Delete
server** removes it from your cloud account; it is billed monthly until then.

## Not on the phone (yet)
Clay and Airtable connectors and the stock screener's market data come from claude.ai and the research
engine; the phone app shows those tabs without them.

## One-time account settings (Supabase dashboard, project "MyOps")
- **Authentication > URL Configuration > Redirect URLs:** add `com.myops.app://auth` (Google sign-in
  returns to the app through it).
- **Authentication > Sign In / Providers > Google:** turn it on with a Google OAuth client ID and secret
  (Google Cloud Console > APIs & Services > Credentials > OAuth client, type Web application, with the
  redirect URI Supabase shows there). Email and password work without this.

## Build
    cd mobile && npm install
    npm run android && (cd android && ./gradlew assembleDebug)   # android/app/build/outputs/apk/debug/app-debug.apk
    npm run ios && npx cap open ios                                # on a Mac with Xcode

The "MyOps phone app" GitHub workflow builds both on every change: an installable APK, and an unsigned
iOS app (`MyOps-unsigned.ipa`). To install the iOS build without the App Store, sign it with your Apple
ID in Sideloadly or AltStore (free accounts re-sign every 7 days), or use an Apple Developer account
($99/year) for TestFlight and the App Store.
