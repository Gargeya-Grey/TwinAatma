# Verification status

This is a development checkpoint dated 20 October 2026. Product readiness remains
unverified. The acceptance target is fixed at 54 outcomes in the
[verification contract](../.agents/skills/verify-twinaatma/references/acceptance-scoring.md).
Passing regression tests alone does not establish those outcomes.

The last accepted historical cumulative snapshot verified 37 of 54 outcomes, with
17 unresolved. Subsequent repairs have focused proof, but no valid current
cumulative snapshot has been produced. Do not present 37/54 as the current score.

On the retained pre-publication snapshot, the Windows relocation grader binds the installed launcher to its exact
virtual-environment and base-Python processes. Its focused controls improved from
23/43 to 43/43. Both the wheel and executable pass all three relocation phases
through the native Windows grading bridge. Eleven related regression tests pass.
These results do not independently award cumulative acceptance credit.

The publication review subsequently found and repaired duplicate frame-length
handling, repeated corrupt-session backup replacement, and diagnostics that crashed
when remembering-policy state was unavailable. These source changes
require fresh package and host evidence before older installed observations can
be treated as current. The older observations remain retained as historical proof.

Current limits include the following.

- Linux runtime evidence cannot be fully revalidated from Windows. One interpreter
  chain ends at `/usr/bin/python3.12` inside the stopped distribution. Its current
  file is outside the retained Windows-accessible evidence. Keep the Linux matrix
  requirements unresolved. WSL must stay stopped on the owner's machine.
- The nine authorized synthetic host conversations ran once. The six installed
  wheel/executable conversations retain their original proof. Advanced-host
  outcomes remain withheld because a protected state hash changed after the trial.
  No additional model trial is authorized by this checkpoint.
- The frozen retrieval evaluation still fails its critical targets. The subsequent
  retrieval candidate was rejected for integration after independent review found
  two attribution regressions.
- Independent owner-terminal approval remains pending at the owner's request.
  Representative elapsed use, clean-device restore and performance-budget
  acceptance remain separate requirements.

Local run directories, transcripts, signing state and handoff receipts are retained
on the development machine and excluded from Git. The reusable verification skill,
rubric, drivers and regression tests are committed as source. Historical failures
remain retained; an inaccessible prerequisite is never converted into a pass.
