## Summary

One or two sentences. What does this PR change and why?

## Motivation

Link the issue this closes (e.g. `Closes #123`), or describe the problem.

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Refactor (no behavior change)
- [ ] Documentation
- [ ] Breaking change

## Checklist

- [ ] I have read [CONTRIBUTING.md](../blob/master/CONTRIBUTING.md)
- [ ] `pytest` green
- [ ] `black --check .` clean
- [ ] `mypy` clean (or pyright, per CONTRIBUTING)
- [ ] Tests added/updated where applicable
- [ ] README updated if user-facing behavior changed
- [ ] Commits signed
- [ ] **No AI-attribution trailers** (`Co-Authored-By: Claude`, `Generated-by`, etc.)

## Test plan

How did you verify this works? Paste the test invocations and observed output.

```sh
$ pytest
$ black --check .
$ mypy
```

## Security considerations

If this touches TLS handling, certificate generation, file I/O, or the daemon's network surface, note any new attack surface and how it was verified safe.