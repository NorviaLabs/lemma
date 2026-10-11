"""Seeded simulations behind the agent, network and sampling visuals.

Each kernel is a deterministic function of its parameters and a seed. The browser
runs the same algorithms (``static/kernels.js``) to animate them; the server runs
them to check that a model's goals can really be reached. Keep the two in step:
same random draws, in the same order, with the same arithmetic.
"""

from __future__ import annotations

import math

from .expr import _normcdf

__all__ = ["KERNELS", "run", "resolve_params", "Rng"]


class Rng:
    """mulberry32, bit-for-bit identical to the JavaScript version."""

    def __init__(self, seed: int):
        self.a = int(seed) & 0xFFFFFFFF

    def __call__(self) -> float:
        a = (self.a + 0x6D2B79F5) & 0xFFFFFFFF
        self.a = a
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    def int(self, n: int) -> int:
        return math.floor(self() * n)

    def normal(self) -> float:
        u1 = 1 - self()
        u2 = self()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


# name: (default, min, max, is_integer)
KERNELS: dict[str, dict] = {
    "schelling": {
        "visual": "agents",
        "about": "Grid of two groups. Agents move to a random empty cell while fewer than `tolerance` of their neighbours are like them.",
        "params": {
            "size": (20, 8, 40, True),
            "density": (0.9, 0.3, 0.98, False),
            "share_a": (0.5, 0.05, 0.95, False),
            "tolerance": (0.3, 0.0, 1.0, False),
            "steps": (40, 1, 200, True),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "segregation": "average share of an agent's neighbours who are in its own group (0–1)",
            "unhappy": "share of agents still unhappy at the end (0–1)",
            "rounds": "rounds run before everyone was content or the step limit",
        },
    },
    "sir": {
        "visual": "agents",
        "about": "Grid contagion: susceptible, infected, recovered and vaccinated cells. Each infected neighbour passes infection with probability `transmission` per round.",
        "params": {
            "size": (30, 10, 60, True),
            "transmission": (0.3, 0.0, 1.0, False),
            "recovery": (0.2, 0.01, 1.0, False),
            "vaccinated": (0.0, 0.0, 0.95, False),
            "initial": (3, 1, 50, True),
            "steps": (100, 1, 400, True),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "peak_infected": "largest share of the population infected at once (0–1)",
            "final_infected": "share of the population ever infected (0–1)",
            "rounds": "rounds until no one was infected or the step limit",
        },
    },
    "opinion": {
        "visual": "agents",
        "about": "Bounded-confidence opinion dynamics: two random agents compromise only if their opinions (0–1) differ by less than `confidence`.",
        "params": {
            "agents": (100, 10, 300, True),
            "confidence": (0.2, 0.01, 1.0, False),
            "convergence": (0.5, 0.05, 0.5, False),
            "rounds": (40, 1, 200, True),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "clusters": "number of opinion groups at the end (gaps wider than 0.1 separate groups)",
            "spread": "distance between the most extreme opinions (0–1)",
        },
    },
    "network": {
        "visual": "network",
        "about": "Ring network with random rewiring (small world). Adoption spreads from a cluster of seed nodes, either by a `threshold` rule (adopt when that share of neighbours has adopted) or a `probability` rule (each new adopter convinces each neighbour with probability `transmission`). Set rule to 0 for threshold, 1 for probability.",
        "params": {
            "nodes": (60, 10, 200, True),
            "degree": (4, 2, 12, True),
            "rewire": (0.1, 0.0, 1.0, False),
            "rule": (0, 0, 1, True),
            "threshold": (0.3, 0.0, 1.0, False),
            "transmission": (0.3, 0.0, 1.0, False),
            "seeds": (3, 1, 50, True),
            "steps": (30, 1, 200, True),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "adopted": "share of nodes that adopted by the end (0–1)",
            "rounds": "rounds until spreading stopped or the step limit",
        },
    },
    "mean": {
        "visual": "sampling",
        "about": "Repeated samples of size `n` from a normal population; each dot is one sample mean.",
        "params": {
            "mu": (0.0, -1e6, 1e6, False),
            "sd": (1.0, 1e-9, 1e6, False),
            "n": (10, 1, 500, True),
            "samples": (200, 10, 1000, True),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "mean_of_means": "average of the sample means",
            "sd_of_means": "standard deviation of the sample means (the standard error)",
        },
    },
    "two_group": {
        "visual": "sampling",
        "about": "Repeated two-group studies: `n` per group drawn from normals with means `mu1`, `mu2` and common `sd`. Each dot is one study's p-value from a z-test.",
        "params": {
            "mu1": (0.0, -1e6, 1e6, False),
            "mu2": (0.5, -1e6, 1e6, False),
            "sd": (1.0, 1e-9, 1e6, False),
            "n": (20, 2, 500, True),
            "alpha": (0.05, 0.001, 0.5, False),
            "samples": (200, 10, 1000, True),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "share_significant": "share of studies with p below alpha (the power, or the false-positive rate when mu1 = mu2)",
            "mean_diff": "average observed difference mu2 − mu1",
            "mean_sig_diff": "average observed difference among significant studies only (shows exaggeration)",
        },
    },
    "regression": {
        "visual": "sampling",
        "about": "Pairs of measurements (first, second) with correlation `r`. The top `select` share on the first measurement is highlighted; their second measurement is, on average, closer to the mean.",
        "params": {
            "r": (0.5, -0.99, 0.99, False),
            "mean": (0.0, -1e6, 1e6, False),
            "sd": (1.0, 1e-9, 1e6, False),
            "people": (300, 20, 1000, True),
            "select": (0.1, 0.01, 0.5, False),
            "seed": (1, 0, 1e9, True),
        },
        "metrics": {
            "first_selected": "average first measurement of the selected group, in sd units from the mean",
            "second_selected": "average second measurement of the same group, in sd units from the mean",
            "retained": "second_selected / first_selected: the share of the extremeness that survives",
        },
    },
}


def resolve_params(kernel: str, raw: dict) -> dict:
    spec = KERNELS[kernel]["params"]
    out = {}
    for name, (default, lo, hi, is_int) in spec.items():
        v = raw.get(name, default)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = float(default)
        if v != v or v in (math.inf, -math.inf):
            v = float(default)
        v = min(max(v, lo), hi)
        if is_int:
            v = math.floor(v + 0.5)
        out[name] = v
    return out


def _schelling(p):
    rng = Rng(p["seed"])
    n = p["size"]
    cells = n * n
    grid = [0] * cells  # 0 empty, 1 group A, 2 group B
    for i in range(cells):
        if rng() < p["density"]:
            grid[i] = 1 if rng() < p["share_a"] else 2

    def neigh(i):
        r, c = divmod(i, n)
        same = occ = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                g = grid[((r + dr) % n) * n + (c + dc) % n]
                if g:
                    occ += 1
                    if g == grid[i]:
                        same += 1
        return same, occ

    def unhappy(i):
        same, occ = neigh(i)
        return occ > 0 and same / occ < p["tolerance"]

    rounds = 0
    for _ in range(p["steps"]):
        movers = [i for i in range(cells) if grid[i] and unhappy(i)]
        if not movers:
            break
        empty = [i for i in range(cells) if not grid[i]]
        if not empty:
            break
        rounds += 1
        for i in movers:
            k = rng.int(len(empty))
            j = empty[k]
            grid[j], grid[i] = grid[i], 0
            empty[k] = i
    shares, unhappy_count, agents = [], 0, 0
    for i in range(cells):
        if not grid[i]:
            continue
        agents += 1
        same, occ = neigh(i)
        if occ:
            shares.append(same / occ)
            if same / occ < p["tolerance"]:
                unhappy_count += 1
    return {
        "segregation": sum(shares) / len(shares) if shares else 0.0,
        "unhappy": unhappy_count / agents if agents else 0.0,
        "rounds": float(rounds),
    }


def _sir(p):
    rng = Rng(p["seed"])
    n = p["size"]
    cells = n * n
    st = [0] * cells  # 0 S, 1 I, 2 R, 3 V
    for i in range(cells):
        if rng() < p["vaccinated"]:
            st[i] = 3
    placed = tries = 0
    while placed < p["initial"] and tries < cells * 4:
        tries += 1
        i = rng.int(cells)
        if st[i] == 0:
            st[i] = 1
            placed += 1
    infected = placed
    peak = infected / cells
    rounds = 0
    q = 1 - p["transmission"]
    for _ in range(p["steps"]):
        if infected == 0:
            break
        rounds += 1
        nxt = st[:]
        for i in range(cells):
            s = st[i]
            if s == 0:
                r, c = divmod(i, n)
                k = 0
                for j in (((r - 1) % n) * n + c, ((r + 1) % n) * n + c, r * n + (c - 1) % n, r * n + (c + 1) % n):
                    if st[j] == 1:
                        k += 1
                if k:
                    stay = 1.0
                    for _k in range(k):
                        stay *= q
                    if rng() < 1 - stay:
                        nxt[i] = 1
            elif s == 1:
                if rng() < p["recovery"]:
                    nxt[i] = 2
        st = nxt
        infected = st.count(1)
        peak = max(peak, infected / cells)
    ever = sum(1 for s in st if s in (1, 2))
    return {"peak_infected": peak, "final_infected": ever / cells, "rounds": float(rounds)}


def _opinion_clusters(xs):
    s = sorted(xs)
    clusters = 1
    for a, b in zip(s, s[1:]):
        if b - a > 0.1:
            clusters += 1
    return clusters, s[-1] - s[0]


def _opinion(p):
    rng = Rng(p["seed"])
    n = p["agents"]
    x = [rng() for _ in range(n)]
    for _ in range(p["rounds"] * n):
        i = rng.int(n)
        j = rng.int(n)
        if i != j and abs(x[i] - x[j]) < p["confidence"]:
            xi, xj = x[i], x[j]
            x[i] = xi + p["convergence"] * (xj - xi)
            x[j] = xj + p["convergence"] * (xi - xj)
    clusters, spread = _opinion_clusters(x)
    return {"clusters": float(clusters), "spread": spread}


def network_graph(p):
    rng = Rng(p["seed"])
    n = p["nodes"]
    half = max(1, p["degree"] // 2)
    adj = [set() for _ in range(n)]
    for i in range(n):
        for j in range(1, half + 1):
            t = (i + j) % n
            if rng() < p["rewire"]:
                for _ in range(10):
                    t = rng.int(n)
                    if t != i and t not in adj[i]:
                        break
            if t != i:
                adj[i].add(t)
                adj[t].add(i)
    return [sorted(a) for a in adj], rng


def _network(p):
    adj, rng = network_graph(p)
    n = p["nodes"]
    on = [False] * n
    for i in range(min(p["seeds"], n)):
        on[i] = True
    fresh = [i for i in range(n) if on[i]]
    rounds = 0
    for _ in range(p["steps"]):
        new = []
        if p["rule"] == 0:
            for i in range(n):
                if not on[i] and adj[i]:
                    k = sum(1 for j in adj[i] if on[j])
                    if k / len(adj[i]) >= p["threshold"] and k > 0:
                        new.append(i)
        else:
            for i in fresh:
                for j in adj[i]:
                    if not on[j] and j not in new and rng() < p["transmission"]:
                        new.append(j)
        if not new:
            break
        rounds += 1
        for i in new:
            on[i] = True
        fresh = new
    return {"adopted": sum(on) / n, "rounds": float(rounds)}


def _mean(p):
    rng = Rng(p["seed"])
    means = []
    for _ in range(p["samples"]):
        s = 0.0
        for _ in range(p["n"]):
            s += p["mu"] + p["sd"] * rng.normal()
        means.append(s / p["n"])
    m = sum(means) / len(means)
    var = sum((x - m) * (x - m) for x in means) / (len(means) - 1)
    return {"mean_of_means": m, "sd_of_means": math.sqrt(var)}


def _two_group(p):
    rng = Rng(p["seed"])
    n = p["n"]
    se = p["sd"] * math.sqrt(2 / n)
    sig = 0
    diffs, sig_diffs = [], []
    for _ in range(p["samples"]):
        a = b = 0.0
        for _ in range(n):
            a += p["mu1"] + p["sd"] * rng.normal()
        for _ in range(n):
            b += p["mu2"] + p["sd"] * rng.normal()
        diff = b / n - a / n
        z = diff / se
        pval = 2 * (1 - _normcdf(abs(z)))
        diffs.append(diff)
        if pval < p["alpha"]:
            sig += 1
            sig_diffs.append(diff)
    return {
        "share_significant": sig / p["samples"],
        "mean_diff": sum(diffs) / len(diffs),
        "mean_sig_diff": sum(sig_diffs) / len(sig_diffs) if sig_diffs else 0.0,
    }


def _regression(p):
    rng = Rng(p["seed"])
    r = p["r"]
    k = math.sqrt(1 - r * r)
    pairs = []
    for _ in range(p["people"]):
        z1 = rng.normal()
        z2 = rng.normal()
        pairs.append((z1, r * z1 + k * z2))
    order = sorted(range(len(pairs)), key=lambda i: (-pairs[i][0], i))
    m = max(1, math.floor(p["people"] * p["select"] + 0.5))
    chosen = order[:m]
    f = sum(pairs[i][0] for i in chosen) / m
    s = sum(pairs[i][1] for i in chosen) / m
    return {"first_selected": f, "second_selected": s, "retained": s / f if f else 0.0}


_RUN = {
    "schelling": _schelling,
    "sir": _sir,
    "opinion": _opinion,
    "network": _network,
    "mean": _mean,
    "two_group": _two_group,
    "regression": _regression,
}


def run(kernel: str, raw_params: dict) -> dict:
    """Run a kernel to completion and return its final metrics."""
    return _RUN[kernel](resolve_params(kernel, raw_params))
