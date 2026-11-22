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
                "lsblk", "-J", "--tree", "-o",
                "NAME,PATH,TYPE,FSTYPE,UUID,LABEL,MOUNTPOINTS,TRAN,RM,PKNAME,MODEL,SIZE"
            ]))
        except Exception:
            return []

        nodes = {}
        graph = {}

        def key_for(value):
            if not value:
                return None
            return str(value).rsplit("/", 1)[-1]

        def connect(left, right):
            if not left or not right:
                return
            graph.setdefault(left, set()).add(right)
            graph.setdefault(right, set()).add(left)

        def collect(items, parent=None):
            for item in items:
                name = key_for(item.get("name") or item.get("path"))
                if not name:
                    collect(item.get("children") or [], parent)
                    continue

                current = nodes.setdefault(name, {})
                for field, value in item.items():
                    if field == "children" or value is None:
                        continue
                    if field == "mountpoints":
                        existing = current.setdefault(field, [])
                        values = value if isinstance(value, list) else [value]
                        for mount in values:
                            if mount not in existing:
                                existing.append(mount)
                    elif value not in ("", [], {}):
                        current[field] = value

                graph.setdefault(name, set())
                connect(name, parent)
                connect(name, key_for(item.get("pkname")))
                collect(item.get("children") or [], name)

        collect(tree.get("blockdevices") or [])

        def component(start):
            seen = {start}
            pending = [start]
            while pending:
                current = pending.pop()
                for neighbour in graph.get(current, ()):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        pending.append(neighbour)
            return seen

        def is_flag_set(value):
            if isinstance(value, str):
                return value.strip().casefold() in ("1", "true", "yes", "on")
            return bool(value)

        def mountpoints(node):
            values = node.get("mountpoints") or []
            if isinstance(values, str):
                values = [values]
            return [value for value in values if isinstance(value, str) and value]

        virtual_disk_names = ("loop", "ram", "zram", "fd")
        physical_disks = {
            name for name, node in nodes.items()
            if node.get("type") == "disk" and not name.startswith(virtual_disk_names)
        }

        # A system mount or active swap makes every physical disk in its
        # dependency component a system disk. This includes all PVs backing
        # an LVM/crypt/RAID root filesystem.
        system_disks = set()
        system_mountpoints = {"/", "/boot", "/boot/efi", "/usr", "/var"}
        for name, node in nodes.items():
            mounts = mountpoints(node)
            is_system_mount = any(mount in system_mountpoints for mount in mounts)
            is_swap = str(node.get("fstype") or "").casefold() == "swap" or "[SWAP]" in mounts
            if is_system_mount or is_swap:
                system_disks.update(component(name) & physical_disks)

        found = {}
        for name, node in nodes.items():
            typ = node.get("type")
            if typ in ("loop", "rom") or not node.get("uuid"):
                continue
            mounts = [mount for mount in mountpoints(node) if mount != "[SWAP]"]
            fstype = node.get("fstype")
            if not mounts or str(fstype or "").casefold() == "swap":
                continue

            related = component(name)
            disk_names = sorted(related & physical_disks)
            disk_nodes = [nodes[disk_name] for disk_name in disk_names]
            # If lsblk cannot establish physical ancestry, do not offer the
            # filesystem as a destination: the safe classification is unknown.
            system = (
                mounts[0] in system_mountpoints
                or not disk_names
                or bool(set(disk_names) & system_disks)
            )
            removable = is_flag_set(node.get("rm")) or any(
                is_flag_set(disk.get("rm")) for disk in disk_nodes
            )
            transports = {
                str(disk.get("tran")).casefold()
                for disk in disk_nodes if disk.get("tran")
            }
            transport = node.get("tran")
            if not transport and len(transports) == 1:
                transport = next(iter(transports))

            path = node.get("path") or ("/dev/" + name)
            metadata = {
                "fstype": fstype,
                "transport": transport,
                "removable": removable,
                "system": system,
                "device_path": path,
                "physical_disks": [nodes[disk_name].get("path") or "/dev/" + disk_name
                                   for disk_name in disk_names],
                "model": node.get("model"),
                "size": node.get("size"),
                "partition_type": typ,
            }
            identifier = str(node["uuid"])
            found[identifier] = Device(
                "storage", "filesystem_uuid", identifier,
                node.get("label") or name, mounts[0], metadata
            )
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
