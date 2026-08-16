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

`.github/workflows/nightly.yml` publishes a pre-release build of the latest
code on every push to `master`, and on every published release.

To use them, turn on pre-release versions for this repository in HACS. Updates
then show up the same way real releases do.

Each build gets **its own tag**, `v1.0.1.dev202608162041`. A single rolling
`nightly` tag does not work: HACS decides what is newest by comparing tag
names, and `nightly` is not a version, so it can never win against the last
real release. The workflow keeps the newest five dev builds and deletes the
rest, tags included, so the releases page stays short. Only pre-releases whose
tag has the `X.Y.Z.devNNN` shape are ever pruned — a real release cannot match
that pattern.

The version is the next patch after the newest release, plus a timestamp:
`v1.0.0` released gives `1.0.1.dev202608162041`, which sorts after the release
it follows and before the eventual real `1.0.1`. Appending `.dev` to the
released version itself would sort *older* than it, which is how PEP 440
pre-releases work.

The base is the higher of the newest real release tag and the committed
manifest version. Previous dev tags are excluded from that calculation, or each
build would ratchet the version up by one. The release workflow stamps the
version into the published zip only — the manifest committed in the repository
deliberately stays where it is, which is why the tag has to be consulted.
