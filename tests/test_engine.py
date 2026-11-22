import tempfile,unittest
from pathlib import Path
from universal_backup.engine import backup,verify,restore,BackupError
class EngineTests(unittest.TestCase):
 def test_backup_versions_verify_restore(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);s=r/"src";s.mkdir();(s/"a.txt").write_text("one");store=r/"store";self.assertEqual(backup([("data",s)],store,"j"),"V000001");(s/"a.txt").write_text("two");self.assertEqual(backup([("data",s)],store,"j"),"V000002");self.assertEqual(verify(store)["versions"],2);restore(store,"V000002",r/"out");self.assertEqual((r/"out/data/a.txt").read_text(),"two")
 def test_unchanged_is_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);s=r/"src";s.mkdir();(s/"x").write_text("x");self.assertEqual(backup([("src",s)],r/"store","j"),backup([("src",s)],r/"store","j"))
 def test_restore_no_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);s=r/"src";s.mkdir();(s/"x").write_text("x");store=r/"store";backup([("src",s)],store,"j");out=r/"out";out.mkdir()
   with self.assertRaises(BackupError):restore(store,"V000001",out)
