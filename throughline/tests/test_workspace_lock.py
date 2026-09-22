"""Single-active-workspace lock (NFR-2): atomic acquisition (no
check-then-write race), stale-lock reclaim, and a genuine concurrent
multi-process race test (ARCH §15 open test #4)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from helpers import EngineError, REPO_ROOT, cleanup, make_workspace, new_root, new_store, persistence, workspace_mod


class SingleActiveWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.store, self.root = new_store()

    def tearDown(self):
        cleanup(self.root)

    def test_second_workspace_blocked_while_first_is_active(self):
        make_workspace(self.store)
        with self.assertRaises(EngineError) as ctx:
            make_workspace(self.store)
        self.assertEqual(ctx.exception.code, "WORKSPACE_ALREADY_ACTIVE")

    def test_reset_frees_the_lock_without_deleting_data(self):
        ws, brief, conn = make_workspace(self.store)
        conn.close()
        closed_id = workspace_mod.reset_active_workspace(self.store, actor="T")
        self.assertEqual(closed_id, ws.id)
        self.assertIsNone(self.store.active_workspace_id())
        self.assertIn(ws.id, self.store.list_workspace_ids())  # data preserved
        ws2, brief2, conn2 = make_workspace(self.store)
        self.assertNotEqual(ws2.id, ws.id)
        conn2.close()

    def test_explicit_reset_frees_the_lock_regardless_of_recorded_pid(self):
        """The real recovery path for an abandoned lock: every Engine
        command is a short-lived, one-shot process by design (ARCH §2/§4),
        so the process that created a lock has *always* already exited by
        the time a later command runs — that is normal, not a crash. An
        automatic "dead pid" reclaim would therefore silently defeat NFR-2
        moments after any ordinary `workspace new`. Recovery is instead
        always available, unconditionally, via an explicit `workspace
        reset` — proven here even with a deliberately implausible pid."""
        ws, brief, conn = make_workspace(self.store)
        conn.close()
        lock = self.store.read_lock()
        lock["pid"] = 999999999
        self.store.lock_path.write_text(json.dumps(lock))
        self.assertEqual(self.store.active_workspace_id(), ws.id)  # still reported active
        workspace_mod.reset_active_workspace(self.store, actor="T")
        self.assertIsNone(self.store.active_workspace_id())
        ws2, brief2, conn2 = make_workspace(self.store)
        self.assertNotEqual(ws2.id, ws.id)
        conn2.close()

    def test_resume_after_reset_reacquires_the_same_workspace(self):
        ws, brief, conn = make_workspace(self.store)
        conn.close()
        workspace_mod.reset_active_workspace(self.store, actor="T")
        result = workspace_mod.resume_workspace(self.store, ws.id, actor="T")
        self.assertEqual(result["workspace"].id, ws.id)


class ConcurrentWorkspaceRaceTests(unittest.TestCase):
    """ARCH §15 open test #4: two processes racing to open a workspace
    against the same root — exactly one must win, atomically."""

    def setUp(self):
        self.root = new_root()

    def tearDown(self):
        cleanup(self.root)

    def test_several_concurrent_processes_only_one_wins(self):
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from engine import persistence, workspace as workspace_mod\n"
            "from engine.errors import EngineError\n"
            "import json\n"
            "store = persistence.Store(root=%r)\n"
            "try:\n"
            "    ws, brief = workspace_mod.create_workspace(store, actor='RaceTest')\n"
            "    print(json.dumps({'ok': True, 'workspaceId': ws.id}))\n"
            "except EngineError as e:\n"
            "    print(json.dumps({'ok': False, 'code': e.code}))\n"
        ) % (str(REPO_ROOT), str(self.root))

        procs = [
            subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(6)
        ]
        outputs = []
        for p in procs:
            out, err = p.communicate(timeout=30)
            outputs.append(json.loads(out.strip().splitlines()[-1]))

        successes = [o for o in outputs if o["ok"]]
        failures = [o for o in outputs if not o["ok"]]
        self.assertEqual(len(successes), 1, f"expected exactly one winner, got {outputs}")
        self.assertEqual(len(failures), 5)
        self.assertTrue(all(f["code"] == "WORKSPACE_ALREADY_ACTIVE" for f in failures))

        store = persistence.Store(root=self.root)
        self.assertEqual(store.active_workspace_id(), successes[0]["workspaceId"])


if __name__ == "__main__":
    unittest.main()
