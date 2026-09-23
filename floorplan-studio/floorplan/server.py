"""A dependency-free web UI: ``python -m floorplan.server``.

Built on :mod:`http.server`, which is enough for a design tool you run on your
own machine. It binds to localhost by default; there is no authentication, so
only expose it further if you understand what that means.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import json
import mimetypes
import secrets
import tempfile
import traceback
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .api import RequestError, catalog, generate_from, replay, scene_for
from .levels import CLIENT, LEVELS
from .dxf import DXF_ENCODING, render_dxf
from .pdf import render_pdf
from .raster import render_png
from .render import build_scene
from .svg import render_svg

STATIC = Path(__file__).parent / "static"
MAX_BODY = 256 * 1024
MAX_UPLOAD = 25 * 1024 * 1024
UPLOAD_TYPES = {"dxf", "svg", "pdf"}
KEEP_CONVERSIONS = 50

EXPORTERS = {
    "svg": ("image/svg+xml", lambda scene: render_svg(scene).encode("utf-8")),
    "pdf": ("application/pdf", render_pdf),
    "png": ("image/png", render_png),
    "dxf": ("image/vnd.dxf",
            lambda scene: render_dxf(scene).encode(DXF_ENCODING, "replace")),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "floorplan-studio"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        if not self.server.quiet:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    # -- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, value) -> None:
        self._send(code, json.dumps(value).encode("utf-8"), "application/json")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise RequestError("empty request body")
        if length > MAX_BODY:
            raise RequestError("request body too large")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError(f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RequestError("request body must be a JSON object")
        return payload

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        try:
            if route in ("/", "/index.html"):
                self._static("index.html")
            elif route == "/api/catalog":
                self._json(200, {"rooms": catalog()})
            elif route.startswith("/api/converted/"):
                self._download(route[len("/api/converted/"):])
            elif route.startswith("/static/"):
                self._static(route[len("/static/"):])
            else:
                self._json(404, {"error": "not found"})
        except BrokenPipeError:
            pass

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        try:
            if route == "/api/generate":
                self._generate()
            elif route == "/api/export":
                self._export()
            elif route == "/api/convert":
                self._convert()
            else:
                self._json(404, {"error": "not found"})
        except RequestError as exc:
            self._json(400, {"error": str(exc)})
        except BrokenPipeError:
            pass
        except Exception:  # keep the server alive; report without leaking a stack
            traceback.print_exc()
            self._json(500, {"error": "internal error generating the plan"})

    def _static(self, name: str) -> None:
        target = (STATIC / name).resolve()
        if not target.is_file() or STATIC.resolve() not in target.parents:
            self._json(404, {"error": "not found"})
            return
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), kind)

    def _generate(self) -> None:
        payload = self._read_json()
        plans = generate_from(payload)
        variants = []
        for plan in plans:
            scene = scene_for(plan, dict(payload, level=CLIENT))  # the preview is the client plan
            variants.append({
                "seed": plan.seed,
                "summary": plan.summary(),
                "svg": render_svg(scene),
                "sheet": scene.sheet.name,
                "scale": scene.scale.label,
                "rooms": [room.to_dict() for room in plan.rooms],
            })
        self._json(200, {"variants": variants})

    def _export(self) -> None:
        payload = self._read_json()
        fmt = str(payload.get("format", "pdf")).lower()
        if fmt not in EXPORTERS:
            raise RequestError(f"unknown format {fmt!r}; use one of {sorted(EXPORTERS)}")
        if payload.get("seed") is None:
            raise RequestError("export needs the seed of the variant to rebuild")
        plan = replay(payload, int(payload["seed"]))
        level = str(payload.get("level") or CLIENT).lower()
        if level not in LEVELS:
            raise RequestError(f"unknown level {level!r}; use one of {', '.join(LEVELS)}")
        content_type, exporter = EXPORTERS[fmt]
        body = exporter(scene_for(plan, dict(payload, level=level)))
        stem = "".join(
            c if c.isalnum() or c in "-_" else "-" for c in plan.spec.title.lower()
        ).strip("-") or "floor-plan"
        self._send(200, body, content_type, {
            "Content-Disposition": f'attachment; filename="{stem}-seed{plan.seed}-{level}.{fmt}"'
        })


    # -- conversion --------------------------------------------------------

    def _store(self) -> dict:
        store = getattr(self.server, "converted", None)
        if store is None:
            store = {}
            self.server.converted = store  # type: ignore[attr-defined]
        return store

    def _read_multipart(self) -> tuple[str, bytes, dict[str, str]]:
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            raise RequestError("upload must be multipart/form-data")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise RequestError("empty upload")
        if length > MAX_UPLOAD:
            raise RequestError(f"upload too large (limit {MAX_UPLOAD // (1024 * 1024)} MB)")
        body = self.rfile.read(length)
        message = email.message_from_bytes(
            b"Content-Type: " + ctype.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
            policy=email.policy.HTTP,
        )
        if not message.is_multipart():
            raise RequestError("malformed multipart body")
        filename, payload, fields = "", b"", {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition") or ""
            data = part.get_payload(decode=True) or b""
            if part.get_filename():
                filename, payload = Path(part.get_filename()).name, data
            else:
                fields[str(name)] = data.decode("utf-8", "replace")
        if not filename:
            raise RequestError("no file in upload")
        return filename, payload, fields

    def _convert(self) -> None:
        from .convert.pipeline import UnsupportedSource, convert_file

        filename, payload, fields = self._read_multipart()
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix not in UPLOAD_TYPES:
            raise RequestError(f"only {', '.join(sorted(UPLOAD_TYPES))} files can be converted")
        formats = [f for f in (fields.get("formats") or "pdf,dxf,svg,png").split(",") if f]
        token = secrets.token_urlsafe(16)
        workdir = Path(tempfile.mkdtemp(prefix="floorplan-"))
        source = workdir / ("".join(c if c.isalnum() or c in "-_." else "-" for c in filename) or f"plan.{suffix}")
        source.write_bytes(payload)
        try:
            report = convert_file(source, formats=formats, out_dir=workdir / "out",
                                  page=int(fields.get("page") or 1),
                                  units=fields.get("units") or "metric",
                                  sheet=fields.get("sheet") or None, scale=fields.get("scale") or None)
        except (UnsupportedSource, ValueError, ImportError) as exc:
            raise RequestError(str(exc)) from exc
        store = self._store()
        store[token] = workdir / "out"
        while len(store) > KEEP_CONVERSIONS:
            store.pop(next(iter(store)))
        svg = ""
        preview = report["outputs"].get("client_svg") or next(
            (p for k, p in report["outputs"].items() if k.endswith("_svg")), None)
        if preview:
            svg = Path(preview).read_text(encoding="utf-8")
        downloads = {fmt: f"/api/converted/{token}/{Path(p).name}" for fmt, p in report["outputs"].items()}
        self._json(200, {"report": report, "svg": svg, "downloads": downloads})

    def _download(self, rest: str) -> None:
        token, _, name = rest.partition("/")
        folder = self._store().get(token)
        if folder is None or not name or "/" in name or "\\" in name:
            self._json(404, {"error": "not found"})
            return
        target = (folder / name).resolve()
        if folder.resolve() not in target.parents or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        kind = {"pdf": "application/pdf", "dxf": "image/vnd.dxf", "svg": "image/svg+xml",
                "png": "image/png", "md": "text/markdown; charset=utf-8",
                "json": "application/json"}.get(target.suffix.lstrip("."), "application/octet-stream")
        self._send(200, target.read_bytes(), kind,
                   {"Content-Disposition": f'attachment; filename="{target.name}"'})


def serve(host: str = "127.0.0.1", port: int = 8000, quiet: bool = False) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.quiet = quiet  # type: ignore[attr-defined]
    print(f"floorplan-studio running at http://{host}:{port}  (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="floorplan.server", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    serve(args.host, args.port, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
