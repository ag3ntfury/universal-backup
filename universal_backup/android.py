from pathlib import Path
import shutil,subprocess,tempfile
class AdbError(RuntimeError): pass
def stage_adb_sources(serial,entries):
 if not shutil.which("adb"): raise AdbError("adb executable not found")
 root=Path(tempfile.mkdtemp(prefix="universal-backup-adb-"));out=[]
 try:
  for e in entries:
   remote=e["path"]
   if not remote.startswith("/") or ".." in Path(remote).parts: raise AdbError(f"unsafe Android path: {remote}")
   local=root/e["name"];p=subprocess.run(["adb","-s",serial,"pull",remote,str(local)],capture_output=True,text=True)
   if p.returncode: raise AdbError(p.stderr.strip() or f"adb pull failed: {remote}")
   if not local.is_dir(): raise AdbError(f"expected directory not pulled: {remote}")
   out.append((e["name"],local))
  return root,out
 except Exception: shutil.rmtree(root,ignore_errors=True);raise
