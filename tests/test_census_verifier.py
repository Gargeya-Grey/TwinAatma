"""The census verifier needs functioning public search and exact result paths."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("census_proof", SCRIPTS / "memory_census.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class CensusVerifierTests(unittest.TestCase):
    def test_missing_search_results_cannot_be_mistaken_for_exclusion(self):
        for result in ({}, {"error": "unreachable"}, {"ranked": None}, []):
            with self.subTest(result=result), self.assertRaises(ValueError):
                proof.result_paths(result)

    def test_all_public_result_buckets_are_checked(self):
        self.assertEqual(proof.result_paths({"ranked": [], "title": [{"path": "Research/generated.md"}]}), ["Research/generated.md"])
        self.assertEqual(proof.result_paths({"ranked": [{"path": "MOCs/user.md"}], "fts": [{"path": "MOCs/user.md"}]}), ["MOCs/user.md"])
        self.assertEqual(proof.result_paths({"ranked": []}), [])

    def test_generated_inventory_covers_every_public_writer(self):
        self.assertEqual(len(proof.WRITERS), 6)
        self.assertEqual(sum(len(row["outputs"]) for row in proof.WRITERS.values()), 10)
        self.assertEqual(len(proof.GENERATED_QUERIES), 10)


if __name__ == "__main__":
    unittest.main()
