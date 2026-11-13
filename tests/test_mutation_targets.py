"""Every seeded defect of `tests/mutation_check.py` still names code that exists.

The mutation check puts a known defect back and expects one scenario to fail. It finds
the place by exact text. When that code is rewritten, the defect is no longer applied,
and the check runs only in CI. This test finds a moved text in the ordinary suite.
"""
from __future__ import annotations

import importlib.util
import unittest

from support import ROOT


def _mutation_check():
    spec = importlib.util.spec_from_file_location("mutation_check", ROOT / "tests" / "mutation_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MutationTargets(unittest.TestCase):
    def test_every_seeded_defect_finds_its_place_once(self):
        module = _mutation_check()
        moved = []
        for entry in module.MUTATIONS:
            scenario, edits = module._normalise(entry)
            texts: dict[str, str] = {}
            for relative, fixed, broken in edits:
                # Read as the driver reads: line ends become one form. The edits of one
                # defect are applied one after the other.
                current = texts.get(relative)
                if current is None:
                    current = (ROOT / relative).read_text(encoding="utf-8")
                if current.count(fixed) != 1:
                    moved.append(f"{scenario}: {relative} holds the text {current.count(fixed)} times: "
                                 f"{fixed.strip().splitlines()[0][:70]}")
                    break
                texts[relative] = current.replace(fixed, broken, 1)
        self.assertEqual(moved, [], "rewrite these seeded defects in tests/mutation_check.py, then run it")


if __name__ == "__main__":
    unittest.main()
