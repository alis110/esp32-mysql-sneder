import tempfile
import textwrap
import unittest
from pathlib import Path

from app.config import ConfigurationError, load_config
from app.database import expand_query, pick_wincc_database


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

WINCC = """
[database]
enabled = true
engine = sqlserver
auth = windows
host = .\\WINCC
port = 0
database = auto
query = SELECT TOP (%(batch_size)s) CAST(1 AS bigint) + %(last_id)s AS id
id_column = id
batch_size = 5
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
            self.assertEqual(config.database.engine, "sqlserver")
            self.assertEqual(config.database.auth, "windows")
            self.assertEqual(config.database.host, ".\\WINCC")
            with self.assertRaises(ConfigurationError):
                load_config(self.write_config(directory, enabled="true"))

    def test_enabled_query_requires_last_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigurationError):
                load_config(self.write_config(directory, enabled="true", query="SELECT 1"))

    def test_sqlserver_windows_auth_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(textwrap.dedent(WINCC), encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.database.engine, "sqlserver")
            self.assertEqual(config.database.auth, "windows")
            self.assertEqual(config.database.host, ".\\WINCC")
            self.assertEqual(config.database.port, 0)
            self.assertEqual(config.database.database, "auto")

    def test_sqlserver_rejects_mysql_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(
                textwrap.dedent(WINCC).replace(
                    "SELECT TOP (%(batch_size)s) CAST(1 AS bigint) + %(last_id)s AS id",
                    "SELECT id FROM t WHERE id > %(last_id)s LIMIT %(batch_size)s",
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_config(path)

    def test_rejects_mysql_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(
                textwrap.dedent(
                    """
                    [database]
                    enabled = false
                    engine = mysql
                    query = SELECT 1
                    [serial]
                    port = auto
                    [runtime]
                    state_db = data/state.sqlite3
                    [logging]
                    file = logs/test.log
                    """
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_config(path)


class DatabaseHelperTests(unittest.TestCase):
    def test_expand_query_inserts_integers(self):
        sql = expand_query(
            "SELECT TOP (%(batch_size)s) id FROM t WHERE id > %(last_id)s",
            last_id=90,
            batch_size=5,
        )
        self.assertEqual(sql, "SELECT TOP (5) id FROM t WHERE id > 90")

    def test_pick_wincc_prefers_latest_fast_archive(self):
        names = [
            "master",
            "CPUPC01_WINCC#ROSHAN_TLG_F_202312202030_202412202030",
            "CPUPC01_WINCC#ROSHAN_TLG_S_202606182030_202606182030",
            "CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202604242306",
            "ROSHAN_TLG_F",
        ]
        chosen = pick_wincc_database(names)
        self.assertEqual(chosen, "CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202604242306")

    def test_pick_wincc_falls_back_to_attached_fast_name(self):
        self.assertEqual(pick_wincc_database(["master", "ROSHAN_TLG_F"]), "ROSHAN_TLG_F")

    def test_classify_and_pick_alarm_and_config(self):
        from app.database import classify_wincc_database, parse_wincc_database

        self.assertEqual(classify_wincc_database("CPUPC01_WinCC#Roshan_ALG_202808130630_202808130730"), "alg")
        self.assertEqual(classify_wincc_database("CC_Kamran_F_25_12_03_14_08_36"), "cc_cs")
        self.assertEqual(classify_wincc_database("CC_Kamran_F_25_12_03_14_08_36R"), "cc_rt")
        self.assertEqual(parse_wincc_database("auto:alg"), ("auto", "alg"))
        names = [
            "CPUPC01_WINCC#ROSHAN_TLG_F_202412202030_202604242306",
            "CPUPC01_WinCC#Roshan_ALG_202808130630_202808130730",
            "CPUPC01_WinCC#Roshan_ALG_202808130730_202808130830",
        ]
        self.assertEqual(
            pick_wincc_database(names, "alg"),
            "CPUPC01_WinCC#Roshan_ALG_202808130730_202808130830",
        )

    def test_load_shipped_wincc_template(self):
        path = Path(__file__).resolve().parents[1] / "config" / "config.wincc.ini"
        config = load_config(path)
        self.assertEqual(config.database.engine, "sqlserver")
        self.assertEqual(config.database.auth, "windows")
        self.assertIn("TagUncompressed", config.database.query)
        self.assertIn("Archive", config.database.query)

    def test_load_shipped_example_template(self):
        path = Path(__file__).resolve().parents[1] / "config" / "config.example.ini"
        config = load_config(path)
        self.assertEqual(config.database.engine, "sqlserver")
        self.assertEqual(config.database.auth, "windows")
        self.assertTrue(config.database.enabled)


if __name__ == "__main__":
    unittest.main()
