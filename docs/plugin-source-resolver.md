# Plugin Source Resolver

The Source Resolver normalizes plugin package inputs into one verified local
download candidate without modifying the Plugin Store.

Supported sources:

- local filesystem paths;
- `file://` URLs;
- direct HTTP or HTTPS URLs;
- GitHub Release assets.

Every resolved source includes:

- source type;
- local cached path;
- safe filename;
- SHA-256 digest;
- byte size;
- source metadata.

The resolver enforces:

- `.empy-plugin` file suffix;
- safe destination filenames;
- configurable size limits;
- configurable network timeouts;
- HTTP error reporting;
- bounded streaming downloads.

GitHub Release resolution performs an API lookup, selects one exact asset name,
and then downloads its `browser_download_url`.

Installation, artifact inspection, extraction, and Store mutation belong to
later Ticket 4 stages.
