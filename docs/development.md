# Development

## Repository layout

| Path | What it is |
| --- | --- |
| `custom_components/supla_local/` | The Home Assistant integration |
| `custom_components/supla_local/server/` | Vendored copy of the server package |
| `supla_server/` | The standalone server, with a REST API and a test web panel |
| `tools/supla_proxy.py` | TCP port forwarder for testing against another host |
| `tests/` | Server tests, plus Home Assistant integration tests |

`custom_components/supla_local/server/` is a byte-identical copy of
`supla_server/` minus `http_api.py`, `app.py`, `__main__.py` and `web/`, so the
two stay in sync. Nothing outside the Python standard library and `cryptography`
is needed, and both ship with Home Assistant.

## Running the tests

```sh
uv venv --python 3.13 .venv
uv pip install -r requirements_test.txt
.venv/bin/python -m pytest tests
```

## Cutting a release

Home Assistant reads the version from `manifest.json`, but the version people
choose is the release tag, so the two have to agree. Rather than keep them in
step by hand, `.github/workflows/release.yml` stamps the tag into the manifest
when a release is published, zips the integration and attaches it. `hacs.json`
sets `zip_release`, so HACS installs that archive rather than the repository
contents.

```sh
git tag v0.2.0 && git push origin master --tags
gh release create v0.2.0 --title v0.2.0 --generate-notes
```

The tag may start with `v`; the manifest gets the bare version. Anything that
is not `MAJOR.MINOR.PATCH` fails the workflow rather than shipping a version
Home Assistant would reject.

The `version` committed in `manifest.json` is only what someone copying the
directory by hand would see — every release overwrites it.

Because `zip_release` is on, a release with no attached zip cannot be
installed. If the workflow fails, fix it and re-run the job rather than
leaving the release published.

## Nightly builds

`.github/workflows/nightly.yml` rebuilds the zip on every push to `master` and
replaces the asset on a single rolling `nightly` pre-release, so the newest
code is always installable without cutting a release for it.

To use it, turn on pre-release versions for this repository in HACS, then
**Redownload** and pick `nightly`.

The build is versioned as the next patch plus a timestamp — `0.1.0` released
becomes `0.1.1.dev202608162029` — which sorts after the release it follows and
before the real `0.1.1`. Appending `.dev` to the released version itself would
sort *older* than it, which is how PEP 440 pre-releases work.

Because the tag name never changes, HACS will not show an update badge for a
new nightly; redownload it when you want the latest. If you would rather have
update notifications, the workflow can create a uniquely tagged pre-release per
push instead, at the cost of a tag per commit.
