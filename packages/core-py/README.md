## swto-core

Shared optimization and domain package for all SWTO clients.

Current state:
- Provides compatibility adapters to existing root `app.*` modules.
- Enables incremental migration without breaking desktop runtime.

Migration direction:
1. Move pure domain files from `app/domain` into this package.
2. Move optimizer engines from `app/engine` into this package.
3. Keep UI and platform-specific code out of core.
