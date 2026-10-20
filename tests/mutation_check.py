"""Prove the scorecard can see the bugs it claims to protect against.

A green spec written by the same author as the code is decoration. For each finding, put
the *bug* back in a scratch copy and confirm the matching scenario goes red. A scenario
that stays green under its own bug is not a check.

    python tests/mutation_check.py

Every mutation is a real defect a reviewer found, reverted in a temporary copy of the
tree. Nothing is written to the working copy: only toolkit and test inputs are copied and
discarded, and each file is restored immediately after its scenario has run.
"""
from __future__ import annotations

import os
import json
import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (scenario id, file, exact text in the fixed tree, replacement that reintroduces the bug)
MUTATIONS = [
    (
        # Round 11 CRITICAL: preview unvalidated file metadata despite a signed ledger.
        "approval.screen_matches_the_ledger",
        "knowledgeos/gate.py",
        '''    validated = _validated_proposal(self_path, text, row)
    if validated.get("error"):
        return validated
    return {
        "path": path,''',
        '''    patch = extract_proposed(text)
    if patch is None:
        return {"error": "proposal must contain exactly one ```markdown block"}
    section = str(row.get("section") or "")
    mode = str(row.get("mode") or "replace")
    for _line in text.splitlines():
        if _line.startswith("proposal_section:"):
            section = _line.split(":", 1)[1].strip()
        if _line.startswith("proposal_mode:"):
            mode = _line.split(":", 1)[1].strip()
    validated = {"patch": patch, "section": section, "mode": mode}
    return {
        "path": path,''',
    ),
    (
        # Round 11: leave the agent-supplied rationale verbatim in the proposal body.
        "approval.body_cannot_read_as_metadata",
        "knowledgeos/gate.py",
        '''    for line in text.splitlines():
        if line.startswith("proposal_") or line.startswith("---"):
            out.append("    " + line)
        else:
            out.append(line)''',
        '''    for line in text.splitlines():
        out.append(line)''',
    ),
    (
        # Round 11 MEDIUM: accept the ordinary word for a destructive waiver too.
        "approval.destructive_waiver_is_confirmed_separately",
        "knowledgeos/__main__.py",
        '        accepted = {"yes-wipe"}',
        '        accepted = {"y", "yes", "yes-wipe"}',
    ),
    (
        # Round 11 HIGH: skip the hash once the budget is spent.
        "reads.same_size_same_mtime_edit_is_seen",
        "knowledgeos/indexer.py",
        """            hashed += info.st_size
            signature = _file_signature(path)""",
        """            if hashed + info.st_size > hash_budget_bytes:
                continue
            hashed += info.st_size
            signature = _file_signature(path)""",
    ),
    (
        # Round 11 HIGH: serve every row straight from the index again, so a removed tag
        # is still returned. Reverting only the snippet refresh is not enough — the
        # survival test below it still drops the row — so the whole refresh goes.
        "reads.removed_metadata_is_not_served",
        "knowledgeos/memory.py",
        """        out: list[dict[str, Any]] = []
        matcher = _FtsMatcher(query, context=context)""",
        """        return [dict(row) for row in rows]
        out: list[dict[str, Any]] = []
        matcher = _FtsMatcher(query, context=context)""",
    ),
    (
        # Round 11 LOW: store the (prompt, key) tuple again.
        "autopilot.session_end_prompt_is_a_string",
        "knowledgeos/memory.py",
        "        soft, soft_key = soft_prompt_for_human(ops, orphan_unsaved=False, asked=asked)",
        "        soft = soft_prompt_for_human(ops, orphan_unsaved=False, asked=asked)\n        soft_key = None",
    ),
    (
        # Round 11 LOW: a missing identity section is only a warning again.
        "ops.doctor_fails_a_missing_identity_section",
        "knowledgeos/doctor.py",
        """            if absent:
                passed = False""",
        """            if absent:
                pass""",
    ),
    # --- round twelve -------------------------------------------------------
    (
        # Round 12: revert the stem fix — a plain substring test instead of the index's
        # own tokenizer, so "running" no longer matches "run".
        "reads.stemmed_query_survives_a_locked_index",
        "knowledgeos/memory.py",
        """            row = self.conn.execute(
                "SELECT count(*) FROM t WHERE t MATCH ?", (self.query,)
            ).fetchone()
            return bool(row and row[0])""",
        """            return self.raw.lower() in (text or "").lower()""",
    ),
    (
        # Revert both fresh-row metadata and the independent project-file filter.
        "reads.decisions_use_the_file_not_the_index",
        [
            (
                "knowledgeos/memory.py",
                """        rows = self._refresh_rows(self._live_rows(rows), "")
        # `type` was the one filter still applied only in SQL.""",
                """        rows = self._live_rows(rows)
        # `type` was the one filter still applied only in SQL.""",
            ),
            (
                "knowledgeos/memory.py",
                '''                try:
                    text = self._resolve(str(row.get("path", ""))).read_text(
                        encoding="utf-8", errors="replace"
                    )
                except (OSError, ValueError):
                    continue
                frontmatter, _body = split_frontmatter(text)
                value = frontmatter.get("project") or ""''',
                '''                value = row.get("project") or ""''',
            ),
        ],
    ),
    (
        # Revert the related fix: never take the file-based branch.
        "reads.related_drops_a_removed_link",
        "knowledgeos/memory.py",
        '            "related": self._related_from_files(rel, hops, limit, warnings=warnings),',
        '            "related": self._related_from_files(rel, hops, 0, warnings=warnings),',
    ),
    (
        # Revert the line-ending fix: "any CRLF present" decides.
        "reads.one_stray_crlf_does_not_rewrite_the_file",
        "knowledgeos/textio.py",
        '    ending = dominant_newline(original).encode()',
        '    write_exact(path, text, "\\r\\n" if b"\\r\\n" in original else "\\n")\n    return',
    ),
    (
        # Revert the manifest signature: trust whatever JSON is on disk.
        "reads.an_unsigned_manifest_is_not_trusted",
        "knowledgeos/indexer.py",
        """    stored = data.get("mac")
    expected = _manifest_mac(data)
    if not stored or not expected:""",
        """    return data
    stored = data.get("mac")
    expected = _manifest_mac(data)
    if not stored or not expected:""",
    ),
    (
        # Round 12 CRITICAL: quote the indexed body again instead of the note.
        "truth.forged_index_text_is_never_quoted",
        [
            (
                "knowledgeos/memory.py",
                """                if "snippet" in updated:
                    # Rebuilt from the file, never from the index.""",
                """                if False:
                    # Rebuilt from the file, never from the index.""",
            ),
            (
                "knowledgeos/indexer.py",
                """    if expected_index and index_state(db_path) == "ok":""",
                """    if False and expected_index and index_state(db_path) == "ok":""",
            ),
        ],
    ),
    (
        # Round 12 CRITICAL: stop verifying index rows against the notes on rebuild.
        # The body-only corroboration this used to revert is gone (round 13's hole); the
        # claim is now held by the digest, so the digest is what gets reverted. A forged
        # body then survives forever because every rebuild says "unchanged".
        "truth.a_forged_index_row_cannot_hide_a_note",
        "knowledgeos/indexer.py",
        """    if expected_index and index_state(db_path) == "ok":""",
        """    if False and expected_index and index_state(db_path) == "ok":""",
    ),
    (
        # Round 12 CRITICAL: drop the digest, so a tampered index reads as fresh.
        "truth.deleted_index_rows_are_repaired",
        "knowledgeos/indexer.py",
        """    if expected_index and index_state(db_path) == "ok":""",
        """    if False and expected_index and index_state(db_path) == "ok":""",
    ),
    (
        # Round 12 HIGH: let the pending-outcome filter run on index columns again.
        "truth.forged_status_cannot_reopen_a_closed_decision",
        "knowledgeos/evolution.py",
        """        if outcome not in ("", "pending"):
            continue""",
        """        if False:
            continue""",
    ),
    (
        # Round 12 HIGH: put the SQL predicate back, so a forged column decides.
        "truth.the_closed_decision_is_not_asked_about",
        [
            (
                "knowledgeos/evolution.py",
                "            SELECT title, path, type, outcome_status, review_after, lesson, updated\n"
                "            FROM notes\n            WHERE type = 'decision' AND path NOT LIKE 'Templates/%'",
                "            SELECT title, path, type, outcome_status, review_after, lesson, updated\n"
                "            FROM notes\n            WHERE type = 'decision' AND path NOT LIKE 'Templates/%'\n"
                "              AND (IFNULL(outcome_status,'') = '' OR outcome_status = 'pending')",
            ),
            (
                "knowledgeos/evolution.py",
                """        if outcome not in ("", "pending"):
            continue""",
                """        if False:
            continue""",
            ),
        ],
    ),
    (
        # Round 12 LOW: admit templates at both the note census and decision query.
        "truth.a_decision_template_is_not_a_decision",
        [
            (
                "knowledgeos/memory.py",
                "            \"WHERE type = 'decision' AND path NOT LIKE 'Templates/%'\"",
                "            \"WHERE type = 'decision'\"",
            ),
            (
                "knowledgeos/indexer.py",
                '''            if current == vault and name == "Templates":''',
                '''            if False:''',
            ),
        ],
    ),
    (
        # Round 12 LOW: do not label a frozen-index answer.
        "truth.a_frozen_index_says_so",
        "knowledgeos/memory.py",
        """        return self._note_frozen({"count": len(rows), "decisions": rows})""",
        """        return {"count": len(rows), "decisions": rows}""",
    ),
    (
        # Round 12 MEDIUM: `mkdir` again, so a file at the state path raises.
        "ops.the_state_folder_must_be_a_folder",
        [
            (
                "knowledgeos/vaultstate.py",
                """    if folder.exists() and not folder.is_dir():""",
                """    if False:""",
            ),
            (
                "knowledgeos/doctor.py",
                """    if state_folder.exists() and not state_folder.is_dir():""",
                """    if False:""",
            ),
            (
                "knowledgeos/doctor.py",
                '''        except PolicyError:
            print("  [ERROR] Remembering policy is unavailable; index coverage could not be checked.")
            passed = False''',
                '''        except PolicyError:
            print("  [WARNING] Index coverage could not be checked; continuing.")''',
            ),
        ],
    ),
    (
        # Round 12 MEDIUM: bypass both binding reads and key the ledger on the marker.
        "identity.rewriting_the_vault_marker_cannot_orphan_proposals",
        [
            (
                "knowledgeos/gate.py",
                """    bound = _read_bindings().get(resolved)
    if bound:
        return bound
    stable = vault_id(vault)""",
                """    bound = None
    stable = vault_id(vault)""",
            ),
            (
                "knowledgeos/gate.py",
                "    return _remember_binding(resolved, key)",
                "    return key",
            ),
        ],
    ),
    (
        # Revert the frozen-index notice.
        "reads.a_frozen_index_says_so",
        [
            ("knowledgeos/memory.py",
             '''        if self.index_locked and not self.index_blocked:''',
             '''        if False:'''),
            ("knowledgeos/memory.py",
             '''        elif self.index_locked:''',
             '''        elif False:'''),
        ],
    ),

    # --- round thirteen -----------------------------------------------------
    (
        # Round 13 CRITICAL: serve metadata from the index again instead of the note.
        "truth.a_forged_metadata_column_is_not_served",
        "knowledgeos/memory.py",
        """                _refresh_display_fields(updated, frontmatter, path, text)""",
        """                pass""",
    ),
    (
        # Round 13 CRITICAL: let the capture fast path re-sign a digest it never verified.
        # The read path is the second line of defence, so both go.
        "truth.a_capture_cannot_bless_a_forged_index",
        [
            (
                "knowledgeos/indexer.py",
                """    if current_digest != expected_digest:
        return rebuild_index(vault)""",
                """    pass""",
            ),
            (
                "knowledgeos/memory.py",
                """                _refresh_display_fields(updated, frontmatter, path, text)""",
                """                pass""",
            ),
        ],
    ),
    (
        # Round 13 HIGH: re-test metadata hits with the full-text matcher and lose
        # prefixes (`Depl` no longer finds `Deploy`, `alph` no longer finds the `alpha`
        # tag). That is the only survival rule for metadata, so it is one edit.
        "reads.a_prefix_still_finds_the_note",
        "knowledgeos/memory.py",
        """                    supported = any(field_contains(field) for field in metadata_buckets)""",
        """                    supported = matcher.matches(text)""",
    ),
    (
        # Round 13 HIGH: reconcile only the paths `notes` knows about, orphaning rows.
        # The digest guard is mutated too, and deliberately: on its own it escalates the
        # capture to a rebuild and repairs every orphan before this code is reached, so
        # reverting the reconcile alone is unobservable. One finding, one mutation — but
        # the mutation has to remove *every* mechanism holding the claim.
        "truth.a_deleted_index_row_is_repaired_by_a_capture",
        [
            (
                "knowledgeos/indexer.py",
                """    if current_digest != expected_digest:
        return rebuild_index(vault)""",
                """    pass""",
            ),
            (
                "knowledgeos/indexer.py",
                """            for path in _indexed_paths(cur):""",
                """            for path in {r[0] for r in cur.execute("SELECT path FROM notes")}:""",
            ),
        ],
    ),
    (
        # Round 13 HIGH: the SQLite boundary no longer rejects a directory as its file.
        "ops.a_directory_where_the_index_belongs_is_an_error",
        "knowledgeos/database.py",
        """        if not stat.S_ISREG(info.st_mode):""",
        """        if False:""",
    ),
    (
        # Round 13 HIGH, second half: `index_state` proves the database takes a write lock
        # but not that it can answer a search, so a `notes_fts` that is an ordinary table is
        # reported `ok` and every search comes back empty.
        "ops.a_directory_where_the_index_belongs_is_an_error",
        "knowledgeos/indexer.py",
        '''    return "ok" if index_schema_problem(db_path) is None else "corrupt"''',
        '''    return "ok"''',
    ),
    (
        # Round 13 MEDIUM: flatten every line to the file's dominant ending.
        "reads.approving_one_line_keeps_every_other_line_ending",
        "knowledgeos/gate.py",
        """    write_preserving_endings(path, text)""",
        """    from knowledgeos.textio import atomic_write, dominant_newline

    original = b""
    with contextlib.suppress(OSError):
        original = path.read_bytes()
    atomic_write(path, text, dominant_newline(original) if original else "\\n")""",
    ),
    (
        # Round 13 LOW: an undecidable query silently counts as a match, so a removed
        # `---` tag is still served.
        "reads.an_undecidable_query_does_not_resurrect_a_row",
        "knowledgeos/memory.py",
        """                        supported = matcher.verdict(text) is True""",
        """                        supported = matcher.matches(text)""",
    ),

    # --- round fourteen -----------------------------------------------------
    (
        # Round 14 CRITICAL: hand a YAML list straight to sqlite3, which fails the whole
        # rebuild for every note in the vault.
        "truth.a_yaml_list_property_does_not_break_the_index",
        "knowledgeos/indexer.py",
        '''            _as_text(fm.get("updated") or ""),
            _as_text(fm.get("description") or ""),''',
        '''            _as_text(fm.get("updated") or ""),
            fm.get("description") or "",''',
    ),
    (
        # Round 14 CRITICAL: re-test only the frontmatter, so a title that lives in the
        # H1 or the filename is found by the index and then dropped by the refresh.
        "reads.a_title_in_the_filename_or_h1_is_found_and_shown",
        "knowledgeos/memory.py",
        """                        if field == "title":
                            return needle in derived_title.lower()""",
        """                        if False:
                            return needle in derived_title.lower()""",
    ),
    (
        # Round 14 HIGH: `doctor` announces an index healthy without checking that it
        # holds the vault, so a 0-row index in a 41-note vault passes.
        "ops.an_incomplete_index_is_not_called_healthy",
        "knowledgeos/doctor.py",
        '''        coverage = index_coverage_problem(vault)''',
        '''        coverage = None''',
    ),
    (
        # Round 14 MEDIUM: rebuild silently when the manifest carries no digest.
        "autopilot.an_absent_digest_says_it_rebuilt",
        "knowledgeos/indexer.py",
        '''        counts["rebuilt"] = "no_signed_digest"''',
        '''        pass''',
    ),
    (
        # Round 14 MEDIUM: let a new line keep the bare `\\n` it was split with, so a CRLF
        # file gains one LF line per approval.
        "reads.approving_one_line_keeps_the_files_line_ending",
        "knowledgeos/textio.py",
        '''                out.append(line[:-1] + ending if line.endswith(b"\\n") else line)''',
        '''                out.append(line)''',
    ),
    (
        # Round 14 MEDIUM: hash `str(value)` with no type tag, so NULL and the word None
        # collide and `UPDATE ... SET description = 'None'` is invisible to the digest.
        # One edit, because the tag, the length prefix and the None branch are one
        # encoding: reverting only the None branch still leaves the two values distinct.
        "reads.the_digest_tells_null_from_the_word_none",
        "knowledgeos/indexer.py",
        """            if value is None:
                digest.update(b"N")
            else:
                if isinstance(value, bytes):
                    tag, payload = b"B", value
                elif isinstance(value, int):
                    tag, payload = b"I", str(value).encode("utf-8", "replace")
                elif isinstance(value, float):
                    tag, payload = b"F", value.hex().encode("ascii")
                else:
                    tag, payload = b"S", str(value).encode("utf-8", "replace")
                digest.update(tag)
                digest.update(str(len(payload)).encode())
                digest.update(b":")
                digest.update(payload)
            digest.update(b"\\x00")""",
        """            digest.update(str(value).encode())
            digest.update(b"\\x00")""",
    ),
    (
        "autopilot.a_failed_rebuild_names_the_fault_and_recovers",
        "knowledgeos/memory.py",
        '''        if self.index_blocked:
            payload["index_frozen"] = True''',
        '''        if False:
            payload["index_frozen"] = True''',
    ),
    (
        "reads.entity_ids_come_from_the_note",
        "knowledgeos/memory.py",
        '''        "lesson",
        "entity_id",
    ):''',
        '''        "lesson",
    ):''',
    ),
    (
        "vault.index_candidates_cannot_escape_the_sandbox",
        [
            (
                "knowledgeos/memory.py",
                '''                    path = self._resolve(str(row.get("path", "")))''',
                '''                    path = self.vault / str(row.get("path", ""))''',
            ),
            (
                "knowledgeos/memory.py",
                '''                    text = RememberingPolicy(self.vault).read(path, historical=False)''',
                '''                    text = path.read_text(encoding="utf-8", errors="replace")''',
            ),
        ],
    ),
    (
        "approval.disjoint_edits_preserve_untouched_bytes",
        "knowledgeos/textio.py",
        '''            out.extend(old_lines[i:j])''',
        '''            out.extend(line.replace(b"\\n", b"\\r\\n") for line in new_lines[k:l])''',
    ),
    (
        "approval.a_failed_write_preserves_the_original",
        "knowledgeos/textio.py",
        '''    atomic_write_bytes(path, payload)''',
        '''    path.write_bytes(payload)''',
    ),
    (
        "ops.a_missing_fulltext_index_is_not_healthy",
        "knowledgeos/indexer.py",
        '''    if indexed != fulltext:''',
        '''    if False:''',
    ),
    (
        "ops.a_comment_is_not_a_fulltext_table",
        [
            (
                "knowledgeos/indexer.py",
                '''        if fts_kind != "table" or not re.search(r"\\bUSING\\s+fts5\\s*\\(", fts_sql, re.I):''',
                '''        if fts_kind != "table" or "fts5" not in fts_sql.lower():''',
            ),
            (
                "knowledgeos/indexer.py",
                '''        conn.execute("SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1", ("schema_probe",)).fetchone()''',
                '''        pass''',
            ),
        ],
    ),
    (
        "autopilot.a_partial_rebuild_is_not_success",
        "knowledgeos/memory.py",
        '''            failed = counts.get("failed") or []''',
        '''            failed = []''',
    ),
    (
        "reads.drift_uses_the_files_during_a_blocked_rebuild",
        "knowledgeos/memory.py",
        '''        result["source"] = "index_updated"
        rows = self._refresh_rows(self._live_rows(rows), "")''',
        '''        result["source"] = "index_updated"
        rows = self._live_rows(rows)''',
    ),
    (
        "reads.id_resolution_verifies_the_file",
        "knowledgeos/memory.py",
        '''        matches: list[Path] = []''',
        '''        cache = sqlite3.connect(self.db_path)
        try:
            row = cache.execute("SELECT path FROM notes WHERE entity_id = ?", (path_or_id,)).fetchone()
        finally:
            cache.close()
        if row:
            return self._resolve(row[0])
        matches: list[Path] = []''',
    ),
    (
        "reads.duplicate_ids_are_not_resolved_arbitrarily",
        "knowledgeos/memory.py",
        '''        return matches[0] if len(matches) == 1 else None''',
        '''        return matches[0] if matches else None''',
    ),
    (
        "reads.pending_outcomes_requires_a_real_decision",
        "knowledgeos/evolution.py",
        '''        if row.get("type") != "decision":
            continue
        outcome = str(row.get("outcome_status") or "").strip()''',
        '''        if False:
            continue
        outcome = str(row.get("outcome_status") or "").strip()''',
    ),
    (
        "autopilot.failed_quarantine_is_not_success",
        [
            ("knowledgeos/indexer.py",
             '''            if backup is None:
                raise OSError("The unusable note index could not be moved aside; it may still be open")
            print(f"Moved unusable index to {backup.name}", file=sys.stderr)''',
             '''            pass'''),
            ("knowledgeos/indexer.py",
             '''        if final_state != "ok":''',
             '''        if False:'''),
        ],
    ),
    (
        "autopilot.list_lessons_can_be_proposed",
        "knowledgeos/evolution.py",
        '''    lesson = _as_text(fm.get("lesson")).strip()''',
        '''    lesson = (fm.get("lesson") or "").strip()''',
    ),
    (
        "reads.timeline_keeps_recently_created_notes",
        "knowledgeos/memory.py",
        '''        rows = [row for row in rows if max(str(row.get("created") or ""), str(row.get("updated") or "")) >= since]''',
        '''        rows = [row for row in rows if str(row.get("updated") or "") >= since]''',
    ),
]


def _normalise(entry):
    """One mutation is either a single (file, old, new) edit or a list of them.

    Round twelve's CRITICAL is held by two mechanisms: the index is checked against the
    note *and* the quoted text is re-derived from it. Reverting either alone leaves the
    other holding the line, so a single-edit mutation would report BLIND against a claim
    that is genuinely protected. A finding fixed in two places is reverted in both.
    """
    scenario_id, payload = entry[0], entry[1:]
    if payload and isinstance(payload[0], (list, tuple)):
        return scenario_id, list(payload[0])
    return scenario_id, [payload]


def make_copy(destination: pathlib.Path) -> None:
    """Copy only the toolkit needed by scenarios, never private vault or task data."""
    destination.mkdir(parents=True, exist_ok=False)
    directories = ("knowledgeos", "tests", "Templates", ".cursor")
    files = ("AGENTS.md", "README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md",
             "pyproject.toml", "setup.py", "MANIFEST.in", "pyinstaller.spec",
             "knowledgeos.config.example.json")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".knowledgeos", "_assets")
    for name in directories:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, destination / name, ignore=ignore)
    for name in files:
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, destination / name)


def score_of(copy: pathlib.Path, only: str = "") -> tuple[int, str]:
    # make_copy excludes caches. Keep every child from creating one: timestamp
    # bytecode caches can reuse a preceding mutation with the same size/mtime.
    argv = [sys.executable, "-B", str(copy / "tests" / "score.py"), "--json"]
    if only:
        argv += ["--only", only]
    proc = subprocess.run(
        argv,
        cwd=str(copy),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout if proc.stdout.strip() else proc.stderr or ""


def _card(output: str) -> dict | None:
    """Require one complete scorecard; noise is a harness fault, not evidence."""
    try:
        candidate = json.loads(output)
    except ValueError:
        return None
    if not isinstance(candidate, dict):
        return None
    if not isinstance(candidate.get("failures"), list):
        return None
    if not isinstance(candidate.get("dimensions"), dict):
        return None
    return candidate


def verdict_of(output: str, scenario_id: str) -> str | None:
    """The verdict the scorecard recorded for one scenario, or None if it never ran."""
    card = _card(output)
    if card is None:
        return None
    for item in card.get("failures") or []:
        if item.get("scenario") == scenario_id:
            return item.get("verdict")
    if scenario_id in (card.get("passing") or []):
        return "PASS"
    return None


def classify_result(code: int, output: str, scenario_id: str) -> str:
    """Only an assertion FAIL for this scenario, with exit 1, catches a mutation."""
    card = _card(output)
    verdict = verdict_of(output, scenario_id)
    if card is None:
        return "SETUP-FAIL"
    if any(item.get("scenario") != scenario_id for item in card["failures"]):
        return "SETUP-FAIL"
    if code == 1 and verdict == "FAIL":
        return "caught"
    if code == 0 and verdict == "PASS":
        return "BLIND"
    if verdict == "ERROR":
        return "ERROR"
    return "SETUP-FAIL"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="run mutations for matching scenario IDs")
    args = parser.parse_args(argv)
    selected = [entry for entry in MUTATIONS if not args.only or args.only in entry[0]]
    if not selected:
        print("no mutations matched", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="ta-mut-") as tmp:
        copy = pathlib.Path(tmp) / "tree"
        make_copy(copy)
        problems: list[str] = []
        print(f"scratch copy: {copy}\n")

        # Establish the baseline first. A pre-existing failure must not be credited to
        # a mutation that happens to leave that failure in place.
        code, output = score_of(copy)
        baseline = _card(output)
        if code != 0 or baseline is None or baseline["failures"]:
            print("SETUP-FAIL: the unmutated tree is not green")
            return 1
        for entry in selected:
            scenario_id, edits = _normalise(entry)
            if scenario_id not in baseline.get("passing", []):
                print(f"SETUP-FAIL {scenario_id}: no passing baseline for this scenario")
                problems.append(scenario_id)
                continue
            # Snapshot every touched file *once*, before any edit. Capturing per edit
            # meant a mutation that reverts two places in the same file restored the
            # first edit's broken text over the second, so the copy stayed mutated for
            # every later run — a harness that quietly poisons itself.
            originals: dict[pathlib.Path, bytes] = {}
            pending: dict[pathlib.Path, str] = {}
            setup_failed = False
            for relative, original_text, broken_text in edits:
                target = copy / relative
                if target not in originals:
                    original = target.read_text(encoding="utf-8")
                    originals[target] = target.read_bytes()
                    pending[target] = original
                # Apply against the *accumulated* text, not the pristine file: two edits
                # to the same file are one mutation, and starting the second from the
                # original silently discarded the first. That reported BLIND for a
                # finding that is genuinely protected.
                current = pending[target]
                if current.count(original_text) != 1:
                    print(f"SETUP-FAIL {scenario_id}: the fixed text moved in {relative}")
                    problems.append(scenario_id)
                    setup_failed = True
                    break
                pending[target] = current.replace(original_text, broken_text, 1)
            if not setup_failed:
                for target, text in pending.items():
                    target.write_bytes(text.encode("utf-8"))
            try:
                if setup_failed:
                    continue
                code, output = score_of(copy, scenario_id)
            finally:
                for target, original in originals.items():
                    target.write_bytes(original)

            # A mutation is caught when *this* scenario fails its own assertion. The old
            # check was `if code != 0`, and `code` is 1 for a traceback as well as for a
            # failed assertion and 2 for an unknown scenario id. The reviewer fed the
            # harness a mutation that did not compile (`... is True (`) and a scenario id
            # that does not exist; both printed `caught`, so the harness would go green
            # on a tree that does not import and on a corpus whose scenario was renamed.
            # That is exactly the failure mode the file's own docstring promises to
            # prevent, so the verdict is now read from the scorecard, not from an exit
            # code.
            verdict = verdict_of(output, scenario_id)
            classification = classify_result(code, output, scenario_id)
            if classification == "SETUP-FAIL":
                print(f"SETUP-FAIL {scenario_id}: the scenario did not run")
                for line in output.splitlines()[-6:]:
                    print(f"        {line.rstrip()}")
                problems.append(scenario_id)
            elif classification == "BLIND":
                print(f"BLIND  {scenario_id}")
                for line in output.splitlines():
                    if "SCORE" in line:
                        print(f"        {line.strip()}")
                problems.append(scenario_id)
            elif classification == "caught":
                print(f"caught {scenario_id}")
            else:
                # An ERROR is the scenario crashing, not the claim being violated: the
                # mutation broke the path the scenario walks instead of demonstrating the
                # defect. Reported, because a corpus full of these is a corpus that is
                # not really testing anything.
                print(f"ERROR  {scenario_id} ({verdict})")
                problems.append(scenario_id)

        code, output = score_of(copy)
        card = _card(output)
        print(f"\nunmutated tree: {card['score'] if card else 'unreadable'}/100")
        if code != 0 or card is None or card["failures"]:
            problems.append("the unmutated tree is not green")

    print()
    if problems:
        print(f"{len(problems)} scenario(s) do not protect anything: {problems}")
        return 1
    print(f"all {len(selected)} mutations caught; the corpus is not decoration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
