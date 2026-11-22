import tempfile,unittest
from pathlib import Path
from universal_backup.config import load_job,ConfigError
from universal_backup.scheduler import parse_interval
VALID="""id: test
name: Test
enabled: true
source:
  type: local
  paths: [/tmp/source]
destination:
  device: {type: storage, identifier_type: filesystem_uuid, uuid: ABC}
  path: Backups
schedule: {interval: 1d, mode: prompt}
backup: {integrity: sha256, verify_after_backup: true}
"""
class ConfigTests(unittest.TestCase):
 def test_valid(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"j.yaml";p.write_text(VALID);self.assertEqual(load_job(p)["id"],"test")
 def test_traversal(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"j.yaml";p.write_text(VALID.replace("path: Backups","path: ../escape"))
   with self.assertRaises(ConfigError):load_job(p)
 def test_intervals(self):
  self.assertEqual(parse_interval("7d").days,7)
  for x in ("5m","31d","bad"):
   with self.assertRaises(ValueError):parse_interval(x)
