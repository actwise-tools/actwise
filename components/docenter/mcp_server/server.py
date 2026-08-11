"""
ActWise MCP Server — exposes NICE Actimize documentation as a searchable MCP tool.

Works as both:
  MCP server:  python server.py                          (add to Claude Code / VS Code)
  CLI search:  python server.py search "policy manager" [--version 10.1] [--guide implementer] [--product actone]

Searches the extracted Markdown files in raw_docs/ (all products).
Builds an inverted index on first query for fast ranked BM25 search across the
~60k-file bundle-centric corpus. The index is persisted to raw_docs/.search-index.pkl
and reused while the corpus is unchanged (keyed on file count + newest mtime); the
cold build parallelizes the I/O-bound file reads across a thread pool.

The `--product` filter is index-driven: each page's bundle is resolved against
raw_docs/index/bundles.json so a SHARED platform bundle matches every product that
references it (not just the one that first downloaded it). When the index is absent
it falls back to the per-page front-matter `product:`.

MCP config for Claude Code (~/.claude/settings.json):
  {
    "mcpServers": {
      "actimize-docs": {
        "command": "actimize-docs-mcp"
      }
    }
  }

VS Code Copilot config (.vscode/mcp.json):
  {
    "servers": {
      "actimize-docs": {
        "type": "stdio",
        "command": "actimize-docs-mcp"
      }
    }
  }
"""

import argparse
import json
import math
import os
import pickle
import re
import sys
import io
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from actwise.paths import repo_root

# Index build read-concurrency. Building the corpus index is I/O-bound (tens of
# thousands of small file reads); reads release the GIL so threads parallelize well.
_INDEX_WORKERS = int(os.environ.get("DOCENTER_INDEX_WORKERS", "32"))

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# raw_docs location: honor DOCENTER_RAW_DOCS_DIR (set by the CLI / .env) so the
# installed package finds the corpus regardless of where it lives; fall back to the
# source-checkout layout, then ./raw_docs in the current working directory.
for _k, _v in list(os.environ.items()):  # back-compat: DOCCENTER_* -> DOCENTER_*
    if _k.startswith("DOCCENTER_"):
        os.environ.setdefault("DOCENTER_" + _k[len("DOCCENTER_"):], _v)
_raw_env = os.environ.get("DOCENTER_RAW_DOCS_DIR")
if _raw_env:
    RAW_DOCS = Path(_raw_env).expanduser()
else:
    _repo_raw = (repo_root() or Path(__file__).resolve().parent.parent) / "raw_docs"
    RAW_DOCS = _repo_raw if _repo_raw.exists() else (Path.cwd() / "raw_docs")
MAX_RESULTS = 10
CONTEXT_BEFORE = 300   # chars before match
CONTEXT_AFTER = 600    # chars after match

_WORD_RE = re.compile(r"[a-z0-9]+")
_FM_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


# ---------------------------------------------------------------------------
# YAML front matter parsing
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    parts = content.split("\n")
    if parts[0].strip() != "---":
        return {}
    block = []
    for line in parts[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    try:
        data = yaml.safe_load("\n".join(block))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    parts = content.split("\n")
    if parts[0].strip() != "---":
        return content
    for i, line in enumerate(parts[1:], start=1):
        if line.strip() == "---":
            return "\n".join(parts[i + 1:]).lstrip("\n")
    return content


# ---------------------------------------------------------------------------
# Inverted index for fast ranked search
# ---------------------------------------------------------------------------

class SearchIndex:
    """In-memory inverted index built from the raw_docs corpus.

    Built lazily on first query. Stores per-document metadata and term
    frequencies for BM25-style scoring.
    """

    _CACHE_NAME = ".search-index.pkl"
    _CACHE_VERSION = 2

    def __init__(self, raw_docs: Path):
        self._raw_docs = raw_docs
        self._cache_path = raw_docs / self._CACHE_NAME
        self._built = False
        self._signature: tuple[int, int] = (0, 0)
        # doc_id (int) -> (path, product_dir)
        self.docs: list[tuple[Path, str]] = []
        # term -> {doc_id: term_count}
        self.postings: dict[str, dict[int, int]] = defaultdict(dict)
        # term -> document frequency (number of docs containing term)
        self.df: dict[str, int] = defaultdict(int)
        self.total_docs = 0
        self._avg_dl = 0.0
        self._doc_lens: list[int] = []
        # Lazy reverse index: bundle_name -> set(product_slug). Loaded from
        # raw_docs/index/bundles.json so a shared platform bundle resolves to
        # EVERY product that references it (not just the one that downloaded it).
        self._bundle_products: dict[str, set[str]] | None = None

    def _bundle_product_map(self) -> dict[str, set[str]]:
        """bundle_name -> set of referencing product slugs (from index/bundles.json).

        Returns an empty map if the index is absent, so callers fall back to the
        per-page front-matter `product:` filter (graceful degradation).
        """
        if self._bundle_products is not None:
            return self._bundle_products
        mapping: dict[str, set[str]] = {}
        index_path = self._raw_docs / "index" / "bundles.json"
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            for name, rec in (data.get("bundles") or {}).items():
                prods = rec.get("products") or []
                mapping[name] = {str(p).lower() for p in prods}
        except Exception:
            mapping = {}
        self._bundle_products = mapping
        return mapping

    def ensure_built(self) -> None:
        if self._built:
            return
        t0 = time.time()
        self._signature = self._corpus_signature()
        if self._load_cache():
            elapsed = time.time() - t0
            print(f"[index] {self.total_docs} docs loaded from cache in {elapsed:.1f}s", file=sys.stderr)
        else:
            self._build()
            self._save_cache()
            elapsed = time.time() - t0
            print(f"[index] {self.total_docs} docs indexed in {elapsed:.1f}s", file=sys.stderr)
        self._built = True

    def _scan_files(self) -> list[Path]:
        """Deterministic, sorted list of corpus pages (skips _* nav/index files)."""
        return sorted(
            (f for f in self._raw_docs.rglob("*.md") if not f.name.startswith("_")),
            key=str,
        )

    def _corpus_signature(self) -> tuple[int, int]:
        """Cheap fingerprint of the corpus: (file count, newest mtime in ns).

        Invalidates the cache when files are added/removed (count) or any page is
        re-downloaded/edited in place (mtime) — a count-only key would miss the
        latter (e.g. `docenter sync` refreshing an existing bundle).
        """
        count = 0
        max_mtime = 0
        for f in self._raw_docs.rglob("*.md"):
            if f.name.startswith("_"):
                continue
            count += 1
            try:
                mt = f.stat().st_mtime_ns
            except OSError:
                continue
            if mt > max_mtime:
                max_mtime = mt
        return count, max_mtime

    def _load_cache(self) -> bool:
        # Safety: pickle is used here for a self-generated local cache file only.
        # The cache lives inside gitignored raw_docs/ and is never loaded from
        # external/untrusted sources. JSON is too slow for 96k-term posting dicts.
        if not self._cache_path.exists():
            return False
        try:
            with open(self._cache_path, "rb") as f:
                data = pickle.load(f)
            if data.get("version") != self._CACHE_VERSION:
                return False
            if data["raw_docs"] != str(self._raw_docs):
                return False
            if tuple(data.get("signature", ())) != self._signature:
                return False
            # Restore index state — paths stored as relative strings
            self.docs = [
                (self._raw_docs / rel, pdir)
                for rel, pdir in data["docs"]
            ]
            self.postings = defaultdict(dict, data["postings"])
            self.df = defaultdict(int, data["df"])
            self.total_docs = data["total_docs"]
            self._avg_dl = data["avg_dl"]
            self._doc_lens = data["doc_lens"]
            return True
        except Exception:
            return False

    def _save_cache(self) -> None:
        data = {
            "version": self._CACHE_VERSION,
            "raw_docs": str(self._raw_docs),
            "signature": self._signature,
            "total_docs": self.total_docs,
            "avg_dl": self._avg_dl,
            "doc_lens": self._doc_lens,
            "docs": [
                (str(p.relative_to(self._raw_docs)), pdir)
                for p, pdir in self.docs
            ],
            "postings": dict(self.postings),
            "df": dict(self.df),
        }
        try:
            with open(self._cache_path, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            print(f"[index] cache write failed: {exc}", file=sys.stderr)

    def _build(self) -> None:
        """Scan all .md files, skip _* files, build inverted index.

        Frontmatter is NOT parsed here (saves ~300s on 100k+ files).
        It's parsed lazily at search time for the top-N candidates only.

        File reads (the dominant cost — corpus build is I/O-bound) run on a thread
        pool; tokenizing and posting-list assembly stay serial so doc_ids follow the
        deterministic sorted file order (keeping the cache reproducible).
        """
        def _read(p: Path) -> tuple[Path, str | None]:
            try:
                return p, p.read_text(encoding="utf-8")
            except Exception:
                return p, None

        total_terms = 0
        paths = self._scan_files()
        with ThreadPoolExecutor(max_workers=_INDEX_WORKERS) as pool:
            for md_path, content in pool.map(_read, paths):
                if content is None:
                    continue

                # Fast regex strip instead of YAML parse
                m = _FM_RE.match(content)
                body = content[m.end():] if m else content

                try:
                    rel = md_path.relative_to(self._raw_docs)
                    product_dir = rel.parts[0] if rel.parts else ""
                except Exception:
                    product_dir = ""

                doc_id = len(self.docs)
                self.docs.append((md_path, product_dir))

                terms = _WORD_RE.findall(body.lower())
                term_counts: dict[str, int] = defaultdict(int)
                for t in terms:
                    term_counts[t] += 1
                for t, c in term_counts.items():
                    self.postings[t][doc_id] = c
                    self.df[t] += 1

                self._doc_lens.append(len(terms))
                total_terms += len(terms)

        self.total_docs = len(self.docs)
        self._avg_dl = total_terms / max(self.total_docs, 1)

    def search(
        self,
        query: str,
        version: str | None = None,
        guide_type: str | None = None,
        product: str | None = None,
        max_results: int = MAX_RESULTS,
    ) -> list[dict]:
        self.ensure_built()
        query_terms = _WORD_RE.findall(query.lower())
        if not query_terms:
            return []

        # Ranked-OR candidate selection (union of posting lists). A document need
        # NOT contain every query token: BM25 below rewards documents that match
        # more — and rarer — terms, so full matches still rank highest, while
        # partial matches remain discoverable lower down. Tokens absent from the
        # index are ignored rather than zeroing out the entire result set. This
        # makes search robust to abbreviations / extra words — e.g. adding "GBI"
        # to "Generic Batch Interface" no longer drops the many pages that spell
        # the phrase out without the standalone "gbi" token.
        present_terms = [t for t in query_terms if t in self.postings]
        if not present_terms:
            return []
        candidates: set[int] = set()
        for t in present_terms:
            candidates |= set(self.postings[t].keys())
        if not candidates:
            return []

        # BM25 scoring (k1=1.5, b=0.75)
        k1 = 1.5
        b = 0.75
        N = self.total_docs
        scores: dict[int, float] = {}
        for doc_id in candidates:
            score = 0.0
            dl = self._doc_lens[doc_id]
            for t in present_terms:
                tf = self.postings[t].get(doc_id, 0)
                df = self.df[t]
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self._avg_dl))
                score += idf * tf_norm
            scores[doc_id] = score

        # Product filtering is index-driven. Under the bundle-centric layout every
        # file lives under raw_docs/bundles/, so the old product_dir pre-filter no
        # longer carries the product. Each page also has only ONE front-matter
        # `product:` (whichever product first downloaded it under the global guard),
        # so a SHARED platform bundle stamped product=cdd would otherwise miss
        # `--product sam` even though SAM references it. We instead resolve the
        # bundle of each page and keep it if `--product` is in that bundle's set of
        # referencing products (index/bundles.json). Front-matter `product:` is the
        # fallback when the index is absent.
        product_lower = product.lower() if product else None
        bundle_products = self._bundle_product_map() if product_lower else {}
        if not candidates:
            return []

        # Filter and rank — parse frontmatter lazily for top candidates only
        version_lower = version.lower() if version else None
        guide_lower = guide_type.lower() if guide_type else None

        ranked = sorted(candidates, key=lambda d: scores[d], reverse=True)
        results = []
        for doc_id in ranked:
            md_path, product_dir = self.docs[doc_id]

            try:
                content = md_path.read_text(encoding="utf-8")
            except Exception:
                continue

            fm = parse_frontmatter(content)
            body = strip_frontmatter(content)

            fm_version = str(fm.get("version", "") or "")
            fm_product = str(fm.get("product", "") or "")
            fm_guide = str(fm.get("guide_type", "") or "")

            if version_lower and fm_version.lower() != version_lower:
                continue
            if product_lower:
                # Resolve the page's bundle, then keep it if `--product` references
                # that bundle per the index. Bundle name comes from front-matter
                # `bundle:` or, failing that, the parent dir under bundles/.
                fm_bundle = str(fm.get("bundle", "") or "") or md_path.parent.name
                ref_products = bundle_products.get(fm_bundle)
                if ref_products is not None:
                    if product_lower not in ref_products:
                        continue
                elif product_lower not in (fm_product.lower(), product_dir.lower()):
                    # Index absent or bundle unknown -> front-matter fallback.
                    continue
            if guide_lower and guide_lower not in fm_guide.lower() and \
                    guide_lower not in str(md_path).lower():
                continue

            # Build excerpt around the first query term occurrence
            query_lower = query.lower()
            body_lower = body.lower()
            idx = body_lower.find(query_lower)
            if idx == -1:
                for t in query_terms:
                    idx = body_lower.find(t)
                    if idx != -1:
                        break
            if idx == -1:
                idx = 0
            start = max(0, idx - CONTEXT_BEFORE)
            end = min(len(body), idx + CONTEXT_AFTER)
            excerpt = body[start:end].strip()

            title = str(fm.get("title", "") or fm.get("page_title", "") or "")
            resource = str(fm.get("resource", "") or fm.get("source_url", "") or "")

            results.append({
                "product": fm_product or product_dir,
                "version": fm_version,
                "bundle": str(fm.get("bundle", "") or ""),
                "guide_type": fm_guide,
                "title": title,
                "resource": resource,
                "timestamp": str(fm.get("timestamp", "") or ""),
                "file": str(md_path.relative_to(self._raw_docs.parent)),
                "excerpt": excerpt,
                "score": round(scores[doc_id], 3),
                "page_title": title,
                "source_url": resource,
            })
            if len(results) >= max_results:
                break

        return results


# Module-level singleton — built lazily on first query
_index: SearchIndex | None = None


def _get_index() -> SearchIndex:
    global _index
    if _index is None:
        _index = SearchIndex(RAW_DOCS)
    return _index


# ---------------------------------------------------------------------------
# Public search API (used by docenter CLI's search --local)
# ---------------------------------------------------------------------------

def search_docs(
    query: str,
    version: str | None = None,
    guide_type: str | None = None,
    product: str | None = None,
    max_results: int = MAX_RESULTS,
) -> list[dict]:
    """Keyword search over extracted MD files across the whole corpus.

    Uses a BM25-scored inverted index for fast ranked search across 100k+ files.
    The index is built lazily on first call (~10-15s) and reused for subsequent queries.
    """
    return _get_index().search(
        query, version=version, guide_type=guide_type,
        product=product, max_results=max_results,
    )


def format_results_text(results: list[dict], query: str) -> str:
    if not results:
        return f"No results found for '{query}' in the local Actimize documentation corpus."

    lines = [f"Found {len(results)} result(s) for '{query}':\n"]
    for i, r in enumerate(results, 1):
        product = r.get("product") or "Unknown"
        version = r.get("version") or ""
        lines.append(f"{'─'*60}")
        lines.append(f"[{i}] {r['title']}  ({product} {version})".rstrip())
        url = (r.get("resource") or "").replace(
            "docs-be.niceactimize.com", "docs.niceactimize.com"
        )
        if url:
            lines.append(f"    {url}")
        lines.append("")
        lines.append(r["excerpt"])
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP server mode
# ---------------------------------------------------------------------------

def run_mcp_server():
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types
    import asyncio

    server = Server("actimize-docs")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="search_actimize_docs",
                description=(
                    "Search NICE Actimize product documentation (all products). "
                    "Returns relevant excerpts ranked by BM25 relevance with source URLs. "
                    "Optionally filter by product, version, and guide type."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for, e.g. 'configure policy manager' or 'installation prerequisites'",
                        },
                        "product": {
                            "type": "string",
                            "description": "Product key/name to filter, e.g. actone, xse-sam, sam, cdd, ifm. Omit to search all products.",
                        },
                        "version": {
                            "type": "string",
                            "description": "Version to search, e.g. 10.0, 10.1, 10.2, 11.2. Omit to search all.",
                        },
                        "guide_type": {
                            "type": "string",
                            "description": "Filter by guide: 'implementer', 'reference', 'installation', 'release_notes', 'extend'",
                        },
                    },
                    "required": ["query"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name != "search_actimize_docs":
            raise ValueError(f"Unknown tool: {name}")

        query = arguments.get("query", "")
        version = arguments.get("version")
        guide_type = arguments.get("guide_type")
        product = arguments.get("product")

        if not query.strip():
            return [types.TextContent(type="text", text="Please provide a search query.")]

        if not RAW_DOCS.exists():
            return [types.TextContent(
                type="text",
                text="Documentation not yet extracted. Run: python extractor/extractor.py"
            )]

        results = search_docs(query, version=version, guide_type=guide_type, product=product)
        text = format_results_text(results, query)
        return [types.TextContent(type="text", text=text)]

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(_serve())


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

def run_cli():
    parser = argparse.ArgumentParser(
        description="Search NICE Actimize documentation (all products)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python server.py search "configure policy manager"
  python server.py search "installation prerequisites" --version 10.1
  python server.py search "policy types" --guide implementer --version 10.0
  python server.py search "data explorer" --product xse-sam
  python server.py search "API endpoints" --product actone --guide extend
        """,
    )
    parser.add_argument("search", help="Subcommand (always 'search')")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--product", dest="product", help="Filter by product, e.g. actone, xse-sam")
    parser.add_argument("--version", help="Filter by version, e.g. 10.0, 10.1")
    parser.add_argument("--guide", dest="guide_type", help="Filter by guide type")
    parser.add_argument("--max", type=int, default=MAX_RESULTS, help="Max results (default 10)")
    args = parser.parse_args()

    if not RAW_DOCS.exists():
        print("Documentation not yet extracted.")
        print("Run: python extractor/extractor.py")
        sys.exit(1)

    results = search_docs(
        args.query,
        version=args.version,
        guide_type=args.guide_type,
        product=args.product,
        max_results=args.max,
    )
    print(format_results_text(results, args.query))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        run_cli()
    else:
        run_mcp_server()


if __name__ == "__main__":
    main()
