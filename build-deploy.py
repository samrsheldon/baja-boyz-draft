#!/usr/bin/env python3
"""
Build the deployable index.html from the editable JSX source.

- Source of truth (edit this): /Users/samsheldon/Claude/wc2026-draft.html
  (still uses <script type="text/babel"> so it stays easy to author)
- Output (deploy this):        /tmp/baja-draft-deploy/index.html
  (JSX pre-compiled to plain JS, no in-browser Babel, pinned production React)

Requires the esbuild binary at /tmp/package/bin/esbuild. If missing, fetch:
  ARCH=$(uname -m); PKG=darwin-arm64; [ "$ARCH" = x86_64 ] && PKG=darwin-x64
  curl -sL "https://registry.npmjs.org/@esbuild/$PKG/-/$PKG-0.21.5.tgz" -o /tmp/esb.tgz
  tar xzf /tmp/esb.tgz -C /tmp
"""
import re, subprocess, sys, os

SRC = '/Users/samsheldon/Claude/wc2026-draft.html'
OUT = '/tmp/baja-draft-deploy/index.html'
ESBUILD = '/tmp/package/bin/esbuild'

src = open(SRC, encoding='utf-8').read()

# 1. Extract the JSX block
m = re.search(r'<script type="text/babel">(.*?)</script>', src, re.S)
if not m:
    sys.exit('ERROR: could not find <script type="text/babel"> block in source')
jsx = m.group(1)
open('/tmp/_jsx_src.jsx', 'w', encoding='utf-8').write(jsx)

# 2. Compile JSX -> plain JS (downlevel modern syntax for broad mobile support)
r = subprocess.run([ESBUILD, '/tmp/_jsx_src.jsx', '--target=es2017',
                    '--outfile=/tmp/_compiled.js'], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit('ESBUILD FAILED:\n' + r.stderr)
compiled = open('/tmp/_compiled.js', encoding='utf-8').read()
assert '</script>' not in compiled, 'compiled JS unexpectedly contains </script>'

# 3. Pin React to production builds
src = src.replace(
    '<script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>',
    '<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js" crossorigin></script>')
src = src.replace(
    '<script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>',
    '<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js" crossorigin></script>')

# 4. Drop the in-browser Babel standalone script (no longer needed)
src = src.replace('  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>\n', '')

# 5. Swap the JSX block for the compiled plain-JS <script> (string splice, no regex escaping)
start = src.index('<script type="text/babel">')
end = src.index('</script>', start) + len('</script>')
src = src[:start] + '<script>\n' + compiled + '\n</script>' + src[end:]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, 'w', encoding='utf-8').write(src)
print(f'Built {OUT}  ({len(src)} bytes)  — Babel removed, React pinned 18.3.1 prod')
