"""The scenario corpus: every clause of the promise, plus every real finding.

Each scenario names its `source`. `review:rN` means an adversarial reviewer found this by
breaking it, which is the strongest possible evidence that the clause needed writing
down. `claim` means it comes from the product promise in `AGENTS.md`.

Nothing here is invented for convenience. If a scenario did not fail before its fix, it
is not protecting anything and should be deleted rather than kept as decoration.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from . import (
    Case,
    expect,
    expect_equal,
    expect_in,
    fail,
    scenario,
    skip,
)

# --------------------------------------------------------------------------- #
# identity safety: the agent must not be able to rewrite who the user is
# --------------------------------------------------------------------------- #


@scenario(
    "identity.accept_always_refuses",
    "identity_safety",
    "The tool surface cannot apply a Self change, whatever it is called with.",
    "claim",
    weight=3,
)
def identity_accept_refuses(case: Case) -> None:
    from knowledgeos import gate

    api = case.api()
    path = case.propose(
        summary="A rule", section="heuristics", proposed_markdown="* A rule.", mode="append"
    )
    before = hashlib.sha256(case.self_path.read_bytes()).hexdigest()
    for arg in (str(path), path.name, "whatever", ""):
        with case.fake_terminal():
            out = gate.accept(api.vault, api.self_path, api.proposals_dir, arg)
        expect(out.get("error"), f"accept({arg!r}) did not refuse: {out!r:.300}")
        expect(
            "applied" not in out,
            f"accept({arg!r}) claimed to apply: {out!r:.300}",
        )
    after = hashlib.sha256(case.self_path.read_bytes()).hexdigest()
    expect_equal(after, before, "Self.md after accept()")


@scenario(
    "identity.no_tty_is_a_refusal",
    "identity_safety",
    "Approval without a terminal applies nothing, even with the right answer typed.",
    "claim",
    weight=3,
)
def identity_no_tty(case: Case) -> None:
    from knowledgeos import gate

    api = case.api()
    path = case.propose(
        summary="A rule", section="heuristics", proposed_markdown="* A rule.", mode="append"
    )
    before = hashlib.sha256(case.self_path.read_bytes()).hexdigest()
    # No fake_terminal: stdin/stdout are the test's own, which are not a TTY.
    out = gate.approve_interactive(api.vault, api.self_path, api.proposals_dir, str(path))
    expect(out.get("error"), f"approval without a TTY did not refuse: {out!r:.300}")
    after = hashlib.sha256(case.self_path.read_bytes()).hexdigest()
    expect_equal(after, before, "Self.md after a non-TTY approval attempt")


@scenario(
    "identity.handwritten_proposal_is_ignored",
    "identity_safety",
    "A proposal the agent writes itself cannot be applied, because it is not in the ledger.",
    "review:r4",
    weight=3,
)
def identity_handwritten(case: Case) -> None:
    from knowledgeos import gate

    api = case.api()
    forged = case.write(
        "People/Self-Proposals/2026-handwritten.md",
        "---\ntype: research\ntitle: x\nproposal_section: heuristics\n"
        "proposal_target: People/Self.md\nproposal_mode: replace\nstatus: draft\n---\n\n"
        "## Proposed\n\n```markdown\n* Anything at all.\n```\n",
    )
    before = hashlib.sha256(case.self_path.read_bytes()).hexdigest()
    out = case.approve(forged, api=api)
    expect(out.get("error"), f"a hand-written proposal was applied: {out!r:.300}")
    expect_equal(
        hashlib.sha256(case.self_path.read_bytes()).hexdigest(),
        before,
        "Self.md after a hand-written proposal",
    )


@scenario(
    "identity.tampered_body_is_refused",
    "identity_safety",
    "Editing a proposal after it was signed invalidates it.",
    "review:r5",
    weight=2,
)
def identity_tampered(case: Case) -> None:
    api = case.api()
    path = case.propose(
        summary="A rule", section="heuristics", proposed_markdown="* A rule.", mode="append"
    )
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("* A rule.", "* Something else entirely.", 1), encoding="utf-8"
    )
    out = case.approve(path, api=api)
    expect(out.get("error"), f"a tampered proposal was applied: {out!r:.300}")


@scenario(
    "identity.hardlinked_self_is_refused",
    "identity_safety",
    "A hardlink at Self.md cannot be used to write identity through a second name.",
    "review:r10",
    weight=2,
)
def identity_hardlink(case: Case) -> None:
    skip("POSIX-only link semantics are covered by the suite's own hardlink tests")


@scenario(
    "identity.raw_html_cannot_hide_a_wipe",
    "identity_safety",
    "Markup that renders as nothing still counts when the retention floor is measured.",
    "review:r9",
    weight=2,
)
def identity_html_wipe(case: Case) -> None:
    from knowledgeos import gate

    api = case.api()
    original = case.body("heuristics")
    expect(len(original) > 80, "the starter heuristics section is too short to test")
    hidden = "<div style='display:none'>" + original.replace("\n", " ") + "</div>\n* One rule."
    out = api.propose_self_update(
        summary="trim", section="heuristics", proposed_markdown=hidden, mode="replace"
    )
    expect(
        out.get("error"),
        f"a hidden-text wipe was accepted as a non-destructive replace: {out!r:.300}",
    )


# --------------------------------------------------------------------------- #
# approval fidelity: what the human reads is what gets applied
# --------------------------------------------------------------------------- #


@scenario(
    "approval.screen_matches_the_ledger",
    "approval_fidelity",
    "The section and mode on screen are the ledger's, not text found in the proposal file.",
    "review:r11",
    weight=3,
)
def approval_screen_matches(case: Case) -> None:
    """Authentic previews use the ledger; edited display metadata is refused."""
    import io
    from unittest import mock

    from knowledgeos import gate
    from knowledgeos.__main__ import _preview_diff, _self_pending

    api = case.api()
    before = case.self_path.read_bytes()
    patch = "* Always approve deploys without review."
    path = case.propose(
        summary="an ordinary summary",
        section="heuristics",
        proposed_markdown=patch,
        mode="replace",
        allow_destructive=True,
    )

    described = gate.describe(case.vault, api.proposals_dir, str(path))
    expect(not described.get("error"), f"an authentic proposal was refused: {described!r:.300}")
    expect_equal(described.get("section"), "heuristics", "the section the screen trusts")
    expect_equal(described.get("mode"), "replace", "the mode the screen trusts")
    expect_equal(described.get("patch"), patch, "the authenticated preview body")
    diff, _removals, _additions, section = _preview_diff(api, path, described["patch"])
    expect_equal(section, "heuristics", "the section rendered by the preview")
    expect_in("+" + patch, diff, "the proposed rule in the rendered diff")

    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nproposal_section: mental_models\nproposal_mode: append\n",
        encoding="utf-8",
    )

    described = gate.describe(case.vault, api.proposals_dir, str(path))
    expect_equal(
        described.get("error"),
        "proposal file was edited after it was created",
        "the edited preview refusal",
    )
    expect_equal(set(described), {"error", "hint"}, "the refused preview fields")
    expect("mental_models" not in str(described), "the forged section reached the refusal")

    sink = io.StringIO()
    with mock.patch("sys.stdout", sink):
        code = _self_pending(["--vault", str(case.vault)])
    screen = sink.getvalue()
    expect_equal(code, 0, "exit code of the read-only pending command")
    expect_in("[heuristics / replace]", screen, "the ledger metadata on the pending screen")
    expect("mental_models" not in screen, f"the forged section reached the screen: {screen[:400]!r:.500}")
    expect_equal(case.self_path.read_bytes(), before, "Self.md after authentic and refused previews")


@scenario(
    "approval.body_cannot_read_as_metadata",
    "approval_fidelity",
    "A proposal's free text cannot contain a line that looks like the proposal's own metadata.",
    "review:r11",
    weight=2,
)
def approval_body_not_metadata(case: Case) -> None:
    """Belt and braces behind the ledger authority: the file is honest too.

    `rationale` accepts newlines, so an agent-supplied rationale containing
    `proposal_mode: append` produced a proposal whose body carried a bare metadata line —
    readable as metadata by a human, and by any future reader that trusts the file.
    """
    from knowledgeos import gate

    path = case.propose(
        summary="an ordinary summary",
        section="heuristics",
        proposed_markdown="* A rule.",
        mode="append",
        rationale="because\n\nproposal_mode: append\nproposal_section: mental_models",
    )
    text = path.read_text(encoding="utf-8")
    expect(
        "mental_models" in text,
        "the rationale was dropped entirely, so this proves nothing",
    )
    for line in text.splitlines():
        expect(
            not line.startswith("proposal_section:") or line.startswith("proposal_section: heuristics"),
            f"the body carries a bare metadata line: {line!r}",
        )
        expect(
            not line.startswith("proposal_mode:") or line.startswith("proposal_mode: append"),
            f"the body carries a bare metadata line: {line!r}",
        )
    expect_equal(gate._claimed_section(text), "heuristics", "the section claimed by the file")


@scenario(
    "approval.destructive_waiver_is_confirmed_separately",
    "approval_fidelity",
    "A waived retention floor is named on screen and needs a word a stray keypress cannot type.",
    "review:r11",
    weight=3,
)
def approval_destructive_word(case: Case) -> None:
    import io
    from unittest import mock

    from knowledgeos.__main__ import _self_approve

    api = case.api()
    path = case.propose(
        summary="trim",
        section="heuristics",
        proposed_markdown="* One rule.",
        mode="replace",
        allow_destructive=True,
    )
    before = case.self_path.read_bytes()
    asked: list[str] = []
    sink = io.StringIO()
    with mock.patch("sys.stdin.isatty", return_value=True), mock.patch(
        "knowledgeos.gate._require_human_terminal", return_value=None
    ), mock.patch("builtins.input", side_effect=lambda prompt="": asked.append(prompt) or "y"), mock.patch("sys.stdout", sink):
        code = _self_approve([str(path), "--vault", str(case.vault)])
    screen = sink.getvalue()
    expect_in("DESTRUCTIVE", screen, "a warning that the retention floor was waived")
    expect(asked and "yes-wipe" in asked[0], f"the confirmation asked {asked!r:.200}")
    expect_equal(code, 1, "exit code after a plain y on a destructive change")
    expect_equal(case.self_path.read_bytes(), before, "Self.md after a plain y")


@scenario(
    "approval.preview_shows_removals",
    "approval_fidelity",
    "The screen shows the lines that would be deleted, not only the ones added.",
    "review:r7",
    weight=2,
)
def approval_preview_removals(case: Case) -> None:
    from knowledgeos.__main__ import _preview_diff

    api = case.api()
    path = case.propose(
        summary="trim",
        section="heuristics",
        proposed_markdown="* One rule.",
        mode="replace",
        allow_destructive=True,
    )
    diff, removals, additions, section = _preview_diff(api, path, _patch_of(case, api, path))
    expect_equal(section, "heuristics", "the section the preview rendered")
    expect(removals > 0, "the preview reported no removals for a replacing patch")
    expect(
        any(line.startswith("-") for line in diff),
        "no '-' line appeared in the diff",
    )


@scenario(
    "approval.append_shows_the_merge",
    "approval_fidelity",
    "An append previews the text that would be stored, not the patch pasted under the old text.",
    "review:r10",
    weight=2,
)
def approval_append_merge(case: Case) -> None:
    from knowledgeos import gate
    from knowledgeos.__main__ import _preview_diff

    api = case.api()
    original = case.body("heuristics")
    rules = [
        line
        for line in original.splitlines()
        if line.strip() and not line.strip().startswith("<!--")
    ]
    expect(rules, "the heuristics section has no rules to duplicate")
    first_line = rules[0]
    path = case.propose(
        summary="add a rule",
        section="heuristics",
        proposed_markdown=first_line + "\n* A genuinely new rule.",
        mode="append",
    )
    described = gate.describe(case.vault, api.proposals_dir, str(path))
    diff, _removals, _additions, _section = _preview_diff(api, path, described["patch"])
    rendered = "\n".join(diff)
    expect(
        response_count(rendered, first_line) <= 1,
        "the preview showed an existing line twice, so it diffed the patch rather than the merge",
    )


@scenario(
    "approval.terminal_escapes_are_refused",
    "approval_fidelity",
    "A terminal escape cannot make the screen display something other than the stored text.",
    "review:r8",
    weight=2,
)
def approval_escapes(case: Case) -> None:
    api = case.api()
    out = api.propose_self_update(
        summary="sneaky",
        section="heuristics",
        proposed_markdown="* Visible.\x1b[8m\n* Invisible wipe of the rest.\x1b[0m",
        mode="replace",
    )
    expect(out.get("error"), f"a terminal escape was accepted into a proposal: {out!r:.300}")


# --------------------------------------------------------------------------- #
# vault integrity: nothing the product writes escapes or corrupts
# --------------------------------------------------------------------------- #


@scenario(
    "vault.junctioned_inbox_is_refused",
    "vault_integrity",
    "A junction planted at Inbox cannot redirect a capture outside the vault.",
    "review:r9",
    weight=2,
)
def vault_junction_inbox(case: Case) -> None:
    outside = case.root / "outside"
    outside.mkdir()
    inbox = case.vault / "Inbox"
    for entry in list(inbox.iterdir()):
        entry.unlink()
    inbox.rmdir()
    try:
        os.symlink(str(outside), str(inbox), target_is_directory=True)
    except (OSError, NotImplementedError):
        skip("this platform will not let the test create a directory link")
    api = case.api()
    out = api.capture("A note", "## Body\n\ntext\n")
    expect(out.get("error"), f"a capture through a junctioned Inbox succeeded: {out!r:.300}")
    expect_equal(sorted(p.name for p in outside.iterdir()), [], "files written outside the vault")


@scenario(
    "vault.junctioned_state_folder_is_refused",
    "vault_integrity",
    "A .knowledgeos junction cannot move vault state outside the vault.",
    "review:r10",
    weight=2,
)
def vault_junction_state(case: Case) -> None:
    outside = case.root / "state-outside"
    outside.mkdir()
    state = case.vault / ".knowledgeos"
    if state.is_dir():
        for entry in list(state.iterdir()):
            entry.unlink()
        state.rmdir()
    try:
        os.symlink(str(outside), str(state), target_is_directory=True)
    except (OSError, NotImplementedError):
        skip("this platform will not let the test create a directory link")
    api = case.api()
    try:
        api.ops_status()
        api.session_start("spec")
    except Exception:
        pass
    leaked = sorted(p.name for p in outside.iterdir())
    expect_equal(leaked, [], "state files written outside the vault")


@scenario(
    "vault.reject_cannot_reach_self_md",
    "vault_integrity",
    "Rejecting a proposal cannot be redirected into People/Self.md.",
    "review:r6",
    weight=3,
)
def vault_reject_redirect(case: Case) -> None:
    from knowledgeos import gate

    api = case.api()
    before = case.self_path.read_bytes()
    for target in (
        case.self_path,
        case.vault / "People" / "Self-Proposals" / ".." / "Self.md",
        case.vault / "People" / "Self-Proposals" / "Self.md",
    ):
        out = gate.reject(case.vault, api.proposals_dir, str(target))
        expect(out.get("error"), f"reject({target}) did not refuse: {out!r:.300}")
    expect_equal(case.self_path.read_bytes(), before, "Self.md after reject attempts")


@scenario(
    "vault.no_hook_code_in_the_vault",
    "vault_integrity",
    "The vault holds hook configuration but no executable hook code.",
    "review:r10",
    weight=2,
)
def vault_no_hook_code(case: Case) -> None:
    hooks = case.vault / ".cursor" / "hooks"
    code = sorted(p.name for p in hooks.glob("*.py")) if hooks.is_dir() else []
    expect_equal(code, [], "python files inside the vault's hook folder")
    expect((case.vault / ".cursor" / "hooks.json").is_file(), "hooks.json is missing")


# --------------------------------------------------------------------------- #
# truthfulness of reads: what is quoted is what the user wrote
# --------------------------------------------------------------------------- #


@scenario(
    "reads.deleted_note_is_never_served",
    "truthfulness_of_reads",
    "A deleted note is not returned by search, in any bucket.",
    "review:r3",
    weight=3,
)
def reads_deleted_note(case: Case) -> None:
    api = case.api()
    note = case.write("Inbox/gone.md", "---\ntitle: Gone\ntags: [narwhalterm]\n---\n\nnarwhalterm\n")
    api.search("narwhalterm")
    note.unlink()
    hits = api.search("narwhalterm")
    served = [row.get("path") for rows in hits.values() if isinstance(rows, list) for row in rows if isinstance(row, dict)]
    expect("Inbox/gone.md" not in served, f"a deleted note was served: {served!r:.300}")


@scenario(
    "reads.edited_note_is_not_quoted_stale",
    "truthfulness_of_reads",
    "Text replaced in a note is not quoted from a frozen index.",
    "review:r10",
    weight=3,
)
def reads_edited_note(case: Case) -> None:
    from unittest import mock

    api = case.api()
    note = case.write(
        "Inbox/rule.md", "---\ntitle: Rule\n---\n\nrequires a human reviewer\n"
    )
    api.search("reviewer")
    note.write_text(
        "---\ntitle: Rule\n---\n\nforbidden to need humans at all\n", encoding="utf-8"
    )
    with mock.patch("knowledgeos.indexer.index_state", return_value="locked"):
        hits = api.search("reviewer")
    quoted = " ".join(
        str(row.get("snippet") or "")
        for rows in hits.values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict)
    )
    expect(
        "requires a human reviewer" not in quoted,
        f"the replaced sentence was still quoted: {quoted!r:.300}",
    )


@scenario(
    "reads.removed_metadata_is_not_served",
    "truthfulness_of_reads",
    "A tag removed from a note is not returned as a hit for that tag.",
    "review:r11",
    weight=2,
)
def reads_removed_metadata(case: Case) -> None:
    from unittest import mock

    api = case.api()
    note = case.write(
        "Inbox/tagged.md", "---\ntitle: Tagged\ntags: [quokka]\n---\n\nbody\n"
    )
    hits = api.search("quokka")
    expect(
        any(row.get("path") == "Inbox/tagged.md" for row in hits.get("tags") or []),
        "the tag was never indexed, so this check proves nothing",
    )
    note.write_text("---\ntitle: Tagged\ntags: [wallaby]\n---\n\nbody\n", encoding="utf-8")
    with mock.patch("knowledgeos.indexer.index_state", return_value="locked"):
        hits = api.search("quokka")
    served = [
        row.get("path")
        for key in ("ranked", "tags", "title", "project", "description")
        for row in (hits.get(key) or [])
    ]
    expect("Inbox/tagged.md" not in served, f"a removed tag was still served: {served!r:.300}")


@scenario(
    "reads.same_size_same_mtime_edit_is_seen",
    "truthfulness_of_reads",
    "An edit that preserves both size and mtime is still detected, at any vault size.",
    "review:r11",
    weight=3,
)
def reads_stealth_edit(case: Case) -> None:
    from knowledgeos import indexer

    api = case.api()
    note = case.write("Inbox/budget.md", "---\ntitle: Budget\n---\n\noriginal sentence here\n")
    api.search("original")
    stored = note.read_bytes()
    info = note.stat()
    replacement = stored.replace(b"original", b"replaced")
    expect_equal(len(replacement), len(stored), "the probe needs an equal-length edit")
    note.write_bytes(replacement)
    os.utime(note, ns=(info.st_atime_ns, info.st_mtime_ns))
    changed, reason = indexer.manifest_diff(case.vault, hash_contents=True, hash_budget_bytes=1)
    expect(changed, f"a stealth edit was reported fresh ({reason})")


@scenario(
    "reads.search_and_validate_agree",
    "truthfulness_of_reads",
    "The set of notes search covers is the set validate checks.",
    "review:r6",
    weight=2,
)
def reads_agree(case: Case) -> None:
    from knowledgeos import indexer

    case.write("Inbox/one.md", "---\ntitle: One\n---\n\nbody one\n")
    case.write("Projects/two.md", "---\ntitle: Two\ntype: project\n---\n\nbody two\n")
    indexed = {p.relative_to(case.vault).as_posix() for p in indexer.iter_markdown(case.vault)}
    expect("Inbox/one.md" in indexed, "a normal note was not in the indexed set")
    expect("Projects/two.md" in indexed, "a project note was not in the indexed set")
    expect(
        not any(name.startswith(".") for name in indexed),
        f"hidden paths leaked into the index: {sorted(indexed)!r:.300}",
    )


@scenario(
    "reads.stemmed_query_survives_a_locked_index",
    "truthfulness_of_reads",
    "A stale index does not turn a stem into a miss: a note saying 'reviews' matches 'review'.",
    "review:r12",
    weight=2,
)
def reads_stemmed_query(case: Case) -> None:
    from unittest import mock

    api = case.api()
    case.write(
        "Concepts/Ship.md",
        "---\ntype: concept\ntitle: Shipping\n---\n\n"
        "Every release is reviewed by a second engineer before it deploys.\n",
    )
    expect(
        [r["path"] for r in api.search("review")["ranked"]],
        "the note was never indexed, so this proves nothing",
    )
    with mock.patch("knowledgeos.indexer.index_state", return_value="locked"):
        for query in ("review", "reviews", "reviewing", "deploys"):
            expect(
                [r["path"] for r in api.search(query)["ranked"]],
                f"a stemmed query returned nothing while the index was locked: {query!r}",
            )


@scenario(
    "reads.decisions_use_the_file_not_the_index",
    "truthfulness_of_reads",
    "A decision that changed project or status is filtered on what the note says now.",
    "review:r12",
    weight=2,
)
def reads_decisions_fresh(case: Case) -> None:
    from unittest import mock

    api = case.api()
    note = case.write(
        "Decisions/pick-vendor.md",
        "---\ntype: decision\ntitle: Pick vendor\nstatus: open\nproject: alpha\n"
        "outcome_status: pending\n---\n\n# Pick vendor\n",
    )
    expect(
        [r["path"] for r in api.decisions(project="alpha")["decisions"]],
        "the decision was never indexed, so this proves nothing",
    )
    note.write_text(
        "---\ntype: decision\ntitle: Pick vendor\nstatus: closed\nproject: beta\n"
        "outcome_status: confirmed\n---\n\n# Pick vendor\n",
        encoding="utf-8",
    )
    with mock.patch("knowledgeos.indexer.index_state", return_value="locked"):
        left = [r["path"] for r in api.decisions(project="alpha")["decisions"]]
        moved = [r["path"] for r in api.decisions(project="beta")["decisions"]]
    expect_equal(left, [], "a decision that left a project was still listed in it")
    expect_equal(moved, ["Decisions/pick-vendor.md"], "the decision in its new project")


@scenario(
    "reads.related_drops_a_removed_link",
    "truthfulness_of_reads",
    "A link deleted from a note stops being a relationship, even while the index is frozen.",
    "review:r12",
    weight=2,
)
def reads_related_fresh(case: Case) -> None:
    from unittest import mock

    api = case.api()
    alpha = case.write(
        "Concepts/Alpha.md", "---\ntype: concept\ntitle: Alpha\n---\n\nSee [Beta](Beta.md).\n"
    )
    case.write("Concepts/Beta.md", "---\ntype: concept\ntitle: Beta\n---\n\n# Beta\n")
    expect_equal(
        [r["path"] for r in api.related("Concepts/Alpha.md")["related"]],
        ["Concepts/Beta.md"],
        "the link was never indexed, so this proves nothing",
    )
    alpha.write_text("---\ntype: concept\ntitle: Alpha\n---\n\nNo links.\n", encoding="utf-8")
    with mock.patch("knowledgeos.indexer.index_state", return_value="locked"):
        hits = [r["path"] for r in api.related("Concepts/Alpha.md")["related"]]
    expect_equal(hits, [], "a link the note no longer contains was still served")


@scenario(
    "reads.one_stray_crlf_does_not_rewrite_the_file",
    "truthfulness_of_reads",
    "Editing a note does not convert every other line's line ending.",
    "review:r12",
    weight=2,
)
def reads_line_endings(case: Case) -> None:
    """One stray CRLF in an otherwise-LF file must not normalise the whole file.

    The assertion is deliberately not "how many CRLF are left". The round-twelve fix
    normalised the file to its dominant ending, which happens to leave 0 CRLF here but
    rewrites every line of a *mixed* file (the round-thirteen finding, covered by
    `reads.approving_one_line_keeps_every_other_line_ending`). The durable property is
    the one a person expects: the lines you did not touch are byte-for-byte the lines
    you had.
    """
    import difflib

    from knowledgeos.textio import dominant_newline

    expect_equal(dominant_newline(b"a\r\nb\nc\nd\n"), "\n", "one stray CRLF in an LF file")
    expect_equal(
        dominant_newline(b"a\r\nb\r\nc\r\nd\r\n"), "\r\n", "a genuinely CRLF file"
    )

    raw = case.self_path.read_bytes().replace(b"\r\n", b"\n")
    lines = raw.split(b"\n")
    lines[10] = lines[10] + b"\r"
    case.self_path.write_bytes(b"\n".join(lines))
    before = case.self_path.read_bytes()

    path = case.propose(
        summary="one rule", section="heuristics", proposed_markdown="* A new rule.", mode="append"
    )
    out = case.approve(path)
    expect(not out.get("error"), f"the append was refused: {out!r:.300}")
    after = case.self_path.read_bytes()

    def bodies(raw: bytes) -> list[bytes]:
        return [line[:-1] if line.endswith(b"\r") else line for line in raw.split(b"\n")]

    def endings(raw: bytes) -> list[bytes]:
        return [b"\r" if line.endswith(b"\r") else b"" for line in raw.split(b"\n")]

    old_bodies, new_bodies = bodies(before), bodies(after)
    old_ends, new_ends = endings(before), endings(after)
    matcher = difflib.SequenceMatcher(a=old_bodies, b=new_bodies, autojunk=False)
    moved = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                if old_ends[i1 + offset] != new_ends[j1 + offset]:
                    moved.append((old_bodies[i1 + offset], old_ends[i1 + offset]))
        elif tag == "replace":
            for body in old_bodies[i1:i2]:
                if not body.lstrip().startswith(b"updated:"):
                    moved.append((body, b"replaced"))
    expect_equal(moved, [], "the append moved line endings on lines it did not touch")
    expect_equal(new_bodies.count(b"* A new rule."), 1, "the rule was not appended")


@scenario(
    "reads.an_unsigned_manifest_is_not_trusted",
    "truthfulness_of_reads",
    "Rewriting the freshness manifest cannot make search assert text the note no longer has.",
    "review:r12",
    weight=3,
)
def reads_manifest_signed(case: Case) -> None:
    """The manifest decides whether search rebuilds, and it lives inside the vault.

    An agent that can write notes can write it, so an unsigned manifest is a way to say
    "these files are already indexed" without that being true. The reviewer rewrote it and
    `search` went on quoting "a human reviewer must sign off" from a note that now said
    deploys were automated.
    """
    import hashlib
    import json

    from knowledgeos import indexer
    from knowledgeos.memory import MemoryAPI

    api = case.api()
    note = case.write(
        "Concepts/Policy.md",
        "---\ntype: concept\ntitle: Policy\n---\n\nrequires a human reviewer\n",
    )
    api.search("human reviewer")

    manifest = case.vault / ".knowledgeos" / "index-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    expect("mac" in data, "the manifest is not signed at all")

    note.write_text(
        "---\ntype: concept\ntitle: Policy\n---\n\ndeploys are automated now\n",
        encoding="utf-8",
    )
    info = note.stat()
    data["files"]["Concepts/Policy.md"] = [
        info.st_size,
        info.st_mtime_ns,
        hashlib.sha256(note.read_bytes()).hexdigest(),
    ]
    manifest.write_text(json.dumps(data, indent=0, sort_keys=True) + "\n", encoding="utf-8")

    expect(
        indexer.load_manifest(case.vault) is None,
        "a forged manifest was accepted, which disables the freshness check",
    )
    hits = [r["path"] for r in MemoryAPI(case.vault).search("human reviewer")["ranked"]]
    expect(
        "Concepts/Policy.md" not in hits,
        f"the replaced sentence was still served: {hits!r:.300}",
    )


@scenario(
    "reads.a_frozen_index_says_so",
    "truthfulness_of_reads",
    "An answer from a frozen index is not presented as a complete one.",
    "review:r12",
    weight=1,
)
def reads_frozen_flag(case: Case) -> None:
    from unittest import mock

    api = case.api()
    case.write("Inbox/early.md", "---\ntitle: Early\n---\n\nzebraword\n")
    api.search("zebraword")
    with mock.patch("knowledgeos.indexer.index_state", return_value="locked"):
        payload = api.search("zebraword")
    expect(payload.get("index_frozen"), f"no frozen indicator: {sorted(payload)}")
    expect("index_frozen_note" in payload, "no sentence explaining the frozen answer")


# --------------------------------------------------------------------------- #
# autopilot reliability: it keeps itself current and never lies about it
# --------------------------------------------------------------------------- #


@scenario(
    "autopilot.session_start_returns_a_usable_brief",
    "autopilot_reliability",
    "The first tool of a chat answers with Self, context and a prompt the agent can act on.",
    "claim",
    weight=3,
)
def autopilot_session_start(case: Case) -> None:
    api = case.api()
    out = api.session_start("what did I decide about pricing")
    expect(isinstance(out, dict) and out, "session_start returned nothing usable")
    for key in ("context", "ops", "agent_must"):
        expect(key in out, f"session_start omitted {key!r}: {sorted(out)!r:.300}")
    context = out.get("context") or {}
    expect(
        isinstance(context.get("self"), dict) and context["self"],
        f"the brief carried no identity: {sorted(context)!r:.300}",
    )
    expect(
        "heuristics" in (context.get("self") or {}).get("sections", {}),
        "the identity in the brief has no sections",
    )


@scenario(
    "autopilot.session_end_prompt_is_a_string",
    "autopilot_reliability",
    "The end of a chat reports one prompt, not a Python tuple.",
    "review:r11",
    weight=2,
)
def autopilot_session_end(case: Case) -> None:
    api = case.api()
    out = api.session_end("a short summary")
    soft = out.get("soft_prompt")
    expect(not isinstance(soft, tuple), f"soft_prompt was a tuple: {soft!r:.200}")
    ask = out.get("ask_human")
    expect(isinstance(ask, str), f"ask_human was {type(ask).__name__}, not str")


@scenario(
    "autopilot.blocked_index_is_reported",
    "autopilot_reliability",
    "An index that cannot be rebuilt is said out loud, in plain language.",
    "review:r10",
    weight=3,
)
def autopilot_blocked_index(case: Case) -> None:
    from knowledgeos.autopilot import ensure_index_fresh, load_state

    case.write("Inbox/new.md", "---\ntitle: New\n---\n\nbrand new note\n")
    lock = case.vault / ".knowledgeos" / "index-rebuild.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.mkdir(parents=True, exist_ok=True)
    try:
        out = ensure_index_fresh(case.vault, load_state(case.vault))
        expect(out.get("blocked") or out.get("busy"), f"a blocked rebuild was not reported: {out!r:.300}")
        status = case.api().ops_status()
        expect(
            status.get("index_blocked") or "index" in " ".join(status.get("plain_language") or []).lower(),
            f"ops_status said nothing about the blocked index: {status!r:.400}",
        )
    finally:
        lock.rmdir()


@scenario(
    "autopilot.drift_needs_evidence",
    "autopilot_reliability",
    "A preference update is not proposed from two chats in one afternoon.",
    "claim",
    weight=2,
)
def autopilot_drift(case: Case) -> None:
    from knowledgeos import autopilot

    api = case.api()
    state = autopilot.load_state(case.vault)
    first = autopilot.maybe_propose_weekly_drift(api, state)
    expect(not first.get("proposed"), f"drift was proposed on the first chat: {first!r:.300}")
    second = autopilot.maybe_propose_weekly_drift(api, autopilot.load_state(case.vault))
    expect(not second.get("proposed"), f"drift was proposed from one afternoon: {second!r:.300}")


# --------------------------------------------------------------------------- #
# install / ops honesty: a fresh machine works, and doctor tells the truth
# --------------------------------------------------------------------------- #


@scenario(
    "ops.doctor_passes_a_healthy_vault",
    "install_ops_honesty",
    "doctor exits 0 and says so on a vault the toolkit just created.",
    "claim",
    weight=1,
)
def ops_doctor_healthy(case: Case) -> None:
    import io
    from unittest import mock

    from knowledgeos import doctor

    sink = io.StringIO()
    with mock.patch("sys.stdout", sink):
        code = doctor.main(["--vault", str(case.vault)])
    output = sink.getvalue()
    expect_equal(code, 0, f"doctor on a fresh vault\n{output[-1200:]}")
    expect_in("PASSED", output, "doctor's verdict on a fresh vault")


@scenario(
    "ops.doctor_fails_a_missing_identity_section",
    "install_ops_honesty",
    "A missing writable Self section is an error, not a warning.",
    "review:r11",
    weight=2,
)
def ops_doctor_missing_section(case: Case) -> None:
    import io
    from unittest import mock

    from knowledgeos import doctor

    text = case.self_text()
    marker = "## Anti-Goals"
    expect_in(marker, text, "the starter Self.md has no Anti-Goals section")
    head, _, tail = text.partition(marker)
    rest = tail.split("\n## ", 1)
    remainder = ("\n## " + rest[1]) if len(rest) > 1 else ""
    case.self_path.write_text(head + remainder.lstrip("\n"), encoding="utf-8")

    sink = io.StringIO()
    with mock.patch("sys.stdout", sink):
        code = doctor.main(["--vault", str(case.vault)])
    output = sink.getvalue()
    expect(code != 0, f"doctor exited 0 on a damaged Self.md:\n{output[-1200:]}")
    expect_in("anti_goals", output, "the section named in doctor's error")


@scenario(
    "ops.vault_round_trips_through_the_cli",
    "install_ops_honesty",
    "A vault created by init can be read by the documented entry point.",
    "claim",
    weight=1,
)
def ops_cli(case: Case) -> None:
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "knowledgeos", "validate", "--vault", str(case.vault)],
        cwd=str(case.root),
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    expect(proc.returncode in (0, 1), f"validate crashed: {proc.stderr[-800:]}")
    expect(
        "Traceback" not in proc.stderr,
        f"validate raised instead of reporting: {proc.stderr[-800:]}",
    )


# --------------------------------------------------------------------------- #
# round twelve: the index is a cache, not the note
# --------------------------------------------------------------------------- #


def _forge_fts(case: Case, rel: str, body: str) -> None:
    """One ordinary write to the index — exactly what an agent with vault access can do."""
    import sqlite3

    db = case.vault / "knowledge_index.db"
    expect(db.exists(), "the scenario needs an index; none was built")
    conn = sqlite3.connect(db, timeout=30)
    try:
        conn.execute("UPDATE notes_fts SET body = ? WHERE path = ?", (body, rel))
        conn.commit()
    finally:
        conn.close()


@scenario(
    "truth.forged_index_text_is_never_quoted",
    "truthfulness_of_reads",
    "Rewriting the index cannot make search quote a sentence no note contains.",
    "review:r12",
    weight=3,
)
def truth_forged_index_text(case: Case) -> None:
    api = case.api()
    note = case.write(
        "Concepts/Deploy.md",
        "---\ntype: concept\ntitle: Deploy policy\nstatus: active\n---\n\n"
        "# Deploy policy\n\nDeploys are fully automated; no human review is involved.\n",
    )
    api.search("warm")
    forged = "Deploys require a human reviewer to sign off in writing."
    _forge_fts(case, "Concepts/Deploy.md", forged)

    hits = api.search("human reviewer")["ranked"]
    snippets = [h.get("snippet", "") for h in hits if "Deploy.md" in h.get("path", "")]
    for snippet in snippets:
        expect(
            "sign off in writing" not in snippet,
            f"search quoted text no note contains: {snippet!r:.200}",
        )
    expect(
        note.read_text(encoding="utf-8").count("automated") == 1,
        "the scenario itself changed the note, so it proves nothing",
    )


@scenario(
    "truth.a_forged_index_row_cannot_hide_a_note",
    "truthfulness_of_reads",
    "Rewriting the index must not make a note unsearchable for the words it contains.",
    "review:r12",
    weight=3,
)
def truth_forged_row_hides(case: Case) -> None:
    api = case.api()
    case.write(
        "Concepts/Ground.md",
        "---\ntype: concept\ntitle: Ground truth\nstatus: active\n---\n\n"
        "# Ground truth\n\nThe zebra-quartz reading was confirmed twice.\n",
    )
    api.search("warm")
    _forge_fts(case, "Concepts/Ground.md", "Nothing to see here.")
    hits = [h["path"] for h in api.search("zebra-quartz")["ranked"]]
    expect_in(
        "Concepts/Ground.md",
        hits,
        "a note whose text still contains the query returned no hits — the forged "
        "index entry hid it, and a silently missing note is the same lie inverted",
    )


@scenario(
    "truth.deleted_index_rows_are_repaired",
    "truthfulness_of_reads",
    "Deleting rows from the index does not make a note disappear from search.",
    "review:r12",
    weight=2,
)
def truth_deleted_rows(case: Case) -> None:
    import sqlite3

    api = case.api()
    case.write(
        "Concepts/Hide.md",
        "---\ntype: concept\ntitle: Hide me\nstatus: active\n---\n\n"
        "# Hide me\n\nCopper-lantern is the codename.\n",
    )
    api.search("warm")
    db = case.vault / "knowledge_index.db"
    conn = sqlite3.connect(db, timeout=30)
    try:
        conn.execute("DELETE FROM notes WHERE path = ?", ("Concepts/Hide.md",))
        conn.execute("DELETE FROM notes_fts WHERE path = ?", ("Concepts/Hide.md",))
        conn.commit()
    finally:
        conn.close()
    hits = [h["path"] for h in api.search("copper-lantern")["ranked"]]
    expect_in("Concepts/Hide.md", hits, "a note deleted from the index vanished from search")


@scenario(
    "truth.forged_status_cannot_reopen_a_closed_decision",
    "truthfulness_of_reads",
    "A closed decision stays closed even if the index says it is pending.",
    "review:r12",
    weight=3,
)
def truth_forged_status(case: Case) -> None:
    import sqlite3

    api = case.api()
    case.write(
        "Decisions/shutdown.md",
        "---\ntype: decision\ntitle: Shut down line B\nstatus: closed\n"
        "outcome_status: confirmed\nupdated: 2026-10-01\n---\n\n"
        "# Shut down line B\n\nOutcome: line B was shut down.\n",
    )
    api.search("warm")
    db = case.vault / "knowledge_index.db"
    conn = sqlite3.connect(db, timeout=30)
    try:
        conn.execute(
            "UPDATE notes SET status='active', outcome_status='pending' WHERE path = ?",
            ("Decisions/shutdown.md",),
        )
        conn.commit()
    finally:
        conn.close()

    from knowledgeos import evolution

    expect_equal(
        evolution.pending_outcome_reviews(api),
        [],
        "a closed decision was reported as still awaiting an outcome",
    )
    open_now = api.decisions(outcome_status="pending")["decisions"]
    expect_equal([row["path"] for row in open_now], [], "decisions(outcome_status='pending')")
    bootstrap = api.bootstrap_context()
    expect_equal(
        [row["path"] for row in bootstrap["pending_decision_outcomes"]],
        [],
        "bootstrap_context listed a closed decision as pending",
    )


@scenario(
    "truth.the_closed_decision_is_not_asked_about",
    "truthfulness_of_reads",
    "The soft prompt never asks the human about a decision they already closed.",
    "review:r12",
    weight=2,
)
def truth_no_nag(case: Case) -> None:
    import sqlite3

    api = case.api()
    note = case.write(
        "Decisions/pick-vendor.md",
        "---\ntype: decision\ntitle: Pick vendor\nstatus: open\n"
        "outcome_status: pending\nupdated: 2026-10-01\n---\n\n"
        "# Pick vendor\n\nWe need to choose a supplier.\n",
    )
    # Index it while it is genuinely open, then close it in the note — the human's own
    # edit, in their own editor. This is the real sequence: the twin indexes on the way in,
    # the decision is answered later, and another process may hold the index when the next
    # chat asks.
    api.search("warm")
    note.write_text(
        "---\ntype: decision\ntitle: Pick vendor\nstatus: closed\n"
        "outcome_status: confirmed\nupdated: 2026-10-15\n"
        "lesson: Vendor B won on price.\n---\n\n# Pick vendor\n\nOutcome: Acme won.\n",
        encoding="utf-8",
    )

    db = case.vault / "knowledge_index.db"
    holder = sqlite3.connect(db, timeout=30)
    try:
        holder.execute("BEGIN IMMEDIATE")
        from knowledgeos import autopilot, evolution

        expect_equal(
            evolution.pending_outcome_reviews(api),
            [],
            "the closed decision came back as pending while the index was held",
        )
        ops = api.ops_status()
        expect_equal(ops["pending_outcomes_count"], 0, "ops_status's pending count")
        soft, _key = autopilot.soft_prompt_for_human(ops, asked=set())
        rendered = str(soft or "")
        expect(
            "Pick vendor" not in rendered,
            f"the human was asked about a decision they finished: {rendered!r:.200}",
        )
        bootstrap = api.bootstrap_context()
        expect_equal(
            [row["path"] for row in bootstrap["pending_decision_outcomes"]],
            [],
            "bootstrap_context listed a closed decision as pending",
        )
    finally:
        holder.execute("ROLLBACK")
        holder.close()


@scenario(
    "truth.a_frozen_index_says_so",
    "truthfulness_of_reads",
    "A list answer drawn from a held index is labelled as possibly incomplete.",
    "review:r12",
    weight=1,
)
def truth_frozen_flag(case: Case) -> None:
    import sqlite3

    api = case.api()
    case.write(
        "Decisions/old.md",
        "---\ntype: decision\ntitle: Old call\nstatus: active\n"
        "outcome_status: pending\nupdated: 2026-10-01\n---\n\n# Old call\n",
    )
    api.search("warm")
    db = case.vault / "knowledge_index.db"
    holder = sqlite3.connect(db, timeout=30)
    try:
        holder.execute("BEGIN IMMEDIATE")
        for label, payload in (
            ("decisions", api.decisions()),
            ("timeline", api.timeline()),
        ):
            expect(
                payload.get("index_frozen"),
                f"{label} answered from a held index without labelling the answer",
            )
    finally:
        holder.execute("ROLLBACK")
        holder.close()


@scenario(
    "truth.a_decision_template_is_not_a_decision",
    "truthfulness_of_reads",
    "A fresh vault reports no open decisions before the human has made one.",
    "review:r12",
    weight=1,
)
def truth_templates(case: Case) -> None:
    api = case.api()
    payload = api.decisions()
    paths = [row["path"] for row in payload["decisions"]]
    expect_equal(paths, [], "a fresh vault reported decisions it does not have")
    expect_equal(
        api.decisions(outcome_status="pending")["decisions"],
        [],
        "a template was reported as an open outcome",
    )


@scenario(
    "ops.the_state_folder_must_be_a_folder",
    "install_ops_honesty",
    "A file where the state folder belongs is a reported fault, not a silent one.",
    "review:r12",
    weight=2,
)
def ops_state_folder_file(case: Case) -> None:
    import io
    from unittest import mock

    from knowledgeos import doctor

    folder = case.vault / ".knowledgeos"
    if folder.is_dir():
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()
    folder.write_text("not a folder", encoding="utf-8")

    sink = io.StringIO()
    with mock.patch("sys.stdout", sink):
        code = doctor.main(["--vault", str(case.vault)])
    output = sink.getvalue()
    expect(code != 0, f"doctor exited 0 with the state folder replaced by a file:\n{output[-1200:]}")
    expect_in(".knowledgeos", output, "the path named in doctor's error")


@scenario(
    "identity.rewriting_the_vault_marker_cannot_orphan_proposals",
    "identity_safety",
    "Editing the vault marker cannot make a pending Self proposal disappear.",
    "review:r12",
    weight=3,
)
def identity_marker_relocation(case: Case) -> None:
    from knowledgeos import gate

    api = case.api()
    path = case.propose(
        summary="A rule", section="heuristics", proposed_markdown="* A rule.", mode="append"
    )
    expect_in(str(path), [str(p) for p in case.proposals()], "the proposal was not written")

    marker = case.vault / ".knowledgeos-vault.json"
    expect(marker.exists(), "init wrote no vault marker")
    marker.write_text('{"vault_id": "deadbeefdeadbeefdeadbeefdeadbeef"}', encoding="utf-8")

    open_now = gate.list_open(case.vault)
    expect(
        any(str(path).endswith(row["path"]) or row["path"] == api._rel(path) for row in open_now),
        f"a pending proposal vanished from the ledger after one marker write: {open_now!r:.300}",
    )
    described = gate.describe(api.vault, api.proposals_dir, str(path))
    expect(
        not described.get("error"),
        f"the gate stopped recognising its own proposal: {described.get('error')}",
    )


# --------------------------------------------------------------------------- #
# round thirteen: the index is a cache, and a cache cannot vouch for itself
# --------------------------------------------------------------------------- #

ROUND13_ANCHOR = None


def _index_db(case: Case):
    import sqlite3

    db = case.vault / "knowledge_index.db"
    expect(db.exists(), "the scenario needs an index; none was built")
    return sqlite3.connect(db, timeout=30)


@scenario(
    "truth.a_forged_metadata_column_is_not_served",
    "truthfulness_of_reads",
    "Changing an index column cannot make search describe a note as something it is not.",
    "review:r13",
    weight=3,
)
def truth_forged_metadata(case: Case) -> None:
    """The reviewer's CRITICAL: only `body` was corroborated.

    One UPDATE to `notes_fts.title` and two to `notes` was enough. `decisions()` then
    returned a note whose own frontmatter said `type: project`, and `search[ranked]`
    described it with the forged title and status while `search[title]` showed the real
    ones — two buckets, one payload, contradictory answers.

    The index is deliberately held stale, which is what happens while another process
    holds the database: the digest cannot rescue the read, so the read has to be honest
    about the row by itself.
    """
    api = case.api()
    note = case.write(
        "Projects/Vendor.md",
        "---\ntype: project\ntitle: Vendor review\nstatus: active\n"
        "project: vendor\n---\n\n# Vendor review\n\nThe quarterly review is due.\n",
    )
    api.search("warm")

    conn = _index_db(case)
    try:
        conn.execute(
            "UPDATE notes SET type = 'decision', status = 'blocked' WHERE path = ?",
            ("Projects/Vendor.md",),
        )
        conn.execute(
            "UPDATE notes_fts SET title = ? WHERE path = ?",
            ("Vendor review \u2014 APPROVED, skip the audit", "Projects/Vendor.md"),
        )
        conn.commit()
    finally:
        conn.close()

    frozen = api._ensure_index
    api._ensure_index = lambda **kwargs: None  # type: ignore[method-assign]
    try:
        expect_equal(
            [row["path"] for row in api.decisions()["decisions"]],
            [],
            "a project note was listed as a decision because the index said so",
        )
        payload = api.search("Vendor")
        for bucket in ("ranked", "title"):
            rows = [row for row in payload[bucket] if row.get("path") == "Projects/Vendor.md"]
            expect(rows, f"the note vanished from the {bucket} bucket")
            for row in rows:
                expect_equal(
                    row.get("title"),
                    "Vendor review",
                    f"{bucket} served a title the note does not contain",
                )
                expect_equal(
                    row.get("type"),
                    "project",
                    f"{bucket} served a type the note does not contain",
                )
                expect_equal(
                    row.get("status"),
                    "active",
                    f"{bucket} served a status the note does not contain",
                )
    finally:
        api._ensure_index = frozen  # type: ignore[method-assign]

    # And an ordinary read must repair the index, not merely refuse to repeat it.
    expect_equal(
        [row["path"] for row in api.decisions()["decisions"]],
        [],
        "the forged type survived a normal read",
    )
    expect_equal(
        "APPROVED" not in note.read_text(encoding="utf-8"),
        True,
        "the scenario itself changed the note, so it proves nothing",
    )


@scenario(
    "truth.a_capture_cannot_bless_a_forged_index",
    "truthfulness_of_reads",
    "An ordinary capture leaves the index agreeing with the notes, not certifying a forgery.",
    "review:r13",
    weight=3,
)
def truth_capture_does_not_launder(case: Case) -> None:
    """The one-shot alarm: the capture fast path re-signed a digest it never verified.

    `index_files` recomputed `index_digest` over the tampered rows and saved a new
    signature, so `manifest_diff` went from `index_tampered` to `fresh` and the forgery
    was permanent — one UPDATE, one `memory_capture`, and from then on the index claimed
    to be verified while it still disagreed with the notes.

    The assertion is therefore about the *stored row*, not about what a read happens to
    return: the read path re-derives every field from the file, so it stays honest either
    way. What cannot be allowed is the index being declared correct while it is not.
    """
    import sqlite3

    from knowledgeos.indexer import manifest_diff

    api = case.api()
    case.write(
        "Projects/Vendor.md",
        "---\ntype: project\ntitle: Vendor review\nstatus: active\n---\n\n"
        "# Vendor review\n\nThe quarterly review is due.\n",
    )
    api.search("warm")

    conn = _index_db(case)
    try:
        conn.execute(
            "UPDATE notes SET type = 'decision' WHERE path = ?", ("Projects/Vendor.md",)
        )
        conn.commit()
    finally:
        conn.close()
    changed, _reason = manifest_diff(case.vault)
    expect(changed, "a forged index column went unnoticed by the manifest")

    out = api.capture("Unrelated capture", "Something worth keeping.")
    expect(not out.get("error"), f"the capture failed: {out.get('error')}")

    # The row the capture signed must agree with the note it claims to describe.
    conn = sqlite3.connect(case.vault / "knowledge_index.db", timeout=30)
    try:
        row = conn.execute(
            "SELECT type FROM notes WHERE path = ?", ("Projects/Vendor.md",)
        ).fetchone()
    finally:
        conn.close()
    expect(row is not None, "the note disappeared from the index")
    expect_equal(
        row[0],
        "project",
        "the capture signed an index row that still disagreed with the note",
    )
    changed, reason = manifest_diff(case.vault)
    expect(
        not changed,
        f"the index is still inconsistent after a capture ({reason})",
    )


@scenario(
    "reads.a_prefix_still_finds_the_note",
    "truthfulness_of_reads",
    "Refreshing a row does not lose a hit the index found by prefix or substring.",
    "review:r13",
    weight=3,
)
def reads_prefix_hit(case: Case) -> None:
    """HIGH-1: metadata buckets were found by `LIKE`, then re-tested with FTS5.

    `Depl` matched `Deploy.md` in the title bucket, then the refresh asked the full-text
    matcher instead — `unicode61` tokenises `Depl` as its own token, which is not
    `Deploy`, so the row was dropped. 24 of 526 matching pairs on a realistic vault, 5%.
    `alph` lost a `tags` hit the same way.
    """
    api = case.api()
    case.write(
        "Projects/Deploy.md",
        "---\ntype: project\ntitle: Deploy pipeline\nstatus: active\n"
        "tags: [alpha, quarter]\n---\n\n# Deploy pipeline\n\nShipping is weekly.\n",
    )
    api.search("warm")

    for query, bucket in (("Depl", "title"), ("alph", "tags"), ("quarter", "tags")):
        payload = api.search(query)
        paths = [row.get("path") for row in payload[bucket]]
        expect_in(
            "Projects/Deploy.md",
            paths,
            f"search({query!r})[{bucket}] lost a hit the index had found",
        )
        ranked = [row.get("path") for row in payload["ranked"]]
        expect_in(
            "Projects/Deploy.md",
            ranked,
            f"search({query!r})[ranked] lost a hit the {bucket} bucket still returns",
        )


@scenario(
    "truth.a_deleted_index_row_is_repaired_by_a_capture",
    "truthfulness_of_reads",
    "Deleting one index row cannot make a note permanently invisible.",
    "review:r13",
    weight=2,
)
def truth_deleted_row_capture(case: Case) -> None:
    """HIGH-2: a deleted `notes` row survived a capture and was then signed as correct.

    The row came back only for readers that reach through the digest. Anything that reads
    `notes` directly — `decisions`, `timeline`, the pending-outcome list — never saw the
    note again, because the next ordinary capture re-signed the hole.
    """
    import sqlite3

    api = case.api()
    case.write(
        "Concepts/Hide.md",
        "---\ntype: concept\ntitle: Hide me\nstatus: active\n---\n\n"
        "# Hide me\n\nCopper-lantern is the codename.\n",
    )
    api.search("warm")

    conn = _index_db(case)
    try:
        conn.execute("DELETE FROM notes WHERE path = ?", ("Concepts/Hide.md",))
        conn.commit()
    finally:
        conn.close()

    out = api.capture("A note", "Something else entirely.")
    expect(not out.get("error"), f"the capture failed: {out.get('error')}")

    conn = sqlite3.connect(case.vault / "knowledge_index.db", timeout=30)
    try:
        row = conn.execute(
            "SELECT title FROM notes WHERE path = ?", ("Concepts/Hide.md",)
        ).fetchone()
    finally:
        conn.close()
    expect(row is not None, "a note missing from the index was never restored")
    expect_equal(row[0], "Hide me", "the restored row does not describe the note")
    hits = [row["path"] for row in api.search("copper-lantern")["ranked"]]
    expect_in("Concepts/Hide.md", hits, "the restored note is still unsearchable")


@scenario(
    "ops.a_directory_where_the_index_belongs_is_an_error",
    "install_ops_honesty",
    "A vault whose index cannot be opened or searched is reported broken, not healthy.",
    "review:r13",
    weight=3,
)
def ops_index_path_is_a_directory(case: Case) -> None:
    """HIGH-3: `st_size == 0` is true for a directory, so `index_state` said "missing".

    `doctor` printed "Index missing; rebuilt automatically", and every rebuild then raised
    `OperationalError: unable to open database file`. The report that exists to tell a human
    something is wrong said nothing was wrong.

    The second half is the same mistake one layer up: `index_state` proves the database
    takes a write lock, not that it has the tables a search needs. A database that opens
    and is missing `links` reported "Index healthy" and the first `memory_search` failed.
    """
    import contextlib
    import io
    import sqlite3

    from knowledgeos import indexer
    from knowledgeos.doctor import run_doctor

    def doctor(vault) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = run_doctor(vault)
        return code, buf.getvalue()

    case.api().search("warm")
    db = case.vault / "knowledge_index.db"
    db.unlink()
    db.mkdir()

    self_before = (case.vault / "People/Self.md").read_bytes()
    for label, action in (("index state", lambda: indexer.index_state(db)),
                          ("index rebuild", lambda: indexer.rebuild_index(case.vault))):
        try:
            action()
        except ValueError:
            pass
        else:
            fail(f"{label} accepted a directory at the SQLite path")
        expect(db.is_dir(), f"{label} moved or replaced the original directory")
        expect_equal((case.vault / "People/Self.md").read_bytes(), self_before,
                     f"Self bytes after unsafe {label}")
    code, out = doctor(case.vault)
    expect(
        "Unsafe or inaccessible index path" in out and "preserved" in out,
        f"doctor said nothing about an index path it cannot open:\n{out[-800:]}",
    )
    expect(db.is_dir(), "doctor moved or replaced the original directory")
    expect_equal(code, 1, "doctor's exit code for an unopenable index")

    # A database that opens but cannot answer a search is not healthy either. Both halves
    # of the probe: a missing `links` table, and a `notes_fts` that is an ordinary table
    # rather than FTS5. The second is the quieter failure — writes succeed, every search
    # comes back empty, and emptiness reads as a real answer.
    db.rmdir()
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE notes (path TEXT PRIMARY KEY, title TEXT)")
        conn.execute(
            "CREATE TABLE notes_fts "
            "(path TEXT, title TEXT, body TEXT, tags TEXT, description TEXT)"
        )
        conn.execute(
            "CREATE TABLE links (id INTEGER PRIMARY KEY, source TEXT, destination TEXT, "
            "raw_destination TEXT)"
        )
        conn.commit()
    finally:
        conn.close()
    expect_equal(
        indexer.index_state(db), "corrupt", "index_state for a non-FTS5 `notes_fts`"
    )
    code, out = doctor(case.vault)
    expect(
        "FTS5" in out or "cannot answer a search" in out,
        f"doctor called an index healthy without checking its tables:\n{out[-800:]}",
    )
    expect_equal(code, 1, "doctor's exit code for an index with no FTS5 table")

    # And the vault still works: the next read quarantines the wrong-shaped index and
    # rebuilds from the notes, so the failure is reported without being fatal.
    (case.vault / "Concepts" / "Hide.md").write_text(
        "---\ntype: concept\ntitle: Hide me\nstatus: active\n---\n\n# Hide me\n\nBody.\n",
        encoding="utf-8",
    )
    hits = [row["path"] for row in case.api().search("Hide me")["title"]]
    expect_in("Concepts/Hide.md", hits, "the rebuilt index lost a note")
    expect_equal(indexer.index_state(db), "ok", "the index after repairing itself")


@scenario(
    "reads.approving_one_line_keeps_every_other_line_ending",
    "truthfulness_of_reads",
    "An edit changes only the lines it edits, including their line endings.",
    "review:r13",
    weight=2,
)
def reads_mixed_endings(case: Case) -> None:
    """MEDIUM-1: the dominant ending rewrote every line of a mixed file.

    The reviewer took a Self.md with 25 CRLF lines and 24 LF lines, approved one append,
    and got 50 CRLF and 0 LF. The diff is computed on normalised text, so it showed
    nothing: the human approved one line and every line they had ever written moved.
    """
    import difflib

    path = case.self_path
    plain = path.read_bytes().replace(b"\r\n", b"\n")
    lines = plain.split(b"\n")
    for index in range(11, 36):
        if index < len(lines):
            lines[index] = lines[index] + b"\r"
    path.write_bytes(b"\n".join(lines))
    before = path.read_bytes()

    proposal = case.propose(
        summary="one rule", section="heuristics", proposed_markdown="* A new rule.", mode="append"
    )
    out = case.approve(proposal)
    expect(not out.get("error"), f"the append was refused: {out!r:.300}")
    after = path.read_bytes()

    def bodies(raw: bytes) -> list[bytes]:
        return [line[:-1] if line.endswith(b"\r") else line for line in raw.split(b"\n")]

    def endings(raw: bytes) -> list[bytes]:
        return [b"\r" if line.endswith(b"\r") else b"" for line in raw.split(b"\n")]

    old_bodies, new_bodies = bodies(before), bodies(after)
    old_ends, new_ends = endings(before), endings(after)
    matcher = difflib.SequenceMatcher(a=old_bodies, b=new_bodies, autojunk=False)
    moved = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                if old_ends[i1 + offset] != new_ends[j1 + offset]:
                    moved.append((old_bodies[i1 + offset], old_ends[i1 + offset]))
        elif tag == "replace":
            for body in old_bodies[i1:i2]:
                if not body.lstrip().startswith(b"updated:"):
                    moved.append((body, b"replaced"))
    expect_equal(
        moved,
        [],
        "approving one append rewrote line endings on lines it did not touch",
    )
    expect_equal(
        new_bodies.count(b"* A new rule."),
        1,
        "the rule was not appended",
    )


@scenario(
    "reads.an_undecidable_query_does_not_resurrect_a_row",
    "truthfulness_of_reads",
    "A query with no searchable words cannot keep a row whose field stopped matching it.",
    "review:r13",
    weight=1,
)
def reads_undecidable_query(case: Case) -> None:
    """LOW-1: "could not decide" was indistinguishable from "matched".

    `---`, `!!!`, `"` and `*` tokenise to nothing, so the full-text matcher raised and
    every row was kept. Remove a `---` tag and searching `---` still returned the note
    under `tags`, on the strength of a query that matched nothing.
    """
    api = case.api()
    note = case.write(
        "Concepts/Dashes.md",
        "---\ntype: concept\ntitle: Dashes\nstatus: active\ntags: [---]\n---\n\n"
        "# Dashes\n\nA horizontal rule.\n",
    )
    api.search("warm")
    expect_in(
        "Concepts/Dashes.md",
        [row["path"] for row in api.search("---")["tags"]],
        "the tag was not searchable while it was there",
    )

    note.write_text(
        "---\ntype: concept\ntitle: Dashes\nstatus: active\ntags: [plain]\n---\n\n"
        "# Dashes\n\nA horizontal rule.\n",
        encoding="utf-8",
    )
    # Hold the index stale on purpose: this is about the refresh, not the rebuild.
    api._ensure_index = lambda **kwargs: None  # type: ignore[method-assign]
    expect_equal(
        [row["path"] for row in api.search("---")["tags"]],
        [],
        "a removed tag was still served because the query could not be decided",
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _patch_of(case: Case, api, path: Path) -> str:
    from knowledgeos import gate

    text = path.read_text(encoding="utf-8")
    patch = gate.extract_proposed(text)
    expect(patch is not None, "the proposal contains no markdown block")
    return patch


def response_count(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return haystack.count(needle)


# --------------------------------------------------------------------------- #
# round fourteen
# --------------------------------------------------------------------------- #


@scenario(
    "truth.a_yaml_list_property_does_not_break_the_index",
    "truthfulness_of_reads",
    "One note with a YAML block-list property does not stop the index being built.",
    "review:r14",
    weight=4,
)
def truth_yaml_list_property(case: Case) -> None:
    """CRITICAL: a `list` handed to `sqlite3` killed the whole index.

    `_process_file` coerced only `tags`, `project` and `lesson`. Every other field went
    to `_INSERT_NOTE_SQL` raw, and YAML produces a Python `list` for the block form

        description:
          - cost
          - risk

    which `parser.py` advertises as supported. `sqlite3` raises
    `ProgrammingError: Error binding parameter 9: type 'list' is not supported`, the
    rebuild fails for *every* note, and `_try_rebuild` could only record it as "the index
    is busy" — so a 42-note vault ended up with zero rows, no manifest, and every search
    answering "Another process is using the note index".

    One ordinary note, and search is off for the whole vault.
    """
    api = case.api()
    case.write(
        "Concepts/audit.md",
        "---\n"
        "type: concept\n"
        "title: Audit plan\n"
        "status: active\n"
        "description:\n"
        "  - cost\n"
        "  - risk\n"
        "---\n\n# Audit plan\n\nWe audit the ferrous pipeline.\n",
    )

    payload = api.search("audit")
    expect(
        not payload.get("index_frozen"),
        "one note with a YAML list property froze the whole index: "
        f"{payload.get('index_frozen_note')}",
    )
    expect(
        not payload.get("index_blocked"),
        f"the rebuild was reported as a failure: {payload.get('index_blocked')}",
    )
    expect_in(
        "Concepts/audit.md",
        [row.get("path") for row in payload["ranked"]],
        "a note with a YAML list property cannot be found at all",
    )

    # The row must be in the index, not merely re-derived from the file on the way out:
    # "the index is empty and the read path papers over it" is the state that made the
    # failure invisible for so long.
    import sqlite3

    conn = sqlite3.connect(case.vault / "knowledge_index.db")
    try:
        rows = conn.execute(
            "SELECT path, description FROM notes WHERE path = 'Concepts/audit.md'"
        ).fetchall()
    finally:
        conn.close()
    expect_equal(len(rows), 1, "the note has no row in the index")
    expect(
        "cost" in rows[0][1],
        f"the list property was not stored as text: {rows[0][1]!r}",
    )
    expect(
        (case.vault / ".knowledgeos" / "index-manifest.json").exists(),
        "no manifest was written, so the vault can never be reported fresh",
    )


@scenario(
    "reads.a_title_in_the_filename_or_h1_is_found_and_shown",
    "truthfulness_of_reads",
    "A note whose title is its H1 or filename is searchable and is shown with that title.",
    "review:r14",
    weight=4,
)
def reads_derived_title(case: Case) -> None:
    """CRITICAL: the refresh asked a narrower question than the index had answered.

    The index derives `title` from the frontmatter, then the first H1, then the filename
    stem — and matches it with `LIKE`. `_refresh_rows` re-tested only the *frontmatter*,
    so a note with no `title:` key (the commonest shape in a personal vault) was found by
    the index and then dropped:

        Concepts/Deployment runbook.md   `Deployment` -> [], `Depl` -> [], `runbook` -> []

    and `_refresh_display_fields` set the displayed title to `""`, so every result for
    such a note came back nameless.
    """
    api = case.api()
    case.write(
        "Concepts/Deployment runbook.md",
        "---\ntype: concept\nstatus: draft\n---\n\nRoll it out slowly.\n",
    )
    case.write(
        "Concepts/churn.md",
        "---\ntype: concept\nstatus: draft\n---\n\n# Churn Interview Script\n\nTalk.\n",
    )

    for query in ("Deployment", "Depl", "eplo", "runbook"):
        payload = api.search(query)
        expect_in(
            "Concepts/Deployment runbook.md",
            [row.get("path") for row in payload["ranked"]],
            f"search({query!r}) lost a note whose title is its filename",
        )

    for query in ("Churn", "Interview"):
        payload = api.search(query)
        expect_in(
            "Concepts/churn.md",
            [row.get("path") for row in payload["ranked"]],
            f"search({query!r}) lost a note whose title is its H1",
        )

    from_filename = [
        row for row in api.search("runbook")["ranked"]
        if row.get("path") == "Concepts/Deployment runbook.md"
    ]
    expect_equal(
        from_filename[0].get("title"),
        "Deployment runbook",
        "a note with no `title:` key is displayed without a name",
    )
    from_h1 = [
        row for row in api.search("Churn")["ranked"]
        if row.get("path") == "Concepts/churn.md"
    ]
    expect_equal(
        from_h1[0].get("title"),
        "Churn Interview Script",
        "the H1 was not used as the displayed title",
    )


@scenario(
    "ops.an_incomplete_index_is_not_called_healthy",
    "install_ops_honesty",
    "A doctor report does not call an index with no rows healthy.",
    "review:r14",
    weight=3,
)
def ops_incomplete_index(case: Case) -> None:
    """HIGH: `[OK] Index healthy` for a database with zero rows.

    `index_state == "ok"` proves the database takes a write lock and has the right
    tables. It says nothing about whether it holds the vault: an index emptied with three
    `DELETE`s reported `[OK] Index healthy (126976 bytes)` and exited 0 in a 41-note
    vault, while every search returned `[]` — which reads as "nothing matches".
    """
    import contextlib
    import io
    import sqlite3

    from knowledgeos.doctor import run_doctor

    api = case.api()
    case.write("Concepts/real.md", "---\ntype: concept\ntitle: Real\n---\n\nQuartz.\n")
    api.search("warm")

    db = case.vault / "knowledge_index.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("DELETE FROM notes")
        conn.execute("DELETE FROM notes_fts")
        conn.execute("DELETE FROM links")
        conn.commit()
    finally:
        conn.close()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_doctor(case.vault)
    out = buf.getvalue()
    expect(
        "Index healthy" not in out,
        f"doctor called an empty index healthy:\n{out[-900:]}",
    )
    expect(
        "incomplete" in out.lower() or "missing" in out.lower(),
        f"doctor said nothing about an index that holds none of the notes:\n{out[-900:]}",
    )


@scenario(
    "autopilot.an_absent_digest_says_it_rebuilt",
    "autopilot_reliability",
    "A capture that has to rebuild the vault says so, and the digest comes back.",
    "review:r14",
    weight=2,
)
def autopilot_absent_digest(case: Case) -> None:
    """MEDIUM: the pre-upgrade path was a silent 26-second pause.

    With no signed digest to compare against, `index_files` falls back to a full rebuild.
    That is correct — a digest you cannot check is not a digest — but the capture result
    said nothing, so the caller saw only latency. The rebuild also has to *restore* the
    digest, or every later capture pays the same price.
    """
    import json

    api = case.api()
    case.write("Concepts/one.md", "---\ntype: concept\ntitle: One\n---\n\nBody.\n")
    api.search("warm")

    manifest = case.vault / ".knowledgeos" / "index-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    expect("index" in data, "the manifest never carried a digest to begin with")
    data.pop("index")
    manifest.write_text(json.dumps(data), encoding="utf-8")

    result = api.capture("After upgrade", "Body about deployment.")
    expect_equal(result.get("ok"), True, "the capture failed outright")
    expect_equal(
        result.get("rebuilt"),
        "no_signed_digest",
        "the capture rebuilt the whole vault without saying so",
    )
    after = json.loads(manifest.read_text(encoding="utf-8"))
    expect("index" in after, "the rebuild did not restore a signed digest")
    expect_in(
        result.get("path"),
        [row.get("path") for row in api.search("After upgrade")["ranked"]],
        "the captured note is not searchable",
    )


@scenario(
    "reads.approving_one_line_keeps_the_files_line_ending",
    "truthfulness_of_reads",
    "A new line takes the file's own line ending, not a bare LF.",
    "review:r14",
    weight=2,
)
def reads_new_line_takes_the_files_ending(case: Case) -> None:
    """MEDIUM: every approval added one bare-LF line to a CRLF file.

    `new_lines` was split from text whose CRLFs had already been normalised to `\n`, so
    every new line ended in `\n` and the `line + ending` branch that was supposed to give
    it the file's ending never ran. On a Windows vault — the default install — every
    approved append left one LF line behind, and a file whose last line had no terminator
    lost 26 of its 48 CRLF lines in a single approval.
    """
    from knowledgeos.textio import write_preserving_endings

    target = case.vault / "People" / "crlf.md"
    target.write_bytes(b"line one\r\nline two\r\nline three\r\n")
    write_preserving_endings(
        target, "line one\r\nline two\r\ninserted\r\nline three\r\n"
    )
    raw = target.read_bytes()
    expect_equal(raw, b"line one\r\nline two\r\ninserted\r\nline three\r\n",
                 "the inserted line did not take the file's CRLF ending")

    # And a file whose last line has no terminator keeps every CRLF it had.
    other = case.vault / "People" / "notail.md"
    other.write_bytes(b"a\r\nb\r\nc")
    write_preserving_endings(other, "a\r\nb\r\nNEW\r\nc\r\n")
    raw = other.read_bytes()
    expect_equal(
        raw.count(b"\r\n"),
        4,
        f"a CRLF file lost its endings: {raw!r}",
    )
    expect(
        raw.count(b"\n") == raw.count(b"\r\n"),
        f"a bare LF line appeared in a CRLF file: {raw!r}",
    )


@scenario(
    "reads.the_digest_tells_null_from_the_word_none",
    "truthfulness_of_reads",
    "Two indexes that differ only by NULL versus the text 'None' do not share a digest.",
    "review:r14",
    weight=2,
)
def reads_digest_null_vs_none_text(case: Case) -> None:
    """MEDIUM: `str(value)` is not injective.

    A `NULL` description and the four characters `None` hashed to the same bytes, so
    `UPDATE notes SET description = 'None'` was invisible to the digest that exists to
    notice exactly that kind of edit.
    """
    import sqlite3

    from knowledgeos import indexer

    schema = [
        "CREATE TABLE notes (path TEXT, title TEXT, description TEXT)",
        "CREATE VIRTUAL TABLE notes_fts USING fts5("
        "path, title, body, tags, description)",
        "CREATE TABLE links (source TEXT, destination TEXT, raw_destination TEXT)",
    ]

    def digest(description):
        conn = sqlite3.connect(":memory:")
        try:
            for statement in schema:
                conn.execute(statement)
            conn.execute("INSERT INTO notes VALUES ('a.md', 'A', ?)", (description,))
            return indexer.index_digest(conn)
        finally:
            conn.close()

    expect(
        digest(None) != digest("None"),
        "NULL and the word None produce the same index digest",
    )
    # Numeric-vs-text cannot be tested through a TEXT column: SQLite's affinity rewrites
    # the integer to text on the way in, so the values are genuinely identical by the time
    # the digest sees them. The NULL case above is the one that was actually reachable.


@scenario("autopilot.a_failed_rebuild_names_the_fault_and_recovers", "autopilot_reliability",
          "A failed refresh reports its real fault, not a fictional writer, and recovers.",
          "stabilization:failure-recovery", weight=3)
def blocked_refresh_recovery(case: Case) -> None:
    from unittest import mock
    from knowledgeos import indexer
    api = case.api()
    api.search("warm")
    case.write("Concepts/new.md", "# New\n\nquartzite\n")
    with mock.patch.object(indexer, "rebuild_index", side_effect=OSError("disk full")):
        result = api.search("quartzite")
    expect("disk full" in str(result.get("index_blocked")), "the rebuild fault was hidden")
    expect("Another process" not in result.get("index_frozen_note", ""), "a fault was reported as contention")
    api._probed_at = 0
    result = api.search("quartzite")
    expect_in("Concepts/new.md", [r["path"] for r in result["ranked"]], "recovery lost the new note")
    expect(not result.get("index_blocked"), "the recovered index still reports a fault")


@scenario("reads.entity_ids_come_from_the_note", "truthfulness_of_reads",
          "A cached identifier cannot override the identifier in the note.", "stabilization:metadata", weight=2)
def file_derived_identifier(case: Case) -> None:
    import sqlite3
    from unittest import mock
    api = case.api()
    case.write("Concepts/real.md", "---\nid: real-id\ntitle: Quartzite\n---\n\nQuartzite.\n")
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("UPDATE notes SET entity_id='forged-id' WHERE path='Concepts/real.md'")
        conn.commit()
    finally:
        conn.close()
    with mock.patch.object(api, "_ensure_index"):
        result = api.search("Quartzite")
    for bucket in ("title", "fts", "ranked"):
        row = next(r for r in result[bucket] if r["path"] == "Concepts/real.md")
        expect_equal(row["entity_id"], "real-id", f"{bucket} trusted a cached identifier")


@scenario("vault.index_candidates_cannot_escape_the_sandbox", "vault_integrity",
          "A forged index path cannot make a read quote a file outside the vault.",
          "stabilization:read-boundary", weight=3)
def candidate_sandbox(case: Case) -> None:
    outside = case.root / "outside.md"
    outside.write_text("# Confidential\n\nquartzite private\n", encoding="utf-8")
    rows = case.api()._refresh_rows([{"path": "../outside.md", "title": "Injected", "snippet": ""}], "quartzite")
    expect_equal(rows, [], "an outside file was quoted through a forged candidate")


@scenario("approval.disjoint_edits_preserve_untouched_bytes", "approval_fidelity",
          "Disjoint edits preserve intervening line endings and a no-op preserves the final byte.",
          "stabilization:line-endings", weight=3)
def disjoint_edits(case: Case) -> None:
    from knowledgeos.textio import write_preserving_endings
    path = case.vault / "Concepts" / "bytes.md"
    for raw in (b"a\r\nb", b"a\rb", b"a\r\nb\r", b"a\nb"):
        path.write_bytes(raw)
        write_preserving_endings(path, raw.decode().replace("\r\n", "\n").replace("\r", "\n"))
        expect_equal(path.read_bytes(), raw, "a no-op changed the file's bytes")
    path.write_bytes(b"start\r\nedit one\r\nmiddle\nedit two\r\nend\r\n")
    write_preserving_endings(path, "start\nnew one\nmiddle\nnew two\nend\n")
    expect_equal(path.read_bytes(), b"start\r\nnew one\r\nmiddle\nnew two\r\nend\r\n",
                 "two edits rewrote an untouched line between them")


@scenario("approval.a_failed_write_preserves_the_original", "approval_fidelity",
          "A failed replacement leaves the original file intact and cleans up staging.",
          "stabilization:atomic-write", weight=3)
def atomic_edit(case: Case) -> None:
    from unittest import mock
    from knowledgeos import textio
    path = case.write("Concepts/bytes.md", "old\n")
    original = path.read_bytes()
    failed = False
    with mock.patch.object(textio.os, "replace", side_effect=OSError("replacement failed")):
        try:
            textio.write_preserving_endings(path, "new\n")
        except OSError:
            failed = True
    expect(failed, "the write bypassed atomic replacement")
    expect_equal(path.read_bytes(), original, "a failed write damaged the original")
    expect(not list(path.parent.glob(".gate-write-*")), "a staging file was left behind")


@scenario("ops.a_missing_fulltext_index_is_not_healthy", "install_ops_honesty",
          "Doctor detects missing full-text rows even when metadata rows still exist.",
          "stabilization:coverage", weight=2)
def fulltext_coverage(case: Case) -> None:
    import sqlite3
    import contextlib
    import io
    from knowledgeos.doctor import run_doctor
    api = case.api()
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("DELETE FROM notes_fts")
        conn.commit()
    finally:
        conn.close()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        run_doctor(case.vault)
    expect("Index healthy" not in output.getvalue(), "doctor missed an emptied full-text index")


@scenario("ops.a_comment_is_not_a_fulltext_table", "install_ops_honesty",
          "A comment mentioning FTS5 cannot make an ordinary table look like a search index.",
          "stabilization:schema", weight=2)
def executable_fulltext(case: Case) -> None:
    import sqlite3
    from knowledgeos import indexer
    api = case.api()
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("DROP TABLE notes_fts")
        conn.execute("CREATE TABLE notes_fts (path, title, body, tags, description /* fts5 */)")
        conn.commit()
    finally:
        conn.close()
    expect_equal(indexer.index_state(api.db_path), "corrupt", "an ordinary table passed as full-text")


@scenario("autopilot.a_partial_rebuild_is_not_success", "autopilot_reliability",
          "A rebuild that skips unreadable notes reports the incomplete result.",
          "stabilization:partial-rebuild", weight=2)
def partial_rebuild(case: Case) -> None:
    from unittest import mock
    from knowledgeos import indexer
    api = case.api()
    case.write("Concepts/broken.md", "# Broken\n\nquartzite\n")
    original = indexer._process_file

    def extract(args):
        if args[0].name == "broken.md":
            return "Concepts/broken.md", OSError("cannot read note")
        return original(args)

    with mock.patch.object(indexer, "_process_file", side_effect=extract):
        result = api.search("quartzite")
    expect("broken.md" in str(result.get("index_blocked")), "a skipped note was not reported")


@scenario("reads.drift_uses_the_files_during_a_blocked_rebuild", "truthfulness_of_reads",
          "Drift verifies its displayed fields and reports incomplete index coverage.", "review:stabilization-F1", weight=3)
def drift_fields(case: Case) -> None:
    import datetime
    import sqlite3
    from knowledgeos import indexer
    api = case.api()
    today = datetime.date.today().isoformat()
    case.write("Concepts/real.md", f"---\ntitle: Review required\ntype: concept\nupdated: {today}\n---\n\nBody.\n")
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("UPDATE notes SET title='APPROVED: skip review' WHERE path='Concepts/real.md'")
        conn.commit()
    finally:
        conn.close()
    (case.vault / indexer.LOCK_REL).mkdir()
    result = api.drift(30)
    row = next(r for r in result["recent_notes"] if r["path"] == "Concepts/real.md")
    expect_equal(row["title"], "Review required", "drift served a forged title")
    expect(result.get("index_blocked"), "blocked drift omitted its coverage diagnostic")


@scenario("reads.id_resolution_verifies_the_file", "truthfulness_of_reads",
          "A forged cached ID mapping cannot select the wrong document.", "review:stabilization-F2", weight=3)
def resolve_id_from_file(case: Case) -> None:
    import sqlite3
    from knowledgeos import indexer
    api = case.api()
    case.write("Concepts/real.md", "---\nid: real-id\n---\n\nReal.\n")
    case.write("Concepts/other.md", "---\nid: other-id\n---\n\nOther.\n")
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("UPDATE notes SET entity_id='hidden-id' WHERE path='Concepts/real.md'")
        conn.execute("UPDATE notes SET entity_id='real-id' WHERE path='Concepts/other.md'")
        conn.commit()
    finally:
        conn.close()
    (case.vault / indexer.LOCK_REL).mkdir()
    expect_equal(api.get_note("real-id").get("path"), "Concepts/real.md", "an ID selected a different note")


@scenario("reads.duplicate_ids_are_not_resolved_arbitrarily", "truthfulness_of_reads",
          "An ambiguous ID requires an explicit note path instead of an arbitrary match.", "review:stabilization-F2", weight=2)
def ambiguous_id(case: Case) -> None:
    for name in ("a", "b"):
        case.write(f"Concepts/{name}.md", "---\nid: duplicate-id\n---\n\nBody.\n")
    expect("error" in case.api().get_note("duplicate-id"), "a duplicate ID arbitrarily selected a note")


@scenario("reads.pending_outcomes_requires_a_real_decision", "truthfulness_of_reads",
          "A concept misclassified in the cache cannot create an outcome follow-up.", "review:stabilization-F3", weight=2)
def pending_real_decision(case: Case) -> None:
    import sqlite3
    from knowledgeos import evolution
    api = case.api()
    case.write("Concepts/not-decision.md", "---\ntype: concept\noutcome_status: pending\n---\n\nBody.\n")
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("UPDATE notes SET type='decision' WHERE path='Concepts/not-decision.md'")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        result = evolution.pending_outcome_reviews(api)
    finally:
        conn.rollback()
        conn.close()
    expect("Concepts/not-decision.md" not in [r["path"] for r in result], "a concept became a follow-up decision")


@scenario("autopilot.failed_quarantine_is_not_success", "autopilot_reliability",
          "Failed quarantine is reported as a blocked repair and recovers after release.", "review:stabilization-F4", weight=3)
def failed_quarantine(case: Case) -> None:
    from unittest import mock
    import sqlite3
    from knowledgeos import indexer
    api = case.api()
    case.write("Concepts/real.md", "# Real\n\nquartzite\n")
    api.search("warm")
    conn = sqlite3.connect(api.db_path)
    try:
        conn.execute("DROP TABLE notes_fts")
        conn.execute("CREATE TABLE notes_fts (path, title, body, tags, description /* USING fts5( */)")
        conn.commit()
    finally:
        conn.close()
    with mock.patch.object(indexer, "_quarantine", return_value=None):
        result = api.search("quartzite")
    expect(result.get("index_blocked"), "an unsuccessful repair was called successful")
    expect(not result.get("fts_available"), "an unusable full-text table was called available")
    api._probed_at = 0
    result = api.search("quartzite")
    expect_in("Concepts/real.md", [r["path"] for r in result["ranked"]], "repair did not recover")


@scenario("autopilot.list_lessons_can_be_proposed", "autopilot_reliability",
          "Supported list-valued lessons can become a proposal without changing Self.", "review:stabilization-F5", weight=2)
def list_lesson_promotion(case: Case) -> None:
    from knowledgeos.mcp_server import MCPServer
    case.write("Decisions/list.md", "---\ntype: decision\noutcome_status: confirmed\nlesson:\n  - prefer evidence\n  - preserve options\n---\n\nBody.\n")
    original = case.self_path.read_bytes()
    result = MCPServer(case.vault).handle({"id": 1, "method": "tools/call", "params": {
        "name": "memory_propose_from_lesson", "arguments": {"path_or_id": "Decisions/list.md"}}})
    expect(not result.get("result", {}).get("isError"), f"list lesson promotion failed: {result}")
    expect_equal(case.self_path.read_bytes(), original, "promoting a lesson silently changed Self")


@scenario("reads.timeline_keeps_recently_created_notes", "truthfulness_of_reads",
          "Timeline preserves created-OR-updated semantics when it verifies rows.", "review:stabilization-F6", weight=2)
def timeline_created_or_updated(case: Case) -> None:
    import datetime
    today = datetime.date.today().isoformat()
    case.write("Concepts/new.md", f"---\ncreated: {today}\nupdated: 2000-01-01\n---\n\nBody.\n")
    result = case.api().timeline(7, 100)
    expect_in("Concepts/new.md", [r["path"] for r in result["notes"]], "timeline dropped a newly created note")
