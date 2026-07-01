<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

# 13 — Release asset retention

> **Status:** Spec only. Implementation is a follow-up; it is
> **eligible to be implemented by a separate subagent** running in
> parallel with other v1 work. The spec below is a complete
> contract for that subagent.

## Dependencies

- **Reads:** `11-ci-release.md` (the release workflow that produces
  the assets this spec retains).

## Goal

Cap the disk and bandwidth cost of GitHub Releases by automatically
pruning old release assets after a configurable number of releases
is retained. Without this, every release adds ~370 MB to the
project's release storage, and `dist/stenographer/` source builds
accumulate on CI runners and locally.

## Trigger

A separate GitHub Actions workflow file at
`.github/workflows/release-retention.yml`. It runs on:

- `schedule:` — daily at a fixed UTC time.
- `workflow_dispatch:` — manual run for ad-hoc cleanup.

It does **not** run on `push` or `pull_request`. The workflow is
read-only with respect to the release pipeline; it only deletes
release assets, never releases themselves.

## Retention policy

Default policy: keep the **most recent N = 5** release assets (the
tarball + the SHA-256). For everything older:

1. Iterate over releases, sorted by `published_at` descending.
2. Skip the first N; for the rest, delete the assets
   `stenographer-*-linux-x86_64.tar.gz` and
   `stenographer-*-linux-x86_64.sha256`.
3. Leave the release itself intact (do not delete the tag, the
   release page, or any non-matching assets).

`N` is configurable via a `workflow_dispatch` input
(`--retained-releases`) and a repo variable
(`STENOGRAPHER_RETENTION_COUNT`) for the scheduled run. Default
`N = 5`.

## Pre-release safety

Pre-release releases are never pruned, regardless of recency. This
prevents the workflow from removing `v0.7.0-rc.1` assets when
`v0.7.0` ships, even if both fall below the retention count.

The flag for "is a pre-release" is the GitHub release's
`prerelease` boolean (set by GitHub for tags matching the
pre-release pattern documented in `spec/11-ci-release.md`).

## Implementation outline

The workflow is a single job with these steps:

1. `actions/checkout@v4` (shallow, no fetch-depth needed).
2. Use `gh release list --repo OWNER/REPO --json tagName,isPrerelease,publishedAt`
   to enumerate releases.
3. Filter out pre-releases.
4. Sort by `publishedAt` descending.
5. Skip the first N entries.
6. For each remaining release, run
   `gh release delete-asset <tag> <asset-name> --repo OWNER/REPO --yes`.

The `gh` CLI is preinstalled on `ubuntu-latest` and authenticated
via the workflow's `GITHUB_TOKEN` (no extra secrets needed).
Required permissions in the workflow file:

```yaml
permissions:
  contents: write
```

## Out of scope (v1)

- Deleting the release itself (not just the assets). This would
  break any external link pointing at the release page.
- Compressing old assets into a single archive. The retention
  policy is the only mechanism; storage reclamation is left to
  GitHub's regular garbage collection.
- A user-facing `stenographer cleanup` subcommand. The retention
  policy is operator-side; it never runs from a user install.

## Open questions

- **N = 5 — is that the right default?** It trades off "users
  can roll back to one of the last five releases" against
  "5 × 370 MB = 1.85 GB of release storage". A larger N costs
  storage; a smaller N breaks older self-update paths. v1 ships
  with 5; can be tuned via the repo variable.
- **Should the workflow also prune the build artifacts produced
  by the release workflow itself (i.e. the `dist/stenographer/`
  directory on the runner)?** No — GitHub Actions already garbage
  collects runner storage between jobs. Out of scope.
