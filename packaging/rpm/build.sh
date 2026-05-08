#!/usr/bin/env bash
# Build the lola-eval RPM. Reads packaging/versions.txt, downloads tarballs,
# verifies SHA256, stages /opt/lola-eval/, then invokes rpmbuild.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
build="$repo_root/build"
staging="$build/staging/opt/lola-eval"
arch="${ARCH:-x86_64}"

# Parse versions.txt (tiny INI parser — no deps, no bashisms beyond declare -A)
declare -A V
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  k="${line%%=*}"; v="${line#*=}"
  V[$k]="$v"
done < <(awk -v sec="[$arch]" '
  /^\[/{cur=$0; next}
  cur==sec && /=/ {gsub(/[ \t]/, "", $0); print $0}
' "$repo_root/packaging/versions.txt")

# Validate that required keys are present and not placeholders
for key in python_url python_sha256 node_url node_sha256 promptfoo_version; do
  val="${V[$key]:-}"
  if [[ -z "$val" ]]; then
    echo "ERROR: versions.txt missing key '$key' under [$arch]" >&2
    exit 1
  fi
  if [[ "$val" == *"<fill-in"* ]]; then
    echo "ERROR: versions.txt key '$key' is still a placeholder — fill in the real SHA256 first" >&2
    exit 1
  fi
done

# Download + verify tarballs
mkdir -p "$build"

python_tarball="$build/python.tar.gz"
[[ -f "$python_tarball" ]] || curl -fL "${V[python_url]}" -o "$python_tarball"
echo "${V[python_sha256]}  $python_tarball" | sha256sum -c -

node_tarball="$build/node.tar.xz"
[[ -f "$node_tarball" ]] || curl -fL "${V[node_url]}" -o "$node_tarball"
echo "${V[node_sha256]}  $node_tarball" | sha256sum -c -

# Extract into staging
rm -rf "$staging"
mkdir -p "$staging/lib/python" "$staging/lib/node" "$staging/share" "$staging/bin"
tar -xzf "$python_tarball" -C "$staging/lib/python" --strip-components=1
tar -xJf "$node_tarball"   -C "$staging/lib/node"   --strip-components=1

# Build wheel + install lola_eval and all of its runtime dependencies into the
# bundled Python. We use the bundled pip directly (no --target, no --no-deps)
# so dependency resolution runs normally and packages land in the right
# site-packages for that interpreter.
cd "$repo_root"
python3 -m build --wheel --outdir "$build/dist"
"$staging/lib/python/bin/pip" install \
  "$build"/dist/lola_eval-*.whl

# Install promptfoo via bundled npm.
# npm requires node on PATH; point PATH at the bundled node first.
PATH="$staging/lib/node/bin:$PATH" \
  "$staging/lib/node/bin/npm" install --prefix "$staging/share/promptfoo" \
  "promptfoo@${V[promptfoo_version]}"

mkdir -p "$staging/share"
cp "$repo_root/packaging/versions.txt" "$staging/share/versions.txt"

# Strip __pycache__ trees that the wheel install left behind in the bundled
# example fixtures. They get regenerated on first import anyway, but if
# committed into the RPM users see them in their target's tests/ dir after
# `lola-eval init` — confusing and easy to commit by accident.
find "$staging/lib/python" -path '*/lola_eval/_data/examples/*' -name '__pycache__' \
  -type d -exec rm -rf {} +

# Wrapper script placed at the well-known path the .spec file symlinks to
cat >"$staging/bin/lola-eval" <<'WRAP'
#!/bin/sh
export PATH="/opt/lola-eval/lib/node/bin:$PATH"
exec /opt/lola-eval/lib/python/bin/python3 -m lola_eval "$@"
WRAP
chmod +x "$staging/bin/lola-eval"

# rpmbuild — _topdir isolates the build completely from ~/.rpmbuild.
# stagingdir points at the opt/lola-eval subtree so the spec's cp -a lands
# the content at %{buildroot}/opt/lola-eval without an extra nesting level.
rpmbuild -bb \
  --define "_topdir $build/rpm" \
  --define "_sourcedir $build" \
  --define "stagingdir $staging" \
  --define "version 0.2.0" \
  "$repo_root/packaging/rpm/lola-eval.spec"

mkdir -p "$repo_root/dist"
cp "$build/rpm/RPMS"/*/*.rpm "$repo_root/dist/"
echo "Built: $(ls "$repo_root/dist"/*.rpm)"
