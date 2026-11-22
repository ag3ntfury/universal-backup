## Summary

## Testing
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python -m compileall -q universal_backup tests`

## Safety review
- [ ] No existing backup format compatibility was broken.
- [ ] No destructive behaviour was introduced without safeguards and tests.
- [ ] Documentation and changelog were updated.
