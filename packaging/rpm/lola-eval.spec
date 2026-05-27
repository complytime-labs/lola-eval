# Suppress brp-mangle-shebangs for the entire bundled tree.
#
# Two things break without this:
#   1. CPython stdlib files (encodings/rot_13.py etc.) ship with bare
#      #!/usr/bin/env python shebangs we do not control; rpmbuild errors
#      "ambiguous python shebang" otherwise.
#   2. Node binaries and npm-installed scripts ship with #!/usr/bin/env
#      node shebangs which brp-mangle rewrites to #!/usr/bin/node — a
#      path that does not exist on most distros — making `lola-eval test`
#      crash with "FileNotFoundError: '/opt/lola-eval/lib/node/bin/npx'"
#      because the kernel can't load the interpreter.
#
# Excluding the whole /opt/lola-eval subtree keeps shebangs untouched.
# The wrapper script (/opt/lola-eval/bin/lola-eval) prepends the bundled
# node to PATH so `#!/usr/bin/env node` resolves to the bundled binary.
%global __brp_mangle_shebangs_exclude_from ^/opt/lola-eval/.*$

# All runtimes are bundled under /opt/lola-eval; disable the automatic
# dependency scanner for that subtree so rpmbuild does not generate
# Requires for GPU libraries, aarch64 loaders, or other incidental sonames
# found inside the bundled Node/Python trees.
%global __requires_exclude_from ^/opt/lola-eval/.*$
# Likewise suppress provides that come from bundled shared libraries so they
# do not pollute the system provides namespace.
%global __provides_exclude_from ^/opt/lola-eval/.*$

# We ship pre-built upstream binaries (CPython from astral-sh, Node from
# nodejs.org, esbuild/codex/ripgrep via npm). Their builders strip the
# .note.gnu.build-id ELF note, so rpmbuild's debuginfo and build-id-link
# phases warn "Missing build-id" for every such file. There is no debug
# info we could produce for binaries we did not compile, so disable both
# the debuginfo subpackage and the build-id link generation.
%global debug_package %{nil}
%global _build_id_links none

Name:           lola-eval
Version:        %{version}
Release:        1%{?dist}
Summary:        Embeddable agent eval runner for lola packs
License:        Apache-2.0 AND MIT AND PSF-2.0 AND BSD-3-Clause
# No public upstream forge yet. Use the same placeholder host the README's
# CI snippet uses so users see the same signal in both places. Update
# both when a real public source location exists.
URL:            https://example.invalid/lola-eval
BuildArch:      x86_64

# Bundled dependencies - exempt from system dependency scanning
Provides:       bundled(python) = 3.12.6
Provides:       bundled(nodejs) = 22.22.2
Provides:       bundled(npm(promptfoo)) = 0.121.11

# Build-time requirements (in Mock chroot, not runtime host)
BuildRequires:  python3
BuildRequires:  python3-pip
BuildRequires:  curl
BuildRequires:  xz
BuildRequires:  tar
BuildRequires:  gzip

%description
A test runner that target projects embed like any other test suite to
verify that lola packs still produce useful results when run through
claude-code or opencode at a particular model version.

This package bundles its own runtimes and dependencies to ensure
consistent behavior across installations:
- Python 3.12.6 (PSF-2.0 license)
- Node.js 22.22.2 (MIT license)
- promptfoo 0.121.11 and dependencies (MIT license)

The bundle is installed under /opt/lola-eval/ to avoid conflicts
with system packages.

%prep
# Download and verify Python 3.12.6 (astral-sh python-build-standalone)
echo "Downloading Python 3.12.6..."
curl -fL https://github.com/astral-sh/python-build-standalone/releases/download/20240909/cpython-3.12.6+20240909-x86_64-unknown-linux-gnu-install_only.tar.gz -o python.tar.gz
echo "68ff386c923c59a33a272bd984b8a33fe8117c56ad7f7552e0c2b21937ee3c0b  python.tar.gz" | sha256sum -c -

# Download and verify Node 22.22.2
echo "Downloading Node 22.22.2..."
curl -fL https://nodejs.org/dist/v22.22.2/node-v22.22.2-linux-x64.tar.xz -o node.tar.xz
echo "88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a  node.tar.xz" | sha256sum -c -

# Extract both tarballs
echo "Extracting Python..."
mkdir -p python-bundle
tar -xzf python.tar.gz -C python-bundle --strip-components=1

echo "Extracting Node..."
mkdir -p node-bundle
tar -xJf node.tar.xz -C node-bundle --strip-components=1

%build
# Copy project source into build directory
# Mock places source at %{_builddir}/%{name}-%{version}/
# We're already in %{_builddir} from %prep
cp -r %{_sourcedir}/src .
cp -r %{_sourcedir}/pyproject.toml .
cp -r %{_sourcedir}/README.md .
cp -r %{_sourcedir}/LICENSE .

# Build wheel using system Python (not bundled Python yet)
echo "Building lola-eval wheel..."
python3 -m pip install --break-system-packages build
python3 -m build --wheel

# Install wheel into bundled Python
echo "Installing lola-eval into bundled Python..."
./python-bundle/bin/pip3 install --no-warn-script-location dist/lola_eval-*.whl

# Install promptfoo via bundled npm
echo "Installing promptfoo via bundled Node..."
PATH="$(pwd)/node-bundle/bin:$PATH" npm install --prefix promptfoo-staging promptfoo@0.121.11

%install
# Stage /opt/lola-eval/ layout
mkdir -p %{buildroot}/opt/lola-eval/{lib/{python,node},share,bin}

# Copy bundled runtimes
cp -a python-bundle/. %{buildroot}/opt/lola-eval/lib/python/
cp -a node-bundle/. %{buildroot}/opt/lola-eval/lib/node/
cp -a promptfoo-staging/. %{buildroot}/opt/lola-eval/share/promptfoo/

# Strip __pycache__ trees that pip left anywhere under lola_eval/_data/.
# Originally scoped to _data/examples/, but the init_template/ tree under
# _data/ also carries starter source that pip byte-compiles into pyc
# bundles. Those pyc files then ride along into every user's scaffolded
# starter when they run `lola-eval init`. Match all _data/** to stop both.
find %{buildroot}/opt/lola-eval/lib/python -path '*/lola_eval/_data/*' -name '__pycache__' \
  -type d -exec rm -rf {} + 2>/dev/null || true

# Copy versions manifest
cat > %{buildroot}/opt/lola-eval/share/versions.txt <<EOF
[x86_64]
python_release = 20240909
python_version = 3.12.6
python_url     = https://github.com/astral-sh/python-build-standalone/releases/download/20240909/cpython-3.12.6+20240909-x86_64-unknown-linux-gnu-install_only.tar.gz
python_sha256  = 68ff386c923c59a33a272bd984b8a33fe8117c56ad7f7552e0c2b21937ee3c0b

node_version = 22.22.2
node_url     = https://nodejs.org/dist/v22.22.2/node-v22.22.2-linux-x64.tar.xz
node_sha256  = 88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a

promptfoo_version = 0.121.11
EOF

# Copy license and documentation
cp %{_sourcedir}/LICENSE %{buildroot}/opt/lola-eval/LICENSE
cp %{_sourcedir}/README.md %{buildroot}/opt/lola-eval/README.md

# Copy additional documentation
mkdir -p %{buildroot}/opt/lola-eval/share/doc
cp %{_sourcedir}/docs/walkthrough.md %{buildroot}/opt/lola-eval/share/doc/walkthrough.md

# Copy examples
cp -r %{_sourcedir}/examples %{buildroot}/opt/lola-eval/share/examples

# Create wrapper script
cat > %{buildroot}/opt/lola-eval/bin/lola-eval <<'EOF'
#!/bin/sh
export PATH="/opt/lola-eval/lib/node/bin:$PATH"
exec /opt/lola-eval/lib/python/bin/python3 -m lola_eval "$@"
EOF
chmod +x %{buildroot}/opt/lola-eval/bin/lola-eval

# Symlink to /usr/bin
# Relative path so the link survives bind-mounts, chroots, and offline
# rootfs inspection (rpmbuild's brp-symlink warns on absolute symlinks
# that cross filesystem trees).
mkdir -p %{buildroot}/usr/bin
ln -s ../../opt/lola-eval/bin/lola-eval %{buildroot}/usr/bin/lola-eval

%files
# List subtrees individually rather than as recursive /opt/lola-eval/ so
# %doc- and %license-tagged paths are not also covered by a broader entry
# (rpmbuild emits "File listed twice" for every file under the overlap).
%dir /opt/lola-eval
%dir /opt/lola-eval/share
%dir /opt/lola-eval/share/doc
/opt/lola-eval/bin
/opt/lola-eval/lib
/opt/lola-eval/share/promptfoo
/opt/lola-eval/share/versions.txt
%license /opt/lola-eval/LICENSE
%doc /opt/lola-eval/README.md
%doc /opt/lola-eval/share/doc/walkthrough.md
%doc /opt/lola-eval/share/examples
/usr/bin/lola-eval

%changelog
* %(date '+%a %b %d %Y') Build %{version}-1
- Initial RPM build of lola-eval via Mock.
