# packs/ — pack lock manifests

Each `*.lock.yaml` in this directory pins one lola pack to a specific
git SHA. The fingerprint of every drift row that uses the pack
incorporates the SHA (see spec Section 4), so a republished version
tag cannot silently corrupt drift history.

## Schema

```yaml
pack:
  name: <pack name as listed by `lola market ls`>
  source: <git URL or marketplace URL>
  resolved_sha: <40-char git commit SHA>
  installed_via: lola
notes: |
  Free-form rationale for why this pack was selected.
```

All four fields under `pack:` are required. `notes:` is optional.

## Adding a pack

```sh
# 1. Add the marketplace if not already present
lola market add general https://raw.githubusercontent.com/RedHatProductSecurity/lola-market/main/general-market.yml

# 2. Inspect available packs
lola market ls

# 3. Resolve the SHA of the pack at HEAD of its branch
git ls-remote <pack source URL> HEAD | awk '{print $1}'

# 4. Author packs/<name>.lock.yaml from the schema above

# 5. Reference the pack in matrix.yaml
#    packs:
#      - <name>@<resolved_sha>
```

Users opting into real-pack drift testing run the above. The harness
itself ships zero pre-pinned packs in Phase 1 — see plan Task 25 for
rationale.
