"""CLI: run the server for the extension with `vfc serve`. Check a single video with `vfc check <url>`."""
import argparse
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="vfc", description="видео-фактчек: пайплайн и сервер")
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="HTTP-сервер для расширения")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    chk = sub.add_parser("check", help="прогон по одному видео в консоль")
    chk.add_argument("url")

    args = p.parse_args()
    if args.cmd == "serve":
        import uvicorn
        from . import server
        uvicorn.run(server.app, host=args.host, port=args.port, log_level="warning")
    elif args.cmd == "check":
        from . import pipeline, store
        started = pipeline.start_run(args.url)
        import time
        run_id = started["run_id"]
        while True:
            st = pipeline.get_status(run_id)
            print(f"\r{st['phase']:<30}", end="", flush=True)
            if st["status"] in ("done", "error"):
                break
            time.sleep(2)
        print()
        if st["status"] == "error":
            print("ERROR:", st["error"])
            sys.exit(1)
        s = st.get("summary", {})
        print(f"\n{s.get('title')} - {s.get('claims_total')} claims, "
              f"checked {s.get('checked')}, opinions outside checking {s.get('skipped_opinions')}")
        print("Counts:", s.get("counts"))
        for c in st.get("claims", []):
            mark = c.get("verdict") or "—"
            print(f"  [{mark}] {c['claim'][:90]}")
            if c.get("why"):
                print(f"        {c['why'][:120]}")


if __name__ == "__main__":
    main()
