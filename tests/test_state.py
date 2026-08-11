import tempfile
import unittest
from pathlib import Path

from app.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_state_survives_reopen_and_never_moves_backwards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            state = StateStore(path)
            self.assertEqual(0, state.last_success_id())
            state.mark_success(100)
            state.close()

            state = StateStore(path)
            self.assertEqual(100, state.last_success_id())
            with self.assertRaises(ValueError):
                state.mark_success(99)
            state.close()


if __name__ == "__main__":
    unittest.main()
