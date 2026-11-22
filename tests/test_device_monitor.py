import unittest
from universal_backup.devices import Device
from universal_backup.device_monitor import snapshot, diff_devices, device_key, DebouncedInventory


class DeviceMonitorTests(unittest.TestCase):
    def setUp(self):
        self.usb = Device("storage", "filesystem_uuid", "UUID-1", "Backup USB", "/media/usb")
        self.phone = Device("android", "adb_serial", "SERIAL-1", "Android")

    def test_device_key_uses_stable_identity(self):
        self.assertEqual(device_key(self.usb), ("storage", "filesystem_uuid", "UUID-1"))

    def test_detects_connection(self):
        self.assertEqual(diff_devices({}, snapshot([self.usb])), [("connected", self.usb)])

    def test_detects_disconnection(self):
        self.assertEqual(diff_devices(snapshot([self.usb]), {}), [("disconnected", self.usb)])

    def test_debounce_ignores_single_scan_disconnect(self):
        tracker = DebouncedInventory([self.usb], confirmations=2)
        self.assertEqual(tracker.update([]), [])
        self.assertEqual(tracker.update([self.usb]), [])
        self.assertIn(device_key(self.usb), tracker.stable)

    def test_debounce_confirms_disconnect(self):
        tracker = DebouncedInventory([self.usb], confirmations=2)
        self.assertEqual(tracker.update([]), [])
        self.assertEqual(tracker.update([]), [("disconnected", self.usb)])

    def test_debounce_confirms_connect(self):
        tracker = DebouncedInventory([], confirmations=2)
        self.assertEqual(tracker.update([self.phone]), [])
        self.assertEqual(tracker.update([self.phone]), [("connected", self.phone)])

    def test_debounce_confirms_mountpoint_change(self):
        mounted = Device("storage", "filesystem_uuid", "UUID-1", "Backup USB", "/mnt/backup")
        tracker = DebouncedInventory([self.usb], confirmations=2)
        self.assertEqual(tracker.update([mounted]), [])
        self.assertEqual(tracker.update([mounted]), [("changed", mounted)])


if __name__ == "__main__":
    unittest.main()
