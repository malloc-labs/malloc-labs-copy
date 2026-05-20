# Branch Protection Notes

`main` should require these status checks before merge:

- `3.11`
- `3.12`
- `3.13`
- `scan`
- `release-intent`

`release-intent` is the guard that prevents a PR from merging without an
explicit release decision. It requires exactly one release label:

- `release:none`
- `release:patch`
- `release:minor`
- `release:major`

For release-bearing PRs, it also requires a Conventional Commit PR title so
Release Please can create the correct release PR/tag from the squash commit on
`main`.
