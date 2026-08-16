"""Regression guard: saving must work when config.json is a bind mount.

`RuntimeConfig.save()` wrote a sibling temp file and renamed it onto the
target. A single-file bind mount, the layout both the README and
docker-compose.yml.example recommend, makes that target a mount point, and
rename(2) onto a mount point fails with EBUSY. Every save from /admin was
rejected with "[Errno 16] Device or resource busy", the host file never
changed, and an orphaned config.json.*.tmp was left behind on each attempt.

A real bind mount needs root and a Linux kernel, so these tests reproduce the
only thing save() can actually observe about one: the errno rename(2) returns.

Reported as #66.
"""

import errno
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.src.config import RuntimeConfig


def _refuse(err):
    """Stand in for the kernel refusing to rename onto a mount point."""

    def raiser(*args, **kwargs):
        raise OSError(err, os.strerror(err))

    return raiser


class _TargetFile(unittest.TestCase):
    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / 'config.json'
        # The bind-mounted file always exists already: `touch config.json`
        # on the host is step one of the documented setup.
        self.path.write_text('{}\n', encoding='utf-8')

    def leftover_temp_files(self):
        return sorted(p.name for p in self.path.parent.glob('config.json.*.tmp'))


class BindMountSaveTests(_TargetFile):
    def test_settings_are_written_through_when_rename_is_refused(self):
        config = RuntimeConfig()
        config.REQUIRE_LOGIN = not config.REQUIRE_LOGIN

        with patch('os.replace', side_effect=_refuse(errno.EBUSY)):
            config.save(self.path)

        self.assertEqual(
            json.loads(self.path.read_text(encoding='utf-8')), config.to_dict()
        )

    def test_the_host_inode_survives(self):
        """Preserving it is the entire reason the mount exists.

        A save that swaps the inode writes into a file the host no longer
        sees, so the setting appears to stick until the container restarts.
        """
        before = os.stat(self.path).st_ino

        with patch('os.replace', side_effect=_refuse(errno.EBUSY)):
            RuntimeConfig().save(self.path)

        self.assertEqual(os.stat(self.path).st_ino, before)

    def test_no_temp_file_is_orphaned(self):
        with patch('os.replace', side_effect=_refuse(errno.EBUSY)):
            RuntimeConfig().save(self.path)

        self.assertEqual(self.leftover_temp_files(), [])

    def test_a_longer_previous_config_does_not_leave_a_trailing_tail(self):
        """Without truncate() the old tail survives past the new payload.

        The result parses as neither JSON nor defaults, so from_file() would
        fall back to defaults and silently discard every tuned setting.
        """
        self.path.write_text(json.dumps({'PAD': 'x' * 10000}), encoding='utf-8')

        with patch('os.replace', side_effect=_refuse(errno.EBUSY)):
            RuntimeConfig().save(self.path)

        self.assertEqual(
            json.loads(self.path.read_text(encoding='utf-8')), RuntimeConfig().to_dict()
        )

    def test_a_cross_device_target_takes_the_same_path(self):
        with patch('os.replace', side_effect=_refuse(errno.EXDEV)):
            RuntimeConfig().save(self.path)

        self.assertEqual(
            json.loads(self.path.read_text(encoding='utf-8')), RuntimeConfig().to_dict()
        )


class OrdinaryFileSaveTests(_TargetFile):
    def test_a_normal_file_is_still_replaced_atomically(self):
        """The bind-mount recovery must not cost everyone else atomicity."""
        calls = []
        real_replace = os.replace

        def spy(src, dst, *args, **kwargs):
            calls.append((str(src), str(dst)))
            return real_replace(src, dst, *args, **kwargs)

        with patch('os.replace', side_effect=spy):
            RuntimeConfig().save(self.path)

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith('.tmp'))
        self.assertEqual(calls[0][1], str(self.path))
        self.assertEqual(
            json.loads(self.path.read_text(encoding='utf-8')), RuntimeConfig().to_dict()
        )
        self.assertEqual(self.leftover_temp_files(), [])

    def test_save_creates_the_file_when_it_does_not_exist_yet(self):
        fresh = self.path.parent / 'fresh.json'

        RuntimeConfig().save(fresh)

        self.assertEqual(
            json.loads(fresh.read_text(encoding='utf-8')), RuntimeConfig().to_dict()
        )


class UnexpectedFailureTests(_TargetFile):
    def test_an_unrelated_rename_error_is_not_swallowed(self):
        """Only EBUSY and EXDEV mean "this target cannot be renamed onto".

        A permissions problem is a real failure and must still surface, or a
        read-only mount would report every save as successful.
        """
        with patch('os.replace', side_effect=_refuse(errno.EACCES)):
            with self.assertRaises(OSError) as caught:
                RuntimeConfig().save(self.path)

        self.assertEqual(caught.exception.errno, errno.EACCES)

    def test_a_failed_save_still_cleans_up_after_itself(self):
        """The reported symptom was a new config.json.*.tmp on every attempt."""
        with patch('os.replace', side_effect=_refuse(errno.EACCES)):
            with self.assertRaises(OSError):
                RuntimeConfig().save(self.path)

        self.assertEqual(self.leftover_temp_files(), [])


if __name__ == '__main__':
    unittest.main()
