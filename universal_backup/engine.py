from pathlib import Path,PurePosixPath
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl,hashlib,json,os,shutil,tempfile
class BackupError(RuntimeError): pass
def digest(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): h.update(b)
 return h.hexdigest()
def safe_rel(s):
 p=PurePosixPath(s)
 if p.is_absolute() or ".." in p.parts or not p.parts: raise BackupError(f"unsafe relative path: {s}")
 return p
@contextmanager
def lock(root):
 root.mkdir(parents=True,exist_ok=True)
 with (root/".universal-backup.lock").open("a+") as f:
  try: fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError as e: raise BackupError("backup store is busy") from e
  try: yield
  finally: fcntl.flock(f.fileno(),fcntl.LOCK_UN)
def _paths_overlap(source, destination):
 """Return True when either path contains the other."""
 return source == destination or source in destination.parents or destination in source.parents


def _validate_backup_paths(sources, root):
 """Validate sources and reject any source/destination directory overlap.

 This runs before the backup lock creates the destination directory. That
 ordering is important: a rejected backup must not modify the source tree.
 """
 destination = Path(root).expanduser()
 if destination.is_symlink():
  raise BackupError(f"backup destination must not be a symlink: {destination}")
 destination = destination.resolve()
 normalized = []
 aliases = set()
 for alias, source in sources:
  if not isinstance(alias, str) or not alias or "/" in alias or alias in (".", ".."):
   raise BackupError("invalid source alias")
  if alias in aliases:
   raise BackupError(f"duplicate source alias: {alias}")
  aliases.add(alias)
  source = Path(source).expanduser()
  if source.is_symlink() or not source.is_dir():
   raise BackupError(f"source missing or unsafe: {source}")
  source = source.resolve()
  if _paths_overlap(source, destination):
   raise BackupError(
    f"source and backup destination overlap; refusing backup: {source} <-> {destination}"
   )
  normalized.append((alias, source))
 if not normalized:
  raise BackupError("at least one source directory is required")
 return normalized, destination


def scan(sources):
 files={};dirs=[]
 for alias,root in sources:
  if not alias or "/" in alias or alias in (".",".."): raise BackupError("invalid source alias")
  root=Path(root)
  if not root.is_dir() or root.is_symlink(): raise BackupError(f"source missing or unsafe: {root}")
  for p in sorted(root.rglob("*")):
   if p.is_symlink(): raise BackupError(f"symlink refused: {p}")
   rel=p.relative_to(root).as_posix(); key=f"{alias}/{rel}" if rel else alias
   if p.is_dir(): dirs.append(key)
   elif p.is_file():
    a=p.stat(); h=digest(p); b=p.stat()
    if (a.st_size,a.st_mtime_ns)!=(b.st_size,b.st_mtime_ns): raise BackupError(f"file changed during scan: {p}")
    files[key]={"sha256":h,"size":b.st_size,"mtime_ns":b.st_mtime_ns}
 return {"files":files,"directories":sorted(set(dirs))}
def backup(sources,root,job_id):
 sources,root = _validate_backup_paths(sources, root)
 with lock(root):
  vd=root/"Versions"; obj=root/"Objects";vd.mkdir(exist_ok=True);obj.mkdir(exist_ok=True)
  versions=sorted((p for p in vd.glob("V[0-9]*") if p.is_dir()),key=lambda p:int(p.name[1:]))
  old=json.loads((versions[-1]/"manifest.json").read_text()) if versions else None
  snap=scan(sources)
  if old and old.get("files")==snap["files"] and old.get("directories")==snap["directories"]: return old["version"]
  number=max([int(p.name[1:]) for p in versions] or [0])+1; name=f"V{number:06d}"; stage=Path(tempfile.mkdtemp(prefix=".building-",dir=vd))
  try:
   source_map=dict(sources)
   for rel,info in snap["files"].items():
    alias,sub=rel.split("/",1); source=source_map[alias]/Path(*safe_rel(sub).parts); target=obj/info["sha256"][:2]/info["sha256"][2:]
    if target.exists():
     if digest(target)!=info["sha256"]: raise BackupError(f"corrupt object: {target}")
    else:
     target.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(dir=target.parent,prefix=".object-");os.close(fd)
     try: shutil.copyfile(source,tmp);
     finally: pass
     if digest(tmp)!=info["sha256"]: os.unlink(tmp);raise BackupError(f"object verification failed: {rel}")
     os.replace(tmp,target)
   manifest={"schema":1,"job_id":job_id,"version":name,"created_utc":datetime.now(timezone.utc).isoformat(),"sources":[{"name":n,"path":str(p)} for n,p in sources],**snap,"file_count":len(snap["files"]),"total_bytes":sum(x["size"] for x in snap["files"].values())}
   (stage/"manifest.json").write_text(json.dumps(manifest,indent=2)); os.replace(stage,vd/name)
   latest=root/"Latest";new=root/f".Latest-new-{os.getpid()}";oldlatest=root/f".Latest-old-{os.getpid()}"
   shutil.rmtree(new,ignore_errors=True);new.mkdir()
   for d in manifest["directories"]: (new/Path(*safe_rel(d).parts)).mkdir(parents=True,exist_ok=True)
   for rel,info in manifest["files"].items():
    dest=new/Path(*safe_rel(rel).parts);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(obj/info["sha256"][:2]/info["sha256"][2:],dest)
    if digest(dest)!=info["sha256"]: raise BackupError(f"Latest verification failed: {rel}")
   if latest.exists(): os.replace(latest,oldlatest)
   os.replace(new,latest);shutil.rmtree(oldlatest,ignore_errors=True)
   return name
  except Exception:
   shutil.rmtree(stage,ignore_errors=True);raise
def verify(root):
 root=Path(root); versions=sorted((p for p in (root/"Versions").glob("V[0-9]*") if p.is_dir()),key=lambda p:int(p.name[1:]))
 if not versions: raise BackupError("no backup versions")
 count=0
 for v in versions:
  m=json.loads((v/"manifest.json").read_text())
  if m.get("version")!=v.name: raise BackupError("manifest version mismatch")
  for info in m["files"].values():
   o=root/"Objects"/info["sha256"][:2]/info["sha256"][2:]
   if not o.is_file() or digest(o)!=info["sha256"]: raise BackupError(f"missing/corrupt object: {o}")
   count+=1
 return {"versions":len(versions),"objects_checked":count}
def restore(root,version,destination):
 root=Path(root);dest=Path(destination)
 if dest.exists(): raise BackupError("restore destination exists; refusing overwrite")
 mpath=root/"Versions"/version/"manifest.json"
 if not mpath.is_file(): raise BackupError("version not found")
 m=json.loads(mpath.read_text());stage=dest.parent/f".{dest.name}.restore-{os.getpid()}"
 if stage.exists(): raise BackupError("restore staging path exists")
 stage.mkdir(parents=True)
 try:
  for d in m["directories"]: (stage/Path(*safe_rel(d).parts)).mkdir(parents=True,exist_ok=True)
  for rel,info in m["files"].items():
   target=stage/Path(*safe_rel(rel).parts);target.parent.mkdir(parents=True,exist_ok=True);obj=root/"Objects"/info["sha256"][:2]/info["sha256"][2:];shutil.copy2(obj,target)
   if digest(target)!=info["sha256"]: raise BackupError(f"restore verification failed: {rel}")
  dest.parent.mkdir(parents=True,exist_ok=True);os.replace(stage,dest)
 except Exception: shutil.rmtree(stage,ignore_errors=True);raise
