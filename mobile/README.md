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
OpenClaw runs on your own computer with a real browser. Turn on its Gateway's HTTP endpoint
(`gateway.http.endpoints.chatCompletions.enabled: true` in the OpenClaw config) and note the Gateway token.
Kimi Claw (OpenClaw hosted by Moonshot) works the same way if it gives you a Gateway address and token
with the HTTP endpoint on. Then link it either way:
- **As the team's AI:** at sign-in step 2 pick **OpenClaw (Clawdbot)**, enter the Gateway address and token.
- **As a browsing helper:** keep any AI for the team, then **Account > Link OpenClaw**. The Manager gets a
  `browse` action that sends web research to OpenClaw (read-only: no logins, purchases, posts or messages).

Address: on the same Wi-Fi, `http://<computer-ip>:18789/v1` (the app allows plain http to your local
network). Away from home, put the Gateway behind Tailscale (`tailscale serve`) and use its https address;
never expose the Gateway to the open internet.

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
