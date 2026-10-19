// Registers the app's link scheme (com.myops.app://) so Google and OpenRouter sign-in return to the app.
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const SCHEME = "com.myops.app";
const platform = process.argv[2];
if (platform === "android") {
  const f = "android/app/src/main/AndroidManifest.xml";
  let x = readFileSync(f, "utf8");
  if (!x.includes(`android:scheme="${SCHEME}"`)) {
    x = x.replace(/(<intent-filter>\s*<action android:name="android.intent.action.MAIN" \/>[\s\S]*?<\/intent-filter>)/, `$1
            <intent-filter>
                <action android:name="android.intent.action.VIEW" />
                <category android:name="android.intent.category.DEFAULT" />
                <category android:name="android.intent.category.BROWSABLE" />
                <data android:scheme="${SCHEME}" />
            </intent-filter>`);
    if (!x.includes(`android:scheme="${SCHEME}"`)) throw new Error("could not add the link scheme to AndroidManifest.xml");
  }
  // Plain http to a computer on the same Wi-Fi (OpenClaw Gateway, Ollama).
  if (!x.includes("usesCleartextTraffic")) x = x.replace("<application", '<application\n        android:usesCleartextTraffic="true"');
  writeFileSync(f, x);
} else if (platform === "ios") {
  const f = "ios/App/App/Info.plist";
  if (!existsSync(f)) throw new Error(`${f} not found`);
  let x = readFileSync(f, "utf8");
  if (!x.includes(`<string>${SCHEME}</string>`)) {
    x = x.replace(/<dict>/, `<dict>
	<key>NSAppTransportSecurity</key>
	<dict><key>NSAllowsLocalNetworking</key><true/></dict>
	<key>NSLocalNetworkUsageDescription</key>
	<string>MyOps connects to your OpenClaw or Ollama computer on this network.</string>
	<key>CFBundleURLTypes</key>
	<array><dict><key>CFBundleURLSchemes</key><array><string>${SCHEME}</string></array></dict></array>`);
    writeFileSync(f, x);
  }
} else {
  throw new Error("usage: node patch-native.mjs android|ios");
}
console.log(`${platform}: ${SCHEME}:// links open the app`);
