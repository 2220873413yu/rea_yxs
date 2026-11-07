"""Keep type preferences separate from authorization to consume scouts or dispatch heroes."""
import json
import tempfile
import unittest
from pathlib import Path

from beacon_preferences import checked_types,load_types,save_types


class BeaconPreferencesTests(unittest.TestCase):
    """Validate migration defaults and atomic selection-only persistence."""

    def test_default_and_round_trip_never_save_master_switch(self):
        """An existing rescue-only installation gains no automatic permission for new types."""
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'choices.json'
            self.assertEqual(load_types(path),(1,))
            save_types((4,3,2,1,4),path)
            self.assertEqual(load_types(path),(1,2,3,4))
            self.assertEqual(set(json.loads(path.read_text(encoding='utf-8'))),{'version','types'})
            save_types((),path);self.assertEqual(load_types(path),())

    def test_invalid_types_fail_closed(self):
        """Strings, boolean aliases and unknown native types never enter the execution mask."""
        for values in ('1234',[True],[5],None,[1,'2']):
            with self.subTest(values=values),self.assertRaises(ValueError):checked_types(values)


if __name__=='__main__':unittest.main()
