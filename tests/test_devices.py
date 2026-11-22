import unittest
from universal_backup.devices import Device,match_destination
class Tests(unittest.TestCase):
 def test_uuid_match(self):
  j={"destination":{"device":{"uuid":"U1"}}};d=Device("storage","filesystem_uuid","U1","usb","/mnt/usb");self.assertEqual(match_destination(j,[d]),d)
 def test_wrong_uuid(self):
  j={"destination":{"device":{"uuid":"U1"}}};d=Device("storage","filesystem_uuid","U2","usb","/mnt/usb");self.assertIsNone(match_destination(j,[d]))
