import io
import json
import struct
import zipfile
import zlib

from salesbot.apps import AppSpec, slugify, validate
from salesbot.apps.icons import icon_png, icon_svg
from salesbot.apps.native import project_files
from salesbot.apps.pwa import head_tags, manifest

from .test_webapp import make_client


def png_size_and_pixels(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    idat = data.index(b"IDAT")
    length = struct.unpack(">I", data[idat - 4 : idat])[0]
    raw = zlib.decompress(data[idat + 4 : idat + 4 + length])
    return w, h, raw


def test_icons_and_spec():
    w, h, raw = png_size_and_pixels(icon_png(64, "#233a57", "L"))
    assert (w, h) == (64, 64) and len(raw) == 64 * (64 * 3 + 1)
    assert raw[1:4] == bytes((0x23, 0x3A, 0x57))  # corner pixel is the background
    assert b"\xff\xff\xff" in raw  # the white letter is drawn
    assert "#d2551f" in icon_svg("#d2551f", "b") and ">B<" in icon_svg("#d2551f", "b")
    spec = AppSpec(slug="lopez-bakery", name="Lopez Bakery & Catering")
    assert spec.letter == "L" and spec.short_name == "Lopez Bakery" and spec.bundle_id == "com.myops.lopezbakery"
    assert slugify("Lopez Bakery & Catering!") == "lopez-bakery-catering" and slugify("123 Go") == "app-123-go"
    assert validate(spec) == []
    bad = AppSpec(slug="X!", name="", color="red", server_url="ftp://x", platforms=["windows"])
    assert len(validate(bad)) == 5


def test_manifest_and_native_project():
    spec = AppSpec(slug="lopez", name="Lopez Bakery", color="#d2551f", version=3)
    m = manifest(spec)
    assert m["start_url"].startswith("/app/lopez") and m["display"] == "standalone" and m["theme_color"] == "#d2551f"
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}
    assert 'rel="manifest" href="/app/lopez/manifest.webmanifest"' in head_tags(spec)
    files = project_files(spec, "https://ops.example.com/")
    cap = json.loads(files["capacitor.config.json"])
    assert cap["appId"] == "com.myops.lopez" and cap["server"]["url"] == "https://ops.example.com/app/lopez"
    assert cap["server"]["cleartext"] is False
    pkg = json.loads(files["package.json"])
    assert pkg["version"] == "1.0.3" and "@capacitor/android" in pkg["dependencies"]
    assert png_size_and_pixels(files["assets/logo.png"])[:2] == (1024, 1024)
    try:
        project_files(spec, "")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "SALESBOT_PUBLIC_URL" in str(exc)


def test_app_routes(tmp_path):
    client2, fake = make_client(tmp_path, token="")
    with client2:
        fake.script("the Manager", ("", [("ask_app_dev", {"platform": "android", "request": "App for Lopez Bakery"})]), ("Made it.", []))
        fake.script("Android developer", ("", [("save_app", {"name": "Lopez Bakery", "color": "#d2551f", "notes": "first"})]), ("Created.", []))
        assert client2.post("/api/chat", json={"text": "make an app"}).json()["reply"] == "Made it."
        apps = client2.get("/api/apps").json()
        assert apps[0]["slug"] == "lopez-bakery" and apps[0]["version"] == 1
        assert apps[0]["install_link"].endswith("/app/lopez-bakery")
        page = client2.get("/app/lopez-bakery").text
        assert 'rel="manifest"' in page and "<h1>Lopez Bakery</h1>" in page and "serviceWorker" in page
        assert client2.get("/app/lopez-bakery/manifest.webmanifest").json()["name"] == "Lopez Bakery"
        icon = client2.get("/app/lopez-bakery/icon-192.png")
        assert icon.headers["content-type"] == "image/png" and png_size_and_pixels(icon.content)[:2] == (192, 192)
        assert client2.get("/app/lopez-bakery/icon-100.png").status_code == 404
        assert "skipWaiting" in client2.get("/sw.js").text
        z = zipfile.ZipFile(io.BytesIO(client2.get("/api/apps/lopez-bakery/native.zip").content))
        assert "lopez-bakery/capacitor.config.json" in z.namelist()


def test_login_redirects_back_to_app(tmp_path):
    client, fake = make_client(tmp_path, token="s3cret")
    with client:
        page = client.get("/app/missing")
        assert page.status_code == 404
        # Unauthenticated: login page carries the app's manifest and returns to the app after sign-in.
        resp = client.post("/login", data={"token": "s3cret", "next": "/app/lopez"}, follow_redirects=False)
        assert resp.headers["location"] == "/app/lopez"
        evil = client.post("/login", data={"token": "s3cret", "next": "https://evil.example"}, follow_redirects=False)
        assert evil.headers["location"] == "/"


async def test_app_devs_save_update_and_validate(team, fake):
    fake.script("Android developer",
                ("", [("save_app", {"name": "Lopez Bakery", "color": "#d2551f"})]),
                ("", [("save_app", {"name": "Lopez Bakery", "slug": "lopez-bakery", "color": "#000000", "notes": "dark icon"})]),
                ("", [("save_app", {"name": "Bad", "color": "orange"})]),
                ("done", []))
    await team.app_dev("android").run("make and update")
    saved = await team.store.get_app("lopez-bakery")
    assert saved["version"] == 2 and saved["color"] == "#000000" and saved["notes"] == "dark icon"
    results = [c for c in fake.calls if "Android developer" in c[0]][-1][1][-1].tool_results
    assert results[0].is_error and "hex color" in results[0].content
    fake.script("iOS developer", ("", [("list_apps", {}), ("app_links", {"slug": "lopez-bakery"}), ("retire_app", {"slug": "lopez-bakery"})]), ("ok", []))
    await team.app_dev("ios").run("list then retire")
    assert await team.store.get_app("lopez-bakery") is None
    assert await team.fire("ios_dev") == "ios_dev is core staff and can't be fired."
