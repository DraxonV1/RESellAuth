"""
Altcha & SellAuth 503 Anti-Bot Proof-of-Work Solvers.
Fully async-friendly pure Python implementations.
"""

import time
import json
import base64
import hashlib
import asyncio
import re
from typing import Dict, Any, Tuple, Optional


def solve_altcha_sync(challenge_data: Dict[str, Any]) -> str:
    """Synchronous CPU-bound Altcha SHA-256 challenge solver."""
    algorithm = challenge_data["algorithm"]
    challenge = challenge_data["challenge"]
    salt = challenge_data["salt"]
    signature = challenge_data["signature"]
    maxnumber = challenge_data.get("maxnumber", 1000000)

    start_time = time.time()
    for num in range(maxnumber + 1):
        test_str = salt + str(num)
        h = hashlib.sha256(test_str.encode("utf-8")).hexdigest()
        if h == challenge:
            took = int((time.time() - start_time) * 1000)
            payload = {
                "algorithm": algorithm,
                "challenge": challenge,
                "number": num,
                "salt": salt,
                "signature": signature,
                "took": took,
            }
            raw_json = json.dumps(payload, separators=(",", ":"))
            return base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")
    raise RuntimeError(f"Altcha PoW solution not found within limit {maxnumber}")


async def solve_altcha(challenge_data: Dict[str, Any]) -> str:
    """Async wrapper that offloads CPU hashing to executor without blocking event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, solve_altcha_sync, challenge_data)


def solve_sellauth_503_sync(html: str) -> Optional[Tuple[str, str]]:
    """Synchronous SellAuth 503 JavaScript Proof-of-Work challenge solver."""
    arr_match = re.search(r"const a0_0x2a54=\[([^\]]+)\];", html)
    if not arr_match:
        return None
    raw_items = [x.strip().strip("'\"") for x in arr_match.group(1).split(",")]

    shift_match = re.search(r"\(a0_0x2a54,\s*(0x[0-9a-fA-F]+|\d+)\)", html)
    if not shift_match:
        return None
    shift_val = int(shift_match.group(1), 16 if "0x" in shift_match.group(1) else 10)

    arr = list(raw_items)
    for _ in range(shift_val):
        arr.append(arr.pop(0))

    def get_str(idx_hex):
        idx = int(idx_hex, 16) if isinstance(idx_hex, str) and idx_hex.startswith("0x") else int(idx_hex)
        return arr[idx]

    c = get_str("0x2")
    cookie_name_prefix = get_str("0x0")
    n1 = int(c[0], 16)

    for i in range(10000000):
        digest = hashlib.sha1((c + str(i)).encode("utf-8")).digest()
        if n1 + 1 < len(digest):
            if digest[n1] == 0xb0 and digest[n1 + 1] == 0x0b:
                cookie_str = cookie_name_prefix + c + str(i)
                parts = cookie_str.split("=")
                return parts[0], parts[1]
    return None


async def solve_sellauth_503(html: str) -> Optional[Tuple[str, str]]:
    """Async wrapper offloading 503 SHA-1 loop to thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, solve_sellauth_503_sync, html)


if __name__ == "__main__":
    async def _test():
        print("[altcha.py] Testing solver...")
        sample_challenge = {
            "algorithm": "SHA-256",
            "challenge": "fb75b9ec7cd43c7a55b7e897da19abcc9678ed7ed633879ef6a2ed67a68acd4b",
            "maxnumber": 10000,
            "salt": "5b7c2d4d4bada12d874638de?expires=1789644549",
            "signature": "a13ca9b92b0b22bdb0042e89ea3ad4afd8313d49a6af7905036b6ab1f08b5125",
        }
        res = await solve_altcha(sample_challenge)
        print("Altcha solved async:", res[:50] + "...")

    asyncio.run(_test())
