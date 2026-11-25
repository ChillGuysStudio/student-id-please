import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("warehouse_roles", ROOT / "scripts/warehouse_roles.py")
roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roles)

CONTRACT = (ROOT / "docs/contracts/warehouse.md").read_text()


def contract_rows(heading):
    section = CONTRACT.split(f"### {heading}\n", 1)[1].split("\n##", 1)[0]
    return [[cell.strip() for cell in line.strip("|").split("|")]
            for line in section.splitlines() if line.startswith("| ") and "---" not in line][1:]


class WarehouseRoles(unittest.TestCase):
    def test_postgres_grants_match_the_contract(self):
        documented = {row[1].strip("`"): set(re.findall(r"`([^`]+)`", row[2])) for row in contract_rows("PostgreSQL")}
        granted = {table: set(columns.split(", ")) for _, _, tables in roles.POSTGRES.values()
                   for table, columns in tables.items()}
        self.assertEqual(granted, documented)

    def test_mongo_views_match_the_contract(self):
        documented = {row[1].strip("`"): set(re.findall(r"`([^`]+)`", row[2])) for row in contract_rows("MongoDB")}
        projected = {}
        for databases in roles.MONGO.values():
            for views in databases.values():
                for collection, projection in views.items():
                    shown = {name for name in projection if name != "_id"}
                    projected[collection] = shown | (set() if projection.get("_id") == 0 else {"_id"})
        self.assertEqual(projected, documented)

    def test_postgres_role_is_read_only_and_reset_first(self):
        script = roles.postgres_script("db", {"t": "a, b"}, "it's")
        self.assertIn("PASSWORD 'it''s'", script)
        self.assertIn("default_transaction_read_only = on", script)
        self.assertLess(script.index("REVOKE ALL ON ALL TABLES"), script.index("GRANT SELECT (a, b) ON t"))
        self.assertNotIn("GRANT SELECT ON", script)

    def test_mongo_role_reads_only_views(self):
        script = roles.mongo_script({"db": {"c": {"_id": 0, "kind": 1}}}, "p")
        self.assertIn('actions: ["find"]', script)
        self.assertIn('"warehouse_" + collection', script)

    def test_password_is_required(self):
        self.assertEqual(roles.reader_password("A=1\nWAREHOUSE_READER_PASSWORD='x=y'\n"), "x=y")
        for text in ("", "WAREHOUSE_READER_PASSWORD=\n", "WAREHOUSE_READER_PASSWORD=''\n"):
            with self.assertRaises(ValueError):
                roles.reader_password(text)

    def test_mongodb_requires_authentication(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("command: [mongod, --replSet, rs0, --keyFile, /data/configdb/replica-set.key,", compose)
        self.assertNotIn("mongodb://mongodb-1", compose)


if __name__ == "__main__":
    unittest.main()
