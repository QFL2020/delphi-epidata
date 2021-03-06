"""Unit tests for csv_to_database.py."""

# standard library
import argparse
import unittest
from unittest.mock import MagicMock

# py3tester coverage target
__test_target__ = 'delphi.epidata.acquisition.covidcast.csv_to_database'


class UnitTests(unittest.TestCase):
  """Basic unit tests."""

  def test_get_argument_parser(self):
    """Return a parser for command-line arguments."""

    self.assertIsInstance(get_argument_parser(), argparse.ArgumentParser)

  def test_scan_upload_archive(self):
    """Scan the data directory, upload to the database, and archive."""

    def make_row(value):
      return MagicMock(
        geo_value=value,
        value=value,
        stderr=value,
        sample_size=value)

    def load_csv_impl(path, *args):
      if path == 'path/a.csv':
        # no validation errors
        yield make_row('a1')
        yield make_row('a2')
        yield make_row('a3')
      elif path == 'path/b.csv':
        # one validation error
        yield make_row('b1')
        yield None
        yield make_row('b3')
      else:
        # fail the test for any other path
        raise Exception('unexpected path')

    data_dir = 'data_dir'
    mock_database = MagicMock()
    mock_csv_importer = MagicMock()
    mock_csv_importer.find_csv_files.return_value = [
      ('path/a.csv', ('src_a', 'sig_a', 'day', 'hrr', 20200419)),
      ('path/b.csv', ('src_b', 'sig_b', 'week', 'msa', 202016)),
      # emulate a file that's named incorrectly
      ('path/c.csv', None),
    ]
    mock_csv_importer.load_csv = load_csv_impl
    mock_file_archiver = MagicMock()

    scan_upload_archive(
        data_dir,
        mock_database,
        csv_importer_impl=mock_csv_importer,
        file_archiver_impl=mock_file_archiver)

    # verify that five rows were added to the database
    self.assertEqual(mock_database.insert_or_update.call_count, 5)
    call_args_list = mock_database.insert_or_update.call_args_list
    actual_args = [args for (args, kwargs) in call_args_list]
    expected_args = [
      ('src_a', 'sig_a', 'day', 'hrr', 20200419, 'a1', 'a1', 'a1', 'a1'),
      ('src_a', 'sig_a', 'day', 'hrr', 20200419, 'a2', 'a2', 'a2', 'a2'),
      ('src_a', 'sig_a', 'day', 'hrr', 20200419, 'a3', 'a3', 'a3', 'a3'),
      ('src_b', 'sig_b', 'week', 'msa', 202016, 'b1', 'b1', 'b1', 'b1'),
      ('src_b', 'sig_b', 'week', 'msa', 202016, 'b3', 'b3', 'b3', 'b3'),
    ]
    self.assertEqual(actual_args, expected_args)

    # verify that one file was successful (a) and two failed (b, c)
    self.assertEqual(mock_file_archiver.archive_file.call_count, 3)
    call_args_list = mock_file_archiver.archive_file.call_args_list
    actual_args = [args for (args, kwargs) in call_args_list]
    expected_args = [
      ('path', 'data_dir/archive/successful/src_a', 'a.csv', True),
      ('path', 'data_dir/archive/failed/src_b', 'b.csv', False),
      ('path', 'data_dir/archive/failed/unknown', 'c.csv', False),
    ]
    self.assertEqual(actual_args, expected_args)

  def test_main_successful(self):
    """Run the main program and successfully commit changes."""

    args = MagicMock(data_dir='data', test=False)
    mock_database = MagicMock()
    mock_database.count_all_rows.return_value = 0
    mock_database_impl = lambda: mock_database
    mock_scan_upload_archive = MagicMock()

    main(
        args=args,
        database_impl=mock_database_impl,
        scan_upload_archive_impl=mock_scan_upload_archive)

    self.assertTrue(mock_scan_upload_archive.called)
    self.assertEqual(mock_scan_upload_archive.call_args[0][0], 'data')

    self.assertTrue(mock_database.connect.called)
    self.assertTrue(mock_database.disconnect.called)
    self.assertTrue(mock_database.disconnect.call_args[0][0])

  def test_main_unsuccessful(self):
    """Run the main program but don't commit changes on failure."""

    args = MagicMock(data_dir='data', test=False)
    mock_database = MagicMock()
    mock_database.count_all_rows.return_value = 0
    mock_database_impl = lambda: mock_database
    mock_scan_upload_archive = MagicMock(side_effect=Exception('testing'))

    with self.assertRaises(Exception):
      main(
          args=args,
          database_impl=mock_database_impl,
          scan_upload_archive_impl=mock_scan_upload_archive)

    self.assertTrue(mock_scan_upload_archive.called)
    self.assertEqual(mock_scan_upload_archive.call_args[0][0], 'data')

    self.assertTrue(mock_database.connect.called)
    self.assertTrue(mock_database.disconnect.called)
    self.assertFalse(mock_database.disconnect.call_args[0][0])

  def test_main_testing(self):
    """Run the main program but don't commit changes when testing."""

    args = MagicMock(data_dir='data', test=True)
    mock_database = MagicMock()
    mock_database.count_all_rows.return_value = 0
    mock_database_impl = lambda: mock_database
    mock_scan_upload_archive = MagicMock()

    main(
        args=args,
        database_impl=mock_database_impl,
        scan_upload_archive_impl=mock_scan_upload_archive)

    self.assertTrue(mock_scan_upload_archive.called)
    self.assertEqual(mock_scan_upload_archive.call_args[0][0], 'data')

    self.assertTrue(mock_database.connect.called)
    self.assertTrue(mock_database.disconnect.called)
    actual_args = mock_database.disconnect.call_args[0]
    self.assertFalse(mock_database.disconnect.call_args[0][0])
