"""Exercise coordinate persistence without touching the user's saved resource list."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resource_preferences import checked_coordinates, parse_coordinates, load_coordinates, save_coordinates, remove_coordinate


class ResourcePreferencesTests(unittest.TestCase):
    """Keep malformed input and interrupted saves from replacing a good coordinate list."""

    def test_removal_uses_latest_saved_list_and_preserves_other_entries(self):
        """Deleting one confirmed point must not overwrite newer, unrelated saved coordinates."""
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'resources.json'
            save_coordinates(((97,192),(101,134),(5,5)),path)
            self.assertEqual(remove_coordinate((97,192),path),((101,134),(5,5)))
            self.assertEqual(load_coordinates(path),((101,134),(5,5)))
            self.assertEqual(remove_coordinate((5,5),path),((101,134),))
            self.assertEqual(remove_coordinate((101,134),path),())

    def test_parse_deduplicates_and_accepts_common_separators(self):
        """Coordinates remain in user order; blank lines and Chinese commas are accepted."""
        self.assertEqual(parse_coordinates('97,192\n\n101，191\n97,192\n99 186'),
                         ((97, 192), (101, 191), (99, 186)))

    def test_invalid_and_unbounded_input_is_rejected(self):
        """An invalid line, coordinate or excessive list cannot reach persistence or dispatch."""
        for text in ('97,192,1', '-1,2', '1.5,2', 'abc', '10001,1', '123'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_coordinates(text)
        for values in (None, [(True, 2)], [(1,)], [(i, 1) for i in range(101)]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                checked_coordinates(values)

    def test_saved_list_round_trips_and_never_contains_switches_or_stock(self):
        """Restart restores coordinates only; file contents cannot enable collection."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'resources.json'
            self.assertEqual(load_coordinates(path), ())
            self.assertEqual(save_coordinates([(97, 192), (101, 191)], path), ((97, 192), (101, 191)))
            self.assertEqual(load_coordinates(path), ((97, 192), (101, 191)))
            self.assertNotIn('enabled', path.read_text(encoding='utf-8'))
            before = path.read_bytes()
            with patch('resource_preferences.os.replace', side_effect=OSError('test failure')):
                with self.assertRaises(OSError):
                    save_coordinates([(1, 2)], path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])
            path.write_text('{"version":1,"coordinates":[[1,"bad"]]}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_coordinates(path)
