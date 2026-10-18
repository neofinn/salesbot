"""Native apps: a Capacitor project per business that wraps the live MyOps web app.

The native shell opens the business's MyOps server (capacitor `server.url`), so new features
and fixes on the server reach the phone without a new store release. Rebuild only when the
name, icon or bundle id change. The GitHub workflow in .github/workflows/mobile.yml builds
every project under apps/: an installable Android APK on each push, and an iOS build on demand.
"""

from __future__ import annotations

import io
import json
import zipfile

from . import AppSpec
from .icons import icon_png

CAPACITOR = "^7.4.0"
CAPACITOR_ASSETS = "^3.0.5"


def project_files(spec: AppSpec, server_url: str) -> dict[str, bytes]:
    """Every file of the native project, keyed by path relative to the project root."""
    if not server_url:
        raise ValueError("A native app needs the server's public address: set SALESBOT_PUBLIC_URL (https://...) or the app's server_url.")
    start = server_url.rstrip("/") + f"/app/{spec.slug}"
    package = {
        "name": spec.slug,
        "version": f"1.0.{spec.version}",
        "private": True,
        "description": spec.description or f"{spec.name} on MyOps",
        "scripts": {
            "assets": f"capacitor-assets generate --iconBackgroundColor '{spec.color}' --iconBackgroundColorDark '{spec.color}' "
                      f"--splashBackgroundColor '{spec.background}' --splashBackgroundColorDark '{spec.color}'",
            "android": "npx cap add android && npm run assets -- --android && npx cap sync android",
            "ios": "npx cap add ios && npm run assets -- --ios && npx cap sync ios",
        },
        "dependencies": {f"@capacitor/{p}": CAPACITOR for p in ("core", "android", "ios")},
        "devDependencies": {"@capacitor/cli": CAPACITOR, "@capacitor/assets": CAPACITOR_ASSETS},
    }
    config = {
        "appId": spec.bundle_id,
        "appName": spec.name,
        "webDir": "www",
        "server": {"url": start, "cleartext": start.startswith("http://")},
        "android": {"backgroundColor": spec.background},
        "ios": {"backgroundColor": spec.background, "contentInset": "always"},
    }
    fallback = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{spec.name}</title><style>body{{font-family:system-ui;background:{spec.background};display:grid;place-items:center;height:100vh;margin:0;text-align:center}}</style></head>
<body><div><h2>{spec.name}</h2><p>Connecting to your MyOps team…</p><p><a href="{start}">Open</a></p></div>
<script>setTimeout(() => location.replace({json.dumps(start)}), 300)</script></body></html>"""
    readme = f"""# {spec.name} (MyOps app)

Native Android and iOS app for {spec.name}. It opens {start}, so updates on the server reach
the phone straight away. Bundle id `{spec.bundle_id}`, version 1.0.{spec.version}.

## Build Android (APK you can install directly)
    npm install
    npm run android
    cd android && ./gradlew assembleDebug     # android/app/build/outputs/apk/debug/app-debug.apk
Or push this folder under `apps/` in the MyOps repo: the "Mobile apps" GitHub workflow builds the APK.
For Google Play, build a signed release bundle (`./gradlew bundleRelease`) with your upload key.

## Build iOS
On a Mac with Xcode: `npm install && npm run ios && npx cap open ios`, then run it or archive it
for TestFlight/App Store with your Apple Developer account (needed to install on iPhones).
The GitHub workflow can also build it for the simulator on demand (Actions > Mobile apps > Run workflow).

## No build at all
On any phone, open {start} and choose Add to Home Screen.
"""
    return {
        "package.json": json.dumps(package, indent=2).encode(),
        "capacitor.config.json": json.dumps(config, indent=2).encode(),
        "myops-app.json": json.dumps(spec.to_dict(), indent=2).encode(),
        "www/index.html": fallback.encode(),
        "assets/logo.png": icon_png(1024, spec.color, spec.letter),
        "README.md": readme.encode(),
        ".gitignore": b"node_modules/\nandroid/\nios/\n",
    }


def project_zip(spec: AppSpec, server_url: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in project_files(spec, server_url).items():
            z.writestr(f"{spec.slug}/{path}", data)
    return buf.getvalue()
