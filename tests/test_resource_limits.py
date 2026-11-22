import unittest
from universal_backup.resource_limits import normalize_policy, build_limited_command


class ResourcePolicyTests(unittest.TestCase):
    def test_defaults(self):
        p = normalize_policy()
        self.assertEqual(p["memory_high"], "1G")
        self.assertEqual(p["memory_max"], "2G")
        self.assertEqual(p["max_parallel_jobs"], 1)

    def test_custom_policy(self):
        p = normalize_policy({"memory_high": "768M", "memory_max": "1536M", "nice": 12})
        self.assertEqual(p["memory_high"], "768M")
        self.assertEqual(p["nice"], 12)

    def test_rejects_bad_memory(self):
        with self.assertRaises(ValueError):
            normalize_policy({"memory_max": "unlimited"})

    def test_rejects_parallel_jobs(self):
        with self.assertRaises(ValueError):
            normalize_policy({"max_parallel_jobs": 2})

    def test_systemd_command_contains_limits(self):
        cmd = build_limited_command(["python", "worker"], {}, systemd_run=True)
        self.assertIn("--property=MemoryHigh=1G", cmd)
        self.assertIn("--property=MemoryMax=2G", cmd)
        self.assertIn("--property=CPUWeight=20", cmd)
        self.assertIn("--property=IOWeight=20", cmd)


if __name__ == "__main__":
    unittest.main()
