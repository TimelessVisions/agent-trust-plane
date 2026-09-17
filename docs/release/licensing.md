# Licensing record (v0.3.0, checked 2026-09-17)

## This repository

- License: MIT. `LICENSE` contains the MIT License text as published at
  https://opensource.org/license/mit; the body was compared word for word
  (whitespace-normalised) against that page on 2026-09-17 and matches. The
  only project-specific line is the copyright line.
- Copyright holder: `George Gakravyi`, as confirmed by the maintainer on
  2026-09-17. The Git history has a single author ("George",
  `george@agentcommercegateway.com` and `georgegarkavyi@gmail.com`; 28+
  commits, 2026-09-16 onward), no other contributors, no `Co-Authored-By`
  trailers naming another person, no CLA.
- Metadata: root `pyproject.toml` uses the PEP 639 form `license = "MIT"`
  with `license-files = ["LICENSE"]` and an `authors` entry; every
  workspace member `pyproject.toml` declares `license = "MIT"`; the
  dashboard `package.json` declares `"license": "MIT"` (it is `private`,
  not published). The wheel ships `LICENSE` in `dist-info/licenses/`.
- Third-party code in the tree: none identified. All Python, TypeScript,
  YAML, docs and images were written for this project; the two PNG
  screenshots and the SVG transcript are of this project's own output.
  Code fragments derived from third parties: none; the MCP integration
  uses the `mcp` SDK as a dependency, not copied code. No vendored
  libraries, fonts, or datasets. The tool-name grammar and annotation
  field names follow the MCP specification (a specification, not code).

The MIT License is a widely used permissive license whose text is
published by the Open Source Initiative. Nothing here is reviewed,
certified, endorsed or approved by the Massachusetts Institute of
Technology or by OSI; "MIT License" is the name of the license text.

## Runtime dependencies (locked set, `uv export --no-dev`)

Checked with `pip-licenses` in a fresh virtual environment installed from
`uv.lock` (Windows resolution; 42 distributions). All are permissive and
compatible with distributing this project under MIT. Dependencies are
imported, not vendored or redistributed in the wheel.

| License | Packages |
|---|---|
| MIT (incl. "MIT License", MIT-0) | PyJWT, PyYAML, annotated-doc, annotated-types, anyio, attrs, cffi (MIT-0), fastapi, h11, httptools, jsonschema, jsonschema-specifications, mcp, mcp-types, pydantic, pydantic-settings, pydantic_core, referencing, rpds-py, truststore, typing-inspection, watchfiles |
| BSD-3-Clause / BSD | click, httpcore, httpcore2, httpx, httpx2, idna, pycparser, python-dotenv, sse-starlette, starlette, uvicorn, websockets |
| Apache-2.0 | opentelemetry-api, python-multipart; cryptography (Apache-2.0 OR BSD-3-Clause) |
| PSF-2.0 / Python Software Foundation | typing_extensions, pywin32 (Windows only) |
| MPL-2.0 | certifi (file-level copyleft; used unmodified as a dependency, which MPL permits) |

Not installed on the audit machine and therefore **not verified here**:
`uvloop` (Linux/macOS only; its own metadata says MIT/Apache-2.0),
`httpx2-jsfetch` (emscripten only). Dev-only tools (pytest, ruff, mypy,
hypothesis, pip-audit) are not distributed.

## Dashboard (`apps/dashboard`, not packaged, `private: true`)

`license-checker --production`: MIT 11, Apache-2.0 3, ISC 2, BSD-3-Clause
1, 0BSD 1, plus two to note:

- `@img/sharp-win32-x64` (via Next.js image optimisation): "Apache-2.0 AND
  LGPL-3.0-or-later" (the LGPL part is libvips, dynamically linked). It is
  a build/runtime dependency fetched by `npm install` on the user's
  machine; it is not in this repository and not redistributed by it.
- `caniuse-lite`: CC-BY-4.0 data, same situation.

Neither affects the MIT licensing of this repository's own code. If the
dashboard were ever *distributed* as a bundle, sharp/libvips attribution
requirements would need to be revisited.

## What cannot be verified from this machine

- Licenses of platform-specific wheels not resolved on Windows (uvloop,
  httpx2-jsfetch); re-run `pip-licenses` on Linux before a PyPI release.
