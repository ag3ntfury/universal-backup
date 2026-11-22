from dataclasses import dataclass
import json
import shutil
import subprocess


@dataclass(frozen=True)
class Device:
    kind: str
    identifier_type: str
    identifier: str
    label: str
    mountpoint: str | None = None
    metadata: dict | None = None


class DeviceInventory:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def run(self, args):
        p = self.runner(args, text=True, capture_output=True, check=False)
        return p.stdout if p.returncode == 0 else ""

    def storage(self):
        if not shutil.which("lsblk"):
            return []
        try:
            tree = json.loads(self.run([
                "lsblk", "-J", "-o",
                "NAME,PATH,TYPE,FSTYPE,UUID,LABEL,MOUNTPOINTS,TRAN,RM,PKNAME,MODEL,SIZE"
            ]))
        except Exception:
            return []

        found = {}
        def walk(nodes, parent_removable=False, parent_path=None):
            for n in nodes:
                typ = n.get("type")
                if typ in ("loop", "rom"):
                    continue
                removable = bool(n.get("rm")) or parent_removable
                path = n.get("path") or ("/dev/" + n["name"] if n.get("name") else None)
                mounts = [x for x in (n.get("mountpoints") or []) if x]
                fstype = n.get("fstype")
                if n.get("uuid") and mounts and fstype != "swap":
                    mount = mounts[0]
                    system = mount in ("/", "/boot", "/boot/efi", "/usr", "/var") or fstype == "swap"
                    metadata = {
                        "fstype": fstype,
                        "transport": n.get("tran"),
                        "removable": removable,
                        "system": system,
                        "device_path": path,
                        "model": n.get("model"),
                        "size": n.get("size"),
                        "partition_type": typ,
                    }
                    found[n["uuid"]] = Device(
                        "storage", "filesystem_uuid", n["uuid"],
                        n.get("label") or n["name"], mount, metadata
                    )
                walk(n.get("children") or [], removable, path)
        walk(tree.get("blockdevices") or [])
        return list(found.values())

    def android(self):
        if not shutil.which("adb"):
            return []
        out = self.run(["adb", "devices", "-l"])
        result = []
        for line in out.splitlines()[1:]:
            f = line.split()
            if len(f) >= 2 and f[1] == "device":
                attrs = dict(x.split(":", 1) for x in f[2:] if ":" in x)
                result.append(Device(
                    "android", "adb_serial", f[0],
                    attrs.get("model", "Android").replace("_", " "),
                    metadata=attrs
                ))
        return result

    def all(self):
        return self.storage() + self.android()


def match_destination(job, devices):
    return next((
        d for d in devices
        if d.kind == "storage"
        and d.identifier == job["destination"]["device"]["uuid"]
        and d.mountpoint
        and not (d.metadata or {}).get("system", False)
    ), None)


def match_android_source(job, devices):
    return next((
        d for d in devices
        if d.kind == "android" and d.identifier == job["source"].get("device_id")
    ), None) if job["source"]["type"] == "android" else None
