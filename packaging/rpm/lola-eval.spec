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

Name:           lola-eval
Version:        %{version}
Release:        1%{?dist}
Summary:        Embeddable agent eval runner for lola packs
License:        Apache-2.0
# Project URL: replace at release time with the real upstream URL.
URL:            https://github.com/anthropics/lola-eval
BuildArch:      x86_64

# `lola` is a runtime requirement (the orchestrator scripts shell out
# to `lola install` when a pack is configured), but it is not yet
# packaged in any RPM repo. Hard `Requires: lola` therefore makes
# `dnf install lola-eval-*.rpm` fail on every clean target. We instead
# check for it at runtime via `lola-eval doctor`, which exits non-zero
# with an actionable message. Reinstate `Requires: lola` once an `lola`
# RPM is published.
# Requires:       lola

%description
A test runner that target projects embed like any other test suite to
verify that lola packs still produce useful results when run through
claude-code or opencode at a particular model
version. Bundles its own Python interpreter, Node interpreter, and
promptfoo install — distro provides only libc.

%install
# stagingdir is $build/staging/opt/lola-eval — copy its contents into place.
mkdir -p %{buildroot}/opt/lola-eval
cp -a %{stagingdir}/. %{buildroot}/opt/lola-eval/
mkdir -p %{buildroot}/usr/bin
ln -s /opt/lola-eval/bin/lola-eval %{buildroot}/usr/bin/lola-eval
mkdir -p %{buildroot}/etc/lola-eval

%files
/opt/lola-eval/
/usr/bin/lola-eval
%dir /etc/lola-eval

%changelog
* %(date '+%a %b %d %Y') Build %{version}-1
- Initial RPM build of lola-eval.
