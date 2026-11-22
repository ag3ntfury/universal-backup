# Contributing

Thanks for helping improve Universal Backup. The project is in alpha; correctness and data safety take priority over feature count.

## Before opening a pull request

1. Open an issue for substantial changes so the design can be discussed.
2. Keep the backup engine independent from the desktop UI.
3. Never change backup format or restore semantics without migration tests.
4. Do not add destructive operations (pruning, overwrite, format, delete) without explicit safeguards and tests.
5. Add tests for new behaviour and failure paths.
6. Run `python -m unittest discover -s tests -v` and `python -m compileall -q universal_backup`.
7. Update documentation and release notes.

## Development setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

## Reporting bugs

Include the Universal Backup version, Linux distribution, Python version, relevant command, redacted logs, and whether the issue can be reproduced with a disposable test directory. Never attach private documents, backup archives, access tokens, or unredacted device identifiers.
