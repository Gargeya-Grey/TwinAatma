# Single host-chat batch for a new product freeze

Keep the v1 rubric unchanged. This recipe gets nine genuine Codex CLI chats ready and runs
them once: three installed-wheel chats, three installed-executable chats and three
advanced-source chats. The first two units use `installed_host.py`. The advanced-source unit
uses the staged producer and `advanced_host_acceptance.py`. Nothing here changes which
evidence awards which outcome.

## One binding

`scripts/host-freeze-pin.json` is the only place that names a freeze. It holds the freeze
folder, the SHA-256 of that folder's `batch-seal.json`, and the host identity (Codex
executable path and hash, version, configured model). The seal holds the hash of
`product-freeze.json` and of six support files: `advanced_host.py`, `controls.py`,
`expectations.json`, `prepared.json`, `private/input.json` and
`outbound-payload-review.json`. `scripts/host_freeze.py` reads the pin. The grader
(`advanced_host_acceptance.py`), the native bridge (`advanced_host_native.py`) and
`host_batch.py` use it and nothing else.

A new freeze needs one new pin, written by `host_batch.py prepare --write-pin`. Counts come from
the freeze file and the live tree. The validator still refuses:

- a swapped or edited freeze (the seal names its hash);
- a swapped seal (the pin names its hash);
- a swapped preparation, producer, controls, expectations or payload inventory;
- a changed product, or a changed set of product files (the live tree must equal the freeze);
- an authorization bound to another freeze or inventory, and a reused or late claim;
- a changed Codex executable, version or model.

The bridge also binds the pin and `host_freeze.py` into every native grading request.
The staged producer checks the complete source file set, including files added after
preparation. The freeze reader requires the unchanged v1 rubric hash and refuses linked
product inputs. Proposed pins receive the same seal and support checks as the active pin.

## Runbook

Step 4 is the only step that calls a model. Do steps 2 and 4 on the same calendar day.
The reviewed advanced-source payload holds the initial notes, which carry the creation date.

1. Freeze the product. Commit it. Build the wheel and the executable and install each into an
   isolated environment. Zero model.

   ```powershell
   python -B .agents/skills/verify-twinaatma/scripts/build.py --output work/gc-artifacts/.knowledgeos/installed-proof
   python -B .agents/skills/verify-twinaatma/scripts/artifact.py --wheel <build>/wheel/<candidate>.whl --output work/gc-artifacts/.knowledgeos/installed-proof/wheel
   python -B .agents/skills/verify-twinaatma/scripts/artifact.py --binary <build>/dist/twinaatma/twinaatma.exe --build-manifest <build>/build-manifest.json --output work/gc-artifacts/.knowledgeos/installed-proof/binary
   ```

2. Prepare. Zero model. It stops before the first model call.

   ```powershell
   python -B .agents/skills/verify-twinaatma/scripts/host_batch.py prepare --wheel-report <wheel>/report.json --binary-report <binary>/report.json --baseline <baseline.json> --write-pin
   ```

   In order it: writes `product-freeze.json` (schema `twinaatma.C-product-freeze/v1`) from the
   live tree and refuses uncommitted product files; stages the producer and controls from
   `scripts/staged/`; runs `advanced_host.py --prepare`; starts one init-only synthetic vault
   (init, doctor, setup-host, `codex --version`); runs the offline controls (grader
   corruption controls, proxy control, date control); builds
   `outbound-payload-review.json`; writes `batch-seal.json`; writes the pin; prints the commands.
   A failed preparation moves its folder to `<name>.failed-<time>` and is never reused.
   Without `--write-pin` the proposed pin stays in the freeze folder.

3. Record the direct human approval. Print the record, fill the human fields, save it as
   `<freeze>/human-trial-authorization.json`, then check. Zero model.

   ```powershell
   python -B .agents/skills/verify-twinaatma/scripts/host_batch.py authorization-template
   python -B .agents/skills/verify-twinaatma/scripts/host_batch.py check
   ```

   The validator and the runner need these fields:

   | Field | Required value |
   |---|---|
   | `status` | `approved` |
   | `direct_user_reply` | non-empty text of the human reply |
   | `product_freeze_sha256` | SHA-256 of `<freeze>/product-freeze.json` |
   | `payload_inventory_sha256` | SHA-256 of `<freeze>/outbound-payload-review.json` |
   | `allowed_units` | `installed-wheel`, `installed-binary`, `advanced-source`, each integer 3 |
   | `maximum_model_conversations` | integer 9 |
   | `model` | the pinned configured model |
   | `single_use` | `true` |
   | `automatic_retries` | `false` |
   | `recorded_ns` | positive integer, set when the human reply is recorded |
   | `schema`, `source`, `question_item_id`, `approved_scope`, `destination`, `owner_terminal_gate` | descriptive text, as in the template |

   The grader, staged producer and batch runner require the bound hashes, model, nine-chat
   maximum, single-use flag, disabled retries and recording time. The advanced-source
   grader also requires its unit claim to precede the first model launch.

4. Run the nine chats. This calls a model, once, without retries.

   ```powershell
   python -B -X utf8 .agents/skills/verify-twinaatma/scripts/host_batch.py chats --allow-model-calls --codex <pinned codex.exe>
   ```

   The command refuses without the flag, without an authorization bound to the pin, with a
   stale product, with a changed Codex executable, and a second time. For each unit it writes a
   single-use unit claim, then starts the unit in its own child. Before every `codex exec` the
   launch guard checks the exact prompt, the exact argv, the proxy configuration and the initial
   notes against the reviewed inventory and writes a reservation. Reports land in
   `<freeze>/installed-wheel/<run>/`, `<freeze>/installed-binary/<run>/` and
   `<freeze>/native-<run>/`.

   Immediately before each reservation, the guard reloads the pin, seal, support files,
   complete product inventory, destination configuration and authorization. It refuses a
   changed authorization or Codex executable before starting the conversation.

5. Grade. Zero model. Run on native Windows in the main checkout with the pinned CPython 3.14.7
   runtime, as `SKILL.md` describes. `host_batch.py commands` prints the host and advanced options.
   Pass the three host reports with `--host-report` (wheel, executable) and
   `--advanced-host-report` (advanced-source), together with the source, artifact and baseline
   options.

`host_batch.py commands` prints every command above for the pinned freeze. `host_batch.py check`
starts nothing.

The staged producer refuses standalone `--run` before constructing a journey or
starting a child. Use the guarded batch command for conversations. The printed
plan names the producer modules loaded by each guarded launcher.

Run the zero-model binding and tampering controls with:

```powershell
python -B -m unittest discover -s tests -p test_host_batch.py
```

These controls use synthetic authorization records in temporary test folders. They cannot
authorize a retained batch. Keep a preparation dry run's reports separate from installed
artifact proof if its artifact descriptors are test fixtures. Such a run receives no fixed54 credit.

## Limits

- `acceptance.retained_path` maps any `W:/AI-Projects/TwinAatma/` path onto the current checkout
  root. Installed-artifact validation therefore works only in the main checkout, not in a nested
  worktree.
- Native grading needs the main checkout path, the hash-pinned CPython 3.14.7 runtime and the
  vendored PyYAML under `work/gc-artifacts/.knowledgeos`. They are not part of a freeze.
- Short synthetic chats do not establish desktop, clean-device, owner approval or
  representative-week acceptance.
