import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from universal_backup.devices import Device, DeviceInventory, match_destination


class Tests(unittest.TestCase):
    def test_uuid_match(self):
        job = {"destination": {"device": {"uuid": "U1"}}}
        device = Device("storage", "filesystem_uuid", "U1", "usb", "/mnt/usb")
        self.assertEqual(match_destination(job, [device]), device)

    def test_wrong_uuid(self):
        job = {"destination": {"device": {"uuid": "U1"}}}
        device = Device("storage", "filesystem_uuid", "U2", "usb", "/mnt/usb")
        self.assertIsNone(match_destination(job, [device]))

    def _inventory(self, blockdevices):
        payload = json.dumps({"blockdevices": blockdevices})

        def runner(_args, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=payload, stderr="")

        with patch("universal_backup.devices.shutil.which", return_value="/usr/bin/lsblk"):
            return DeviceInventory(runner=runner).storage()

    def test_all_partitions_on_os_disk_are_ineligible(self):
        sdc = {
            "name": "sdc", "path": "/dev/sdc", "type": "disk", "rm": False,
            "tran": "sata", "model": "System SSD", "size": "931G",
            "children": [
                {"name": "sdc1", "path": "/dev/sdc1", "type": "part", "pkname": "sdc",
                 "fstype": "vfat", "uuid": "EFI-UUID", "mountpoints": ["/boot/efi"], "rm": False},
                {"name": "sdc2", "path": "/dev/sdc2", "type": "part", "pkname": "sdc",
                 "fstype": "ext4", "uuid": "ROOT-UUID", "mountpoints": ["/"], "rm": False},
                {"name": "sdc3", "path": "/dev/sdc3", "type": "part", "pkname": "sdc",
                 "fstype": "swap", "mountpoints": ["[SWAP]"], "rm": False},
                {"name": "sdc4", "path": "/dev/sdc4", "type": "part", "pkname": "sdc",
                 "fstype": "ext4", "uuid": "SRV-UUID", "mountpoints": ["/srv"], "rm": False},
            ],
        }
        sda = {
            "name": "sda", "path": "/dev/sda", "type": "disk", "rm": False,
            "tran": "usb", "model": "Expansion HDD", "size": "3.6T",
            "children": [
                {"name": "sda1", "path": "/dev/sda1", "type": "part", "pkname": "sda",
                 "fstype": "ext4", "uuid": "STORAGE-UUID", "mountpoints": ["/storage"], "rm": False},
            ],
        }
        sdb = {
            "name": "sdb", "path": "/dev/sdb", "type": "disk", "rm": True,
            "tran": "usb", "model": "Ventoy", "size": "115G",
            "children": [
                {"name": "sdb1", "path": "/dev/sdb1", "type": "part", "pkname": "sdb",
                 "fstype": "exfat", "uuid": "VENTOY-UUID", "mountpoints": ["/run/media/fury/Ventoy"], "rm": True},
            ],
        }

        devices = {device.identifier: device for device in self._inventory([sdc, sda, sdb])}
        self.assertTrue(devices["ROOT-UUID"].metadata["system"])
        self.assertTrue(devices["EFI-UUID"].metadata["system"])
        self.assertTrue(devices["SRV-UUID"].metadata["system"])
        self.assertEqual(devices["SRV-UUID"].metadata["physical_disks"], ["/dev/sdc"])
        self.assertFalse(devices["STORAGE-UUID"].metadata["system"])
        self.assertEqual(devices["STORAGE-UUID"].metadata["physical_disks"], ["/dev/sda"])
        self.assertTrue(devices["VENTOY-UUID"].metadata["removable"])

        job = {"destination": {"device": {"uuid": "SRV-UUID"}}}
        self.assertIsNone(match_destination(job, list(devices.values())))
        job["destination"]["device"]["uuid"] = "STORAGE-UUID"
        self.assertEqual(match_destination(job, list(devices.values())).identifier, "STORAGE-UUID")

    def test_lvm_root_marks_other_partitions_on_same_disk_as_system(self):
        system_disk = {
            "name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "rm": False,
            "children": [
                {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "type": "part", "pkname": "nvme0n1",
                 "children": [
                     {"name": "cryptroot", "path": "/dev/mapper/cryptroot", "type": "crypt", "pkname": "nvme0n1p3",
                      "children": [
                          {"name": "vg-root", "path": "/dev/mapper/vg-root", "type": "lvm", "pkname": "cryptroot",
                           "fstype": "ext4", "uuid": "LVM-ROOT", "mountpoints": ["/"]},
                      ]},
                 ]},
                {"name": "nvme0n1p4", "path": "/dev/nvme0n1p4", "type": "part", "pkname": "nvme0n1",
                 "fstype": "ext4", "uuid": "LVM-DATA", "mountpoints": ["/srv"]},
            ],
        }
        devices = {device.identifier: device for device in self._inventory([system_disk])}
        self.assertTrue(devices["LVM-ROOT"].metadata["system"])
        self.assertTrue(devices["LVM-DATA"].metadata["system"])
        self.assertEqual(devices["LVM-DATA"].metadata["physical_disks"], ["/dev/nvme0n1"])

    def test_raid_root_marks_all_member_disks_as_system(self):
        sda = {
            "name": "sda", "path": "/dev/sda", "type": "disk", "rm": False,
            "children": [{
                "name": "sda1", "path": "/dev/sda1", "type": "part", "pkname": "sda",
                "children": [{
                    "name": "md0", "path": "/dev/md0", "type": "raid1", "fstype": "ext4",
                    "uuid": "RAID-ROOT", "mountpoints": ["/"],
                }],
            }],
        }
        sdb = {
            "name": "sdb", "path": "/dev/sdb", "type": "disk", "rm": False,
            "children": [
                {"name": "sdb1", "path": "/dev/sdb1", "type": "part", "pkname": "sdb",
                 "children": [{"name": "md0", "path": "/dev/md0", "type": "raid1"}]},
                {"name": "sdb2", "path": "/dev/sdb2", "type": "part", "pkname": "sdb",
                 "fstype": "ext4", "uuid": "SECOND-PARTITION", "mountpoints": ["/backup"]},
            ],
        }
        devices = {device.identifier: device for device in self._inventory([sda, sdb])}
        self.assertEqual(set(devices["RAID-ROOT"].metadata["physical_disks"]), {"/dev/sda", "/dev/sdb"})
        self.assertTrue(devices["SECOND-PARTITION"].metadata["system"])

    def test_unknown_physical_ancestry_is_ineligible(self):
        node = {
            "name": "dm-9", "path": "/dev/dm-9", "type": "lvm", "fstype": "ext4",
            "uuid": "UNKNOWN-UUID", "mountpoints": ["/mnt/unknown"],
        }
        devices = self._inventory([node])
        self.assertTrue(devices[0].metadata["system"])
        self.assertEqual(devices[0].metadata["physical_disks"], [])
