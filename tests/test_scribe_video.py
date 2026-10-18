import os
import shutil

import pytest

from salesbot.media import video
from salesbot.store import AgentSpec

from .test_webapp import make_client

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and video.find_font()), reason="ffmpeg or fonts missing")

STORYBOARD = {
    "title": "Grand opening", "aspect": "9:16", "brand": "Lopez Bakery",
    "palette": {"bg": "#102030", "fg": "#ffffff", "accent": "#ff8800"},
    "scenes": [{"headline": "Fresh bread: 100% new", "sub": "Opening 'Saturday' %{pts}", "seconds": 2},
               {"headline": "Come say hi", "seconds": 2}],
    "narration": "We're open.", "caption": "#bakery",
}


def test_from_dict_clamps_and_defaults():
    spec = video.from_dict({"aspect": "4:3", "palette": {"bg": "red"}, "scenes": [
        {"headline": "x" * 200, "seconds": 99}, {"headline": ""}, {"sub": "no headline"}, {"headline": "ok", "seconds": "abc"}]})
    assert spec.aspect == "16:9" and spec.bg == "#18212b" and spec.title == "Untitled video"
    assert [len(s.headline) for s in spec.scenes] == [90, 2]
    assert [s.seconds for s in spec.scenes] == [8.0, 4]
    assert video.problems(video.from_dict({"scenes": []})) == ["a video needs at least one scene with a headline"]


@needs_ffmpeg
async def test_render_mp4(tmp_path):
    out = str(tmp_path / "v.mp4")
    await video.render_mp4(video.from_dict(STORYBOARD), out, "Lopez Bakery")
    assert os.path.getsize(out) > 1000
    with open(out, "rb") as fh:
        assert fh.read(12)[4:8] == b"ftyp"


async def test_scribe_writes_and_updates_notes_from_activity(team, fake):
    await team.store.add_agent(AgentSpec("writer", "Writer", "You write.", "fake:test", []))
    tid = await team.store.log_task("writer", "Summarize ACME")
    await team.store.finish_task(tid, "ACME makes anvils.")
    await team.store.add_chat("c1", "user", "We chose ACME as a partner.")
    fake.script("the Manager", ("", [("ask_scribe", {"request": "Minutes of today"})]), ("Minutes saved.", []))
    fake.script("the Scribe", ("", [("team_activity", {}), ("write_note", {"title": "Minutes", "body": "- ACME makes anvils"})]),
                ("Saved note 1: Minutes", []))
    assert await team.handle("c1", "Write minutes") == "Minutes saved."
    scribe_call = [c for c in fake.calls if "You are the Scribe" in c[0]][0]
    assert "We chose ACME as a partner." in scribe_call[1][0].text  # the chat is in the brief
    activity = [c for c in fake.calls if "You are the Scribe" in c[0]][-1][1][-1].tool_results[0].content
    assert "ACME makes anvils." in activity and '"bot": "writer"' in activity
    assert (await team.store.get_note(1))["body"] == "- ACME makes anvils"

    fake.script("the Scribe", ("", [("write_note", {"title": "Minutes v2", "body": "updated", "note_id": 1}),
                                    ("write_note", {"title": "x", "body": "y", "note_id": 99})]), ("done", []))
    await team.ask_scribe("revise")
    results = [c for c in fake.calls if "You are the Scribe" in c[0]][-1][1][-1].tool_results
    assert "Updated note 1" in results[0].content
    assert results[1].is_error and "No note 99" in results[1].content
    assert [n["title"] for n in await team.store.list_notes()] == ["Minutes v2"]


@needs_ffmpeg
async def test_video_producer_renders(team, fake):
    fake.script("the Manager", ("", [("ask_video_producer", {"request": "Opening promo"})]), ("Video ready.", []))
    fake.script("the Video Producer", ("", [("create_video", STORYBOARD)]), ("Made it.", []))
    assert await team.handle("c1", "Make a promo") == "Video ready."
    [v] = await team.store.list_videos()
    assert v["file"] == f"{v['id']}.mp4" and v["brand"] == "Lopez Bakery" and v["aspect"] == "9:16"
    assert os.path.exists(team.video_path(v["id"]))
    result = [c for c in fake.calls if "You are the Video Producer" in c[0]][-1][1][-1].tool_results[0].content
    assert f"/api/videos/{v['id']}.mp4" in result


async def test_video_without_ffmpeg_keeps_storyboard(team, fake, monkeypatch):
    monkeypatch.setattr(video, "ffmpeg_path", lambda: None)
    fake.script("the Video Producer", ("", [("create_video", STORYBOARD)]), ("ok", []))
    await team.video_producer().run("promo")
    result = [c for c in fake.calls if "You are the Video Producer" in c[0]][-1][1][-1].tool_results[0].content
    assert "ffmpeg is not installed" in result
    [v] = await team.store.list_videos()
    assert v["file"] == "" and v["narration"] == "We're open."


def test_notes_and_videos_api(tmp_path):
    client, fake = make_client(tmp_path)
    with client:
        assert client.get("/api/notes").json() == [] and client.get("/api/videos").json() == []
        fake.script("the Manager", ("", [("ask_scribe", {"request": "note"})]), ("ok", []))
        fake.script("the Scribe", ("", [("write_note", {"title": "T", "body": "B"})]), ("ok", []))
        client.post("/api/chat", json={"text": "write it"})
        [note] = client.get("/api/notes").json()
        assert note["title"] == "T" and note["body"] == "B"
        assert client.delete(f"/api/notes/{note['id']}").json() == {"ok": True}
        assert client.delete(f"/api/notes/{note['id']}").status_code == 404
        assert client.get("/api/videos/1.mp4").status_code == 404
        assert "Notes" in client.get("/").text and "video_producer" in client.get("/").text


@needs_ffmpeg
def test_video_api_render_and_download(tmp_path):
    client, fake = make_client(tmp_path)
    with client:
        fake.script("the Manager", ("", [("ask_video_producer", {"request": "promo"})]), ("ok", []))
        fake.script("the Video Producer", ("", [("create_video", STORYBOARD)]), ("ok", []))
        client.post("/api/chat", json={"text": "video"})
        [v] = client.get("/api/videos").json()
        resp = client.get(f"/api/videos/{v['id']}.mp4")
        assert resp.status_code == 200 and resp.headers["content-type"] == "video/mp4"
        os.remove(os.path.join(tmp_path, "videos", f"{v['id']}.mp4"))
        assert client.post(f"/api/videos/{v['id']}/render").json()["file"] == f"{v['id']}.mp4"
        assert client.delete(f"/api/videos/{v['id']}").json() == {"ok": True}
        assert client.get(f"/api/videos/{v['id']}.mp4").status_code == 404
