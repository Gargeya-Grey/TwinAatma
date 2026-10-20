# Verify an installed vault move through native Codex

Use one passing current Windows wheel artifact report and one passing current Windows binary artifact report. Preserve the build manifests, installations, product source, verifier files, and named isolation sentinels throughout observation and grading.

For each artifact, run the integrated producer from the repository root. Use a different fresh output directory for each run.

```powershell
& 'C:/Python313/python.exe' -B .agents/skills/verify-twinaatma/scripts/installed_move.py --artifact-report '<current-Windows-artifact-report.json>' --output 'work/gc-artifacts/.knowledgeos/<current-run>/native-move-wheel'
```

The producer uses native Codex 0.163.0 with its pinned executable hash and a new credential-free profile. It sends no model turn or approval answer. The configured server's original bytes remain unchanged in three phases. Native calls read the original vault before the move, the relocated vault while the old path is absent, and the relocated vault after a distinct unrelated vault reuses the old path. Exact note hashes, relative links, stable IDs, full inventories, raw protocol, kernel parent and launch identity, and actual shutdown remain retained.

The observation report says `NOT GRADED`. A zero producer exit records successful observation capture. It does not assert that relocation passed.

For a separate Windows diagnosis, grade the exact printed report and its SHA256. Retain a new output file.

```powershell
& 'C:/Python313/python.exe' -B .agents/skills/verify-twinaatma/scripts/grade_installed_move.py --report '<original-report.json>' --expected-report-sha256 '<original-report-SHA256>' --output 'work/gc-artifacts/.knowledgeos/<current-run>/native-move-wheel.grade.json'
```

The cumulative scorer does not consume that cached result. It reruns the independent grader under the exact hash-pinned Windows CPython 3.14.7 runtime. The bridge binds the original report, complete current product hashes, producer, grader, support helpers, acceptance and artifact helpers, runtime, declared dependency manifest, and a new nonce.

For a Linux cumulative scorer without Windows executable interop, create a new contained base channel directory. Create one empty child for each original report, named `installed-move-<full report SHA256>`. In separate task-owned Windows processes, run the pinned watcher against each child.

```powershell
& 'W:/AI-Projects/TwinAatma/work/gc-artifacts/.knowledgeos/runtime-hooks-20261019/runtimes/additional/cpython-3.14.7-windows-x86_64-none/python.exe' -I -B .agents/skills/verify-twinaatma/scripts/native_grader_rendezvous.py --watch 'W:/AI-Projects/TwinAatma/work/gc-artifacts/.knowledgeos/<current-run>/move-grade-channel/installed-move-<full-report-SHA256>'
```

Supply both original reports to the Linux scorer with repeated `--installed-move-report`. Pass the Linux path of their base channel through `--installed-move-native-rendezvous`. Keep the existing advanced-host channel separate.

The Windows helper checks the current retained artifact and original observations. The Linux scorer checks the fresh response and actual stopped child receipt. A missing cell earns no partial credit. A failed supplied run remains failed. The complete passing Windows pair can verify only `PORT.same_device_move` in the unchanged 54-outcome rubric.

Retain every attempted report, failed predecessor, transcript, fixture, and signing-state directory. Register only real task evidence through the observer workflow. No clean-device restore, other host, Linux relocation, model conversation, elapsed use, performance, or independent human approval is established by this journey.
