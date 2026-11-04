# Documentation claim auditor

Offline, deterministic checking of documentation promises against Python call
patterns. Uses only the standard library, executes no scanned code, makes no
network requests, collects no telemetry and writes no files.

## Usage

```sh
python3 -m pip install .
beat-tracking-claim-audit audit . --json
python3 -m beat_tracking_claim_audit audit . --verbose
beat-tracking-claim-audit audit . --ignore build --ignore dist --fail-on medium
beat-tracking-claim-audit --version
```

The repository defaults to the current directory. Scope is root README.md and
Markdown recursively below root docs, plus Python sources throughout the tree.
Virtual environments and cache directories are skipped. Prefix exclusions are
repeatable. Fenced blocks are excluded; inline code counts as prose. Negative
spans are removed before positive matching, longest first, case insensitively.
A complete evidence route must occur in one module, with imported aliases
resolved and local function or class definitions respected.

Exit codes: 0 for results below the threshold, 2 for findings meeting it,
and 1 for usage or input errors. The default threshold is high. Claims found
only beneath a tests directory have medium severity. JSON findings include
verdict and message fields; verbose output describes scope and file decisions.

```text
documented-beat-tracking-claim-false
documented-no-beat-tracking-claim-false
```

## Differentiation

The neighboring tools cover different outputs:

```text
tempo-detection-claim-audit: BPM scalar versus beat times here.
onset-detection-claim-audit: note onsets versus the metrical grid here.
sound-event-detection-claim-audit: event labels versus beat times here.
```

## Limitations

Static pattern matching is not semantic judgement or proof of runtime behavior.
Only exact phrases are recognized, not paraphrases. Dynamic imports and calls
may be missed. Calls in dead code may qualify. Syntax errors do not supply
evidence. Pair routes cannot be assembled across modules.

## Development

```sh
python3 -m unittest discover
python3 -m build
```

Version 0.1.0. MIT licensed.
