import tempfile
import textwrap
import unittest
from pathlib import Path

from app.config import ConfigurationError, load_config


CONFIG = """
[database]
enabled = {enabled}
query = {query}
id_column = id
[serial]
port = auto
[runtime]
state_db = data/state.sqlite3
[logging]
file = logs/test.log
"""


class ConfigTests(unittest.TestCase):
    def write_config(self, directory, enabled="false", query="REPLACE_WITH_QUERY"):
        path = Path(directory) / "config.ini"
        path.write_text(textwrap.dedent(CONFIG.format(enabled=enabled, query=query)), encoding="utf-8")
        return path

    def test_placeholder_is_allowed_only_while_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(self.write_config(directory))
            self.assertFalse(config.database.enabled)
            with self.assertRaises(ConfigurationError):
                load_config(self.write_config(directory, enabled="true"))

    def test_enabled_query_requires_last_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigurationError):
                load_config(self.write_config(directory, enabled="true", query="SELECT 1"))


if __name__ == "__main__":
    unittest.main()
