# sb3gen Complete Guide (English)

**sb3gen** is a CLI tool that generates and iteratively edits Scratch 3.0 project files
(`.sb3`) purely from natural-language instructions. This guide covers everything from
setup to the internal architecture.

---

## Table of Contents

1. [What This Is](#1-what-this-is)
2. [Requirements & Setup](#2-requirements--setup)
3. [Quick Start](#3-quick-start)
4. [CLI Reference](#4-cli-reference)
5. [Overall Architecture](#5-overall-architecture)
6. [From Instruction to Project (Internal Flow)](#6-from-instruction-to-project-internal-flow)
7. [Clarification Flow](#7-clarification-flow)
8. [Data Model (ProjectSpec)](#8-data-model-projectspec)
9. [Supported Blocks & Extensions](#9-supported-blocks--extensions)
10. [Custom Blocks (My Blocks / Procedures)](#10-custom-blocks-my-blocks--procedures)
11. [Asset Handling (Costumes & Sounds)](#11-asset-handling-costumes--sounds)
12. [Continuing an Existing Project (--input)](#12-continuing-an-existing-project---input)
13. [LLM Output Stabilization](#13-llm-output-stabilization)
14. [Known Limitations](#14-known-limitations)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. What This Is

sb3gen takes a natural-language instruction such as "add a cat sprite and make it jump"
and has an LLM (OpenAI or Gemini) turn it directly into a `.sb3` file that Scratch 3.0
can open.

Highlights:
- Can **create from scratch** or **load and continue editing** an existing `.sb3`.
- If an instruction is ambiguous, it **asks a clarifying question in the terminal**
  instead of crashing.
- Supports adding/modifying/removing sprites, editing global variables/lists/broadcasts,
  custom blocks (procedures), and Pen/Music extension blocks.
- Uses a **plan-then-generate-piece-by-piece** strategy rather than one giant LLM call,
  to avoid broken/truncated JSON output.

---

## 2. Requirements & Setup

- Python 3.8+ (the codebase deliberately avoids `typing.Literal[*tuple(...)]` unpacking
  syntax, which only works on Python 3.11+, so it stays compatible with older versions).
- Dependencies: `pydantic`, plus `openai` or `google-genai` depending on which provider
  you use.

```bash
pip install pydantic openai google-genai
```

Set the relevant API key as an environment variable (you only need the one you use):

```bash
# For OpenAI
export OPENAI_API_KEY="sk-..."

# For Gemini
export GEMINI_API_KEY="..."
# or
export GOOGLE_API_KEY="..."

# Optional: override the Gemini model (defaults to the value baked into run.py)
export GEMINI_MODEL="gemini-2.0-flash"
```

If both keys are present and `--provider` is not specified, **OpenAI is preferred**.

---

## 3. Quick Start

```bash
# Create a new project with the built-in default instruction
python run.py

# Create a new project with a specific instruction
python run.py "when the flag is clicked, make the cat move 10 steps"

# Load an existing project and keep editing it (overwrites the same file by default)
python run.py --input my_game.sb3 "make the cat twice as big"
```

Once generation finishes, open the resulting `.sb3` directly in Scratch
(scratch.mit.edu or Scratch Desktop) to inspect it.

---

## 4. CLI Reference

`run.py` supports the following arguments:

| Argument | Type | Purpose | Default behavior |
|---|---|---|---|
| `instruction` | positional, optional | Natural-language instruction | Uses a built-in default instruction (add a red circle sprite, move 10 steps) |
| `--provider` | option | Which LLM to use (`openai`/`gemini`) | Auto-detected from `LLM_PROVIDER` env var, then from whichever API key is set (OpenAI wins if both) |
| `--output` | option | Output `.sb3` path | Overwrites `--input`'s file if given; otherwise a new timestamped filename is generated |
| `--input` | option | Existing `.sb3` to continue editing | Starts from an empty new project |
| `--reference` | option, repeatable | File(s) passed to the LLM as read-only context | No reference context |

### Examples

```bash
# Explicitly choose a provider
python run.py --provider gemini "add a cat"

# Explicit output path
python run.py --output my_game.sb3 "add a cat"

# Load an existing file and save under a new name (original file untouched)
python run.py --input my_game.sb3 --output my_game_v2.sb3 "make the cat twice as big"

# Multiple reference files (.sb3 is rendered as pseudocode; .txt/.md/.json etc. are passed as-is)
python run.py --input my_game.sb3 \
  --reference style_guide.md \
  --reference sample_project.sb3 \
  "using sample_project.sb3's jump implementation as a reference, add a jump to this project"
```

`--reference` files are never modified. `.sb3` references are converted to pseudocode
(capped at 20,000 characters, with the rest truncated); text-like extensions
(`.txt`, `.md`, `.json`, `.csv`, `.yaml`, `.py`, `.html`, etc.) are passed verbatim.
Any other extension is passed as a filename-only mention. A missing reference file
only produces a warning and does not stop execution.

---

## 5. Overall Architecture

```
run.py (CLI, API key checks, retry logic, --input/--reference loading)
   ↓
sb3gen.main.generate_sb3 (top-level orchestration + clarification loop)
   ↓
sb3gen.patcher.apply_patch
   ├─ plan_instruction … breaks the instruction into ActionSpecs
   │  (add_sprite / modify_sprite / remove_sprite / modify_globals)
   ├─ runs handle_add_sprite / handle_modify_sprite /
   │  handle_remove_sprite / handle_modify_globals per action
   └─ after each successful action, linter.reconcile_globals auto-registers
      any variable/list/broadcast referenced by scripts but not yet declared
   ↓
sb3gen.compiler.compile_project (high-level ProjectSpec → Scratch's project.json)
   ↓
sb3gen.writer.write_sb3 (project.json + asset binaries → .sb3 = ZIP)
```

When continuing an existing project (`--input`), `sb3gen.reader.read_sb3` runs first,
decompiling the existing `.sb3` back into a `ProjectSpec` and re-registering all
embedded asset binaries (costumes/sounds) into the asset registry.

---

## 6. From Instruction to Project (Internal Flow)

1. **Planning (`plan_instruction`)**: the LLM breaks the user's instruction into an
   `ActionPlan` — a list of `add_sprite` / `modify_sprite` / `remove_sprite` /
   `modify_globals` actions. A compound instruction like "add a cat, make it jump, and
   create a score variable" is split into multiple actions executed in order.
2. **Executing each action**:
   - `add_sprite`: the LLM first decides how to obtain each costume (template / generated
     SVG / placeholder) via `AssetDecision`, and the costumes are materialized. Then a
     single call produces a "shell + script plan + procedure plan"; the actual script and
     custom-block bodies are generated **one at a time** in separate LLM calls (see
     section 13).
   - `modify_sprite`: the target sprite's current state is rendered as pseudocode and
     shown to the LLM, then updated using the same "shell → generate scripts one by one"
     approach.
   - `remove_sprite`: simply drops the target from the target list.
   - `modify_globals`: shows the current global variables/lists/broadcasts and has the
     LLM output an add/remove diff (`GlobalsPatch`).
3. **Automatic consistency repair**: after every successful action, `reconcile_globals`
   scans for any variable/list/broadcast referenced by scripts that isn't declared
   globally or locally, and auto-registers it globally.
4. **Validation**: each action's result passes through `validate_project_spec`, which
   checks the schema, the opcode allow-list, and custom-block reference consistency.
5. **Compile & write**: once all actions succeed, the final `ProjectSpec` is compiled
   into Scratch's project.json via `compile_project` and written out as `.sb3` via
   `write_sb3`.

If an action in the middle fails, **changes from prior successful actions are kept**
rather than discarding everything.

---

## 7. Clarification Flow

If an instruction is too ambiguous for `plan_instruction` to act on, the LLM returns
`clarification_needed=true` along with up to 3 questions. When this happens:

1. `generate_sb3` prints the questions to the terminal and reads a reply via `input()`.
2. The reply is appended to a `PendingClarification` history, which is passed back to
   the LLM on the next planning call as "original request + prior Q&A".
3. This can repeat for **up to 3 turns** (`MAX_CLARIFICATION_TURNS`).
4. If it's still unresolved after 3 turns, a fixed fallback message is returned and the
   operation stops.

---

## 8. Data Model (ProjectSpec)

Rather than having the LLM write Scratch's low-level project.json directly, sb3gen has
the LLM produce a **high-level Pydantic model** (defined in `sb3gen/schema.py`), which
`compiler.py` then translates into valid Scratch JSON. The key types:

```
ProjectSpec
├── targets: List[SpriteSpec]        # sprites + the stage (is_stage=True)
├── variables: List[VariableSpec]    # global variables
├── lists: List[ListSpec]            # global lists
└── broadcasts: List[BroadcastSpec]  # global broadcasts

SpriteSpec
├── name, x, y, size, visible
├── costumes: List[CostumeSpec]
├── sounds: List[SoundSpec]
├── variables: List[VariableSpec]    # sprite-local variables
├── scripts: List[ScriptSpec]
└── procedures: List[ProcedureDefinitionSpec]  # this sprite's custom blocks

ScriptSpec
└── blocks: List[BlockSpec]

BlockSpec
├── opcode: str (must be in ALLOWED_OPCODES)
├── fields / inputs: Dict[str, Any]
├── substacks: List[List[BlockSpec]]  # bodies of if/repeat/etc.
└── proc_name: Optional[str]          # only for procedures_call
```

This intermediate representation means the LLM never has to deal with Scratch's
internal block-ID assignment or mutation structures — `compiler.py` handles all of that.

---

## 9. Supported Blocks & Extensions

Only opcodes listed in `ALLOWED_OPCODES` (`schema.py`) may be used. By category:

- Motion (`motion_*`), Looks (`looks_*`), Sound (`sound_*`)
- Events (`event_*`), Control (`control_*`, including clones)
- Sensing (`sensing_*`), Operators (`operator_*`)
- Variables & Lists (`data_*`)
- **Pen extension** (`pen_*`), **Music extension** (`music_*`)
- Custom-block plumbing (`procedures_*`, `argument_reporter_*`)

Whenever a Pen/Music opcode is used, `compile_project` automatically adds the
corresponding extension ID to project.json's `extensions` array. Without this, Scratch
would never load the extension and the blocks wouldn't function — this is an important
automatic step.

Any opcode outside this list (e.g. native shadow opcodes like `math_number`, or
extension blocks this tool doesn't support) is rejected by `validate_project_spec` even
if the LLM outputs it, and the patch is marked FAILED.

---

## 10. Custom Blocks (My Blocks / Procedures)

`ProcedureDefinitionSpec` defines a name, arguments (string/number or boolean), warp
mode, and a body. Callers just set `procedures_call`'s `proc_name` to the block's name
and pass argument values keyed by argument name in `inputs` — `compiler.py` handles
converting this into Scratch's internal `proccode` string and argument IDs.

Generation follows the same split strategy as scripts: first decide the signature
(name, arguments, one-line summary), then generate each body individually via a
separate LLM call.

---

## 11. Asset Handling (Costumes & Sounds)

### Costumes

When adding a new sprite, the LLM picks one of these sourcing strategies
(`AssetSourceType`) per costume:

- `template`: a pre-registered template from `templates/manifest.json` (currently only
  a cat, `cat.svg`).
- `svg_generate`: color/shape keywords detected in the prompt (e.g. "red circle",
  "blue triangle") are rendered as an SVG with a radial gradient, gloss highlight, and
  drop shadow (multiple colors/shapes are composited into one image, up to 4).
- `placeholder`: a gray box with the costume's name, used as a last resort.

### Sounds

`register_wav_asset` / `register_wav_template` can register `.wav` files, but
`templates/manifest.json` currently has no `sounds` section, so no sound effect
templates ship out of the box (you'd need to register your own or extend the manifest).

### Fallback on Missing Assets

If a referenced asset ID isn't found in the registry at write time, `writer.py`
**does not fail the whole project** — it falls back automatically:

- Costume → a gray placeholder SVG labeled with the costume's name
- Sound → a minimal silent WAV

### Stage Backdrop

If no Stage target is present in the instruction's result, `compile_project`
automatically prepends a Stage with a plain white 480×360 backdrop
(properly registered via `register_default_backdrop`, avoiding the old bug where an
unregistered fixed asset ID always triggered the placeholder fallback).

---

## 12. Continuing an Existing Project (--input)

Passing `--input` with a `.sb3` path runs `reader.read_sb3`, which:

1. Decompiles the entire project.json back into a `ProjectSpec` (block trees, custom
   block definitions, variables/lists/broadcasts included).
2. Re-registers **every asset binary** in the ZIP (every file besides project.json)
   into the asset registry.

Step 2 matters a lot: without it, costumes/sounds this instruction never touched would
be misdiagnosed as "missing" and silently replaced by the writer's placeholder/silence
fallback — breaking the whole point of continuing to edit.

**Note**: this reader targets `.sb3` files this tool itself produced. Files saved
directly by the Scratch editor (or other tools) often contain unsupported opcodes and
may fail validation on load — this is intentional, to avoid silently emitting a broken
project.

---

## 13. LLM Output Stabilization (`llm_io.py`)

Having a single LLM call output a huge JSON blob (e.g. an entire sprite's block tree)
risks the output getting **truncated mid-stream** due to token limits. To mitigate this:

- **JSON validation + retry** (`generate_json_with_retry`): on parse/validation failure,
  it distinguishes "output was truncated" from "schema violation" and builds a tailored
  retry prompt for each case (up to 3 attempts).
- **Per-item generation** (`generate_items_individually`): sprite generation first
  decides only a lightweight "list of script summaries" and "custom block signatures"
  in one call, then generates each script/procedure body **individually** in its own
  LLM call. This keeps each call's output size small and consistent, and one failure
  doesn't cascade into others.

Separately, `run.py` implements **exponential-backoff retries** for transient API
errors (rate limits, 503/429, overload, timeouts). Errors that indicate exhausted
quotas (which waiting won't fix) are failed immediately rather than retried.

---

## 14. Known Limitations

- No sound-effect templates ship by default; `manifest.json` has no `sounds` section
  populated yet.
- Multiple backdrops (e.g. for level switching) are technically supported by the data
  model (`SpriteSpec.costumes` allows multiple entries for the Stage), but there's no
  dedicated generation logic or UI flow for it yet.
- Pen/Music opcodes are allow-listed, but there's no `AssetDecision`-style intermediate
  planning step to help the LLM use them well — output quality depends entirely on the
  LLM.
- `--input` is intended for `.sb3` files this tool produced itself. Projects from other
  tools may contain unsupported opcodes and fail to load.

---

## 15. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `SyntaxError: invalid syntax` near `schema.py` | Happens on Python < 3.11 if unpacking syntax like `Literal[*tuple(...)]` is used. The current implementation uses `Literal[tuple(...)]` (no `*`), which works on Python 3.8+. |
| Complains that `OPENAI_API_KEY`/`GEMINI_API_KEY` is missing | Set the environment variable matching the provider you intend to use, or pass `--provider` explicitly. |
| Keeps asking clarifying questions in a loop | The instruction is too vague and the LLM keeps returning `clarification_needed`. Answer with concrete sprite names/numbers (it auto-stops after 3 turns). |
| Generated `.sb3`'s backdrop/image is a gray placeholder | The referenced asset wasn't found in the registry and the automatic fallback kicked in. If this came from `--input`, check that embedded-asset re-registration ran correctly. |
| Loading an existing `.sb3` (not produced by this tool) errors out | `.sb3` files from the Scratch editor or other tools often contain unsupported opcodes — this is expected behavior, not a bug. |
