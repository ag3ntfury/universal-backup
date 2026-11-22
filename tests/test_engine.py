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

 def test_rejects_destination_inside_source_before_creating_it(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/"source";source.mkdir();(source/"document.txt").write_text("safe")
   destination=source/"Backups"
   with self.assertRaisesRegex(BackupError,"overlap"):
    backup([("data",source)],destination,"j")
   self.assertFalse(destination.exists())

 def test_rejects_source_inside_destination(self):
  with tempfile.TemporaryDirectory() as d:
   destination=Path(d)/"store";source=destination/"input";source.mkdir(parents=True)
   (source/"document.txt").write_text("safe")
   with self.assertRaisesRegex(BackupError,"overlap"):
    backup([("data",source)],destination,"j")

 def test_rejects_source_equal_to_destination(self):
  with tempfile.TemporaryDirectory() as d:
   same=Path(d)/"same";same.mkdir()
   with self.assertRaisesRegex(BackupError,"overlap"):
    backup([("data",same)],same,"j")

 def test_rejects_duplicate_source_aliases(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/"source";source.mkdir();destination=Path(d)/"store"
   with self.assertRaisesRegex(BackupError,"duplicate source alias"):
    backup([("data",source),("data",source)],destination,"j")
   self.assertFalse(destination.exists())
