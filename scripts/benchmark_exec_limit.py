#!/usr/bin/env python3
"""Enforce a declared process lifetime around an unmodified exec-server.

This benchmark transport forwards JSON-RPC without changing tool arguments or
results. The same adapter can bound native and experimental executors. Process
reads, writes and client reconnects do not renew an admitted process deadline.
"""

import argparse
import asyncio
import json
import sys
import time
import uuid


async def relay(command, seconds, receipt):
    process = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        limit=64 * 1024 * 1024,
    )
    prefix = "benchmark-limit-" + uuid.uuid4().hex + "-"
    pending = {}
    active = {}
    internal = set()
    closed_before_response = set()
    tasks = set()
    write_lock = asyncio.Lock()
    failed = asyncio.get_running_loop().create_future()

    def timer_finished(task):
        tasks.discard(task)
        if not task.cancelled() and task.exception() is not None and not failed.done():
            failed.set_exception(task.exception())

    def record(event, **fields):
        receipt.write(json.dumps(dict(at=time.time(), event=event, **fields)) + "\n")
        receipt.flush()

    async def send(raw):
        async with write_lock:
            process.stdin.write(raw)
            await process.stdin.drain()

    async def expire(pid, admitted):
        await asyncio.sleep(max(0, admitted + seconds - time.monotonic()))
        identity = prefix + uuid.uuid4().hex
        internal.add(identity)
        record("process_limit", process_id=pid, seconds=seconds)
        await send((json.dumps({"id": identity, "method": "process/terminate",
                               "params": {"processId": pid}}) + "\n").encode())

    async def client_input():
        reader = asyncio.StreamReader(limit=64 * 1024 * 1024)
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)
        while raw := await reader.readline():
            message = json.loads(raw)
            identity = message.get("id")
            if isinstance(identity, str) and identity.startswith(prefix):
                raise ValueError("client used transport-reserved request identity")
            if message.get("method") == "process/start":
                pending[identity] = (message["params"]["processId"], time.monotonic())
            await send(raw)
        process.stdin.close()

    async def server_output():
        while raw := await process.stdout.readline():
            message = json.loads(raw)
            identity = message.get("id")
            if identity in internal:
                internal.remove(identity)
                record("termination_result", response=message)
                if "error" in message:
                    raise RuntimeError("executor rejected benchmark termination")
                continue
            if identity in pending and "method" not in message:
                pid, admitted = pending.pop(identity)
                if "error" not in message and pid not in closed_before_response:
                    if pid in active:
                        raise RuntimeError("executor admitted an already active process identity")
                    timer = asyncio.create_task(expire(pid, admitted))
                    active[pid] = timer
                    tasks.add(timer)
                    timer.add_done_callback(timer_finished)
                    record("process_admitted", process_id=pid, seconds=seconds)
                closed_before_response.discard(pid)
            if message.get("method") == "process/closed":
                pid = message["params"]["processId"]
                timer = active.pop(pid, None)
                if timer is not None:
                    timer.cancel()
                elif any(p == pid for p, _ in pending.values()):
                    closed_before_response.add(pid)
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()

    client = asyncio.create_task(client_input())
    server = asyncio.create_task(server_output())
    try:
        done, _ = await asyncio.wait([client, server, failed], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if server not in done:
            await asyncio.wait_for(server, timeout=10)
        return await process.wait()
    finally:
        for task in [client, server, *tasks]:
            task.cancel()
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("seconds must be positive")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("executor command is required")
    with open(args.receipt, "a") as receipt:
        raise SystemExit(asyncio.run(relay(command, args.seconds, receipt)))


if __name__ == "__main__":
    main()
