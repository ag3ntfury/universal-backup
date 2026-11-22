from pathlib import Path
import yaml
from .scheduler import parse_interval
from .resource_limits import normalize_policy
class ConfigError(ValueError): pass
def load_job(path):
 p=Path(path).expanduser().resolve()
 try: d=yaml.safe_load(p.read_text())
 except Exception as e: raise ConfigError(f"cannot read {p}: {e}") from e
 if not isinstance(d,dict): raise ConfigError("YAML root must be a mapping")
 for k in ("id","name","enabled","source","destination","schedule","backup"):
  if k not in d: raise ConfigError(f"missing {k}")
 if not isinstance(d["enabled"],bool): raise ConfigError("enabled must be boolean")
 s=d["source"]
 if s.get("type") not in ("local","android"): raise ConfigError("source.type must be local or android")
 entries=s.get("entries")
 if entries is None:
  paths=s.get("paths")
  if not isinstance(paths,list) or not paths: raise ConfigError("source.paths must be a non-empty list")
  entries=[{"name":Path(str(x)).name or f"source-{i+1}","path":str(x)} for i,x in enumerate(paths)]
 if not isinstance(entries,list) or not entries: raise ConfigError("source.entries must be non-empty")
 names=set()
 for e in entries:
  if not isinstance(e,dict) or not e.get("name") or not e.get("path"): raise ConfigError("each source entry needs name and path")
  if e["name"] in names: raise ConfigError("duplicate source alias")
  names.add(e["name"])
 if s["type"]=="android" and not s.get("device_id"): raise ConfigError("Android source requires device_id")
 dest=d["destination"]; dev=dest.get("device",{})
 if dev.get("type")!="storage" or dev.get("identifier_type")!="filesystem_uuid" or not dev.get("uuid"): raise ConfigError("destination requires filesystem UUID")
 rel=Path(dest.get("path",""))
 if not str(rel) or rel.is_absolute() or ".." in rel.parts: raise ConfigError("destination path must be relative and safe")
 sch=d["schedule"]; parse_interval(sch.get("interval",""))
 if sch.get("mode","prompt") not in ("prompt","auto"): raise ConfigError("mode must be prompt or auto")
 parse_interval(sch.get("skip_reminder","15m"),60)
 b=d["backup"]
 if b.get("integrity","sha256")!="sha256" or b.get("verify_after_backup",True) is not True: raise ConfigError("SHA-256 and verification are mandatory")
 d=dict(d); d["resources"]=normalize_policy(d.get("resources")); d["source"]=dict(s,entries=entries); d["schedule"]=dict(sch,mode=sch.get("mode","prompt"),skip_reminder=sch.get("skip_reminder","15m")); d["_config_path"]=str(p); return d
def discover_jobs(directory):
 jobs=[load_job(p) for p in sorted([*Path(directory).glob("*.yaml"),*Path(directory).glob("*.yml")])]; jobs=[j for j in jobs if j["enabled"]]; ids=[j["id"] for j in jobs]
 if len(ids)!=len(set(ids)): raise ConfigError("duplicate job IDs")
 return jobs
