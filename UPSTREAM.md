# Upstream source

This repository is derived from [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).

- Upstream remote: `https://github.com/TauricResearch/TradingAgents.git`
- Imported release: `v0.4.0`
- Annotated tag object: `c5e62b8bb88bc308e84ea351044356f99da1213e`
- Peeled commit: `2448d0a12576f9b2ddcd5980a0630833423d1e1b`
- License: Apache License 2.0 in `LICENSE`

The import preserves upstream history and attribution. Future upstream changes are never merged automatically. A maintainer must fetch the upstream repository, verify the selected tag or commit, inspect the complete diff, and submit the result through the GitHub pull-request process for manual review.

Recreate the local upstream relationship with:

```bash
git remote add upstream https://github.com/TauricResearch/TradingAgents.git
git fetch upstream --tags
git log --oneline --decorate --graph main upstream/main
```

Before proposing an update, record the selected upstream ref and full commit SHA in the pull request and run the repository's complete CI and local-release qualification suite.
