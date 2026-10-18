import os
import time

from salesbot import maintenance
from salesbot.store import Store


async def seed(store):
    a = await store.add_lead(name="Ann", company="A", email="ann@a.test", notes="first")
    b = await store.add_lead(name="Ann B", company="A", email="ANN@a.test ", phone="555", status="qualified", notes="second")
    c = await store.add_lead(name="Bob", company="B")
    d = await store.add_lead(name="bob", company="b ", notes="dup by name")
    await store.add_lead(name="Cy", company="C", email="cy@c.test")
    old = await store.log_task("writer", "stuck job")
    await store.db.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (time.time() - 3600, old))
    await store.log_task("writer", "fresh job")
    pid = await store.add_pending("email", {"to": "x"}, "writer")
    await store.db.execute("UPDATE pending_actions SET created_at = ? WHERE id = ?", (time.time() - 40 * 86400, pid))
    await store.add_pending("email", {"to": "y"}, "writer")
    await store.db.commit()
    return a, b, c, d


async def test_health_and_fixes(team, tmp_path):
    store = team.store
    a, b, c, d = await seed(store)
    report = await maintenance.health(store, str(tmp_path))
    assert [t["task"] for t in report["stuck_tasks"]] == ["stuck job"]
    assert report["duplicate_count"] == 2 and len(report["approvals_waiting_over_30_days"]) == 1
    assert report["last_backup"] is None

    assert await maintenance.fix_stuck_tasks(store) == 1
    assert [t["task"] for t in await store.tasks_with_status("running")] == ["fresh job"]
    assert await maintenance.merge_duplicates(store) == 2
    leads = {x["id"]: x for x in await store.all_leads()}
    assert sorted(leads) == [a, c, 5]
    assert leads[a]["phone"] == "555" and leads[a]["status"] == "qualified" and leads[a]["notes"] == "first\nsecond"
    assert leads[c]["notes"] == "dup by name"
    assert await maintenance.expire_stale_approvals(store) == 1
    assert len(await store.list_pending()) == 1
    report = await maintenance.health(store, str(tmp_path))
    assert report["duplicate_count"] == 0 and not report["stuck_tasks"] and not report["approvals_waiting_over_30_days"]


async def test_backup_keeps_last_copies(tmp_path):
    store = await Store(str(tmp_path / "myops.db")).open()
    await store.add_lead(name="Ann")
    paths = []
    for i in range(3):
        path = await maintenance.backup(store, str(tmp_path), keep=2)
        os.utime(path)
        new = path.replace(".db", f"-{i}.db")
        os.rename(path, new)
        paths.append(new)
    await maintenance.backup(store, str(tmp_path), keep=2)
    left = sorted(os.listdir(tmp_path / "backups"))
    assert len(left) == 2
    copy = await Store(str(tmp_path / "backups" / left[-1])).open()
    assert [x["name"] for x in await copy.all_leads()] == ["Ann"]
    await copy.close()
    await store.close()


async def test_manager_asks_maintenance(team, fake):
    await seed(team.store)
    fake.script("the Manager", ("", [("ask_maintenance", {"request": "Clean up"})]), ("All clean.", []))
    fake.script("the Maintenance team", ("", [("health_check", {})]), ("", [("backup_database", {})]),
                ("", [("merge_duplicate_contacts", {})]), ("Merged 2 duplicates.", []))
    assert await team.handle("c1", "Clean up the data") == "All clean."
    results = [m.tool_results[0] for m in [c for c in fake.calls if "You are the Maintenance team" in c[0]][-1][1] if m.role == "tool"]
    assert "\"duplicate_count\": 2" in results[0].content and '"ai_providers_connected"' in results[0].content
    assert results[1].is_error and "in memory" in results[1].content
    assert "Merged 2 duplicate" in results[2].content
    assert len(await team.store.all_leads()) == 3
