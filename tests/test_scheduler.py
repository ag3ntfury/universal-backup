import tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from universal_backup.scheduler import SchedulerState
JOB={"id":"j","schedule":{"interval":"1d"}}
class Tests(unittest.TestCase):
 def test_first_due(self):
  with tempfile.TemporaryDirectory() as d:self.assertTrue(SchedulerState(Path(d)/"s").status(JOB)["due"])
 def test_last_success_clock(self):
  with tempfile.TemporaryDirectory() as d:
   s=SchedulerState(Path(d)/"s");n=datetime(2026,1,1,tzinfo=timezone.utc);s.success("j",n);self.assertFalse(s.status(JOB,n+timedelta(hours=23))["due"]);self.assertTrue(s.status(JOB,n+timedelta(days=1))["due"])
 def test_skip(self):
  with tempfile.TemporaryDirectory() as d:
   s=SchedulerState(Path(d)/"s");n=datetime(2026,1,1,tzinfo=timezone.utc);s.skipped("j","15m",n);self.assertFalse(s.status(JOB,n+timedelta(minutes=14))["due"]);self.assertTrue(s.status(JOB,n+timedelta(minutes=15))["due"])
 def test_failure_pending(self):
  with tempfile.TemporaryDirectory() as d:
   s=SchedulerState(Path(d)/"s");s.failure("j","drive missing");self.assertTrue(s.status(JOB)["due"])


class DeclineTests(unittest.TestCase):
 def test_denied_until_next_interval_and_persists(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"state.json"
   state=SchedulerState(path)
   now_at=datetime(2026,1,1,tzinfo=timezone.utc)
   state.denied("j","1d",now_at)
   self.assertFalse(state.status(JOB,now_at+timedelta(hours=23))["due"])
   self.assertTrue(state.status(JOB,now_at+timedelta(days=1))["due"])
   reloaded=SchedulerState(path)
   self.assertFalse(reloaded.status(JOB,now_at+timedelta(hours=1))["due"])


class RecoveryTests(unittest.TestCase):
 def test_running_job_recovered_as_pending(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"state.json"
   state=SchedulerState(path)
   state.begin("j", datetime(2026,1,1,tzinfo=timezone.utc))
   self.assertFalse(state.status(JOB)["due"])
   restarted=SchedulerState(path)
   self.assertEqual(restarted.recover_interrupted(), ["j"])
   self.assertTrue(restarted.status(JOB)["due"])
   self.assertIsNone(restarted.record("j")["running"])
   self.assertEqual(restarted.record("j")["last_result"], "interrupted")

 def test_success_clears_running_and_pending(self):
  with tempfile.TemporaryDirectory() as d:
   state=SchedulerState(Path(d)/"state.json")
   state.begin("j")
   state.success("j")
   record=state.record("j")
   self.assertIsNone(record["running"])
   self.assertFalse(record["pending"])
   self.assertEqual(record["last_result"], "success")

 def test_failure_clears_running_and_keeps_pending(self):
  with tempfile.TemporaryDirectory() as d:
   state=SchedulerState(Path(d)/"state.json")
   state.begin("j")
   state.failure("j","simulated worker crash")
   record=state.record("j")
   self.assertIsNone(record["running"])
   self.assertTrue(record["pending"])
   self.assertEqual(record["last_result"], "failed")

 def test_state_schema_one_migrates(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"state.json"
   path.write_text('{"schema":1,"jobs":{"j":{"last_success":null,"pending":false}}}')
   state=SchedulerState(path)
   self.assertEqual(state.data["schema"], 2)
   self.assertIsNone(state.record("j")["running"])
