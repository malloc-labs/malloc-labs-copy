# Pull Request

## Summary

-

## Validation

-

## Release Intent

Choose exactly one label before merge:

- `release:none` — no version bump or release expected
- `release:patch` — patch release; PR title must start with `fix:` or `perf:`
- `release:minor` — minor release; PR title must start with `feat:`
- `release:major` — breaking release; PR title must use `!:` or document `BREAKING CHANGE`

Release Please reads the squash-merge commit on `main`, so release-bearing PR
titles must be valid Conventional Commit titles.
