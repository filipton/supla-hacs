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
