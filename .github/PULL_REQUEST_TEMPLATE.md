## Summary

<!-- Brief description of what this PR does -->

## Checklist

- [ ] If this PR adds code to `runtime/` or `servers/<name>/tools/`, did you confirm it doesn't belong in dev-nexus (analysis) or openclaw-gateway (orchestration) per [architectural boundaries](https://github.com/DarojaAI/dev-nexus/blob/main/docs/architecture/architectural-boundaries.md)?
- [ ] If this PR changes `config/dat-contract.yaml`, did you regenerate `docs/github-actions-secrets.md` with `python3 scripts/ci/generate-secrets-doc.py`?
- [ ] Tests pass locally: `pytest tests/`
- [ ] Linting passes: `ruff check .`
- [ ] Updated relevant docs in `docs/` (if applicable)

## Testing

<!-- How did you test this? Manual steps, automated tests, etc. -->

## Related Issues

<!-- Link to any related issues/PRs -->
