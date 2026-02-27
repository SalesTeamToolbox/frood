"""
Knowledge base tool — document import and RAG-powered retrieval.

Enables agents to import documents (PDF, CSV, HTML, Markdown, text, JSON)
into a vector store and query them via semantic search. Builds on the
existing EmbeddingStore and Qdrant infrastructure.

Usage flow:
1. import_file / import_dir — ingest documents into the knowledge base
2. query — retrieve relevant chunks for a question
3. list — see what's been imported
4. delete — remove a document from the knowledge base
"""

import csv
import hashlib
import io
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import aiofiles

from core.config import settings
from core.sandbox import WorkspaceSandbox
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.knowledge")

# Supported file extensions
SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".html", ".htm", ".pdf"}


@dataclass
class DocumentMeta:
    """Metadata for an imported document."""

    file_path: str
    file_name: str
    file_type: str
    checksum: str
    chunk_count: int
    imported_at: float = field(default_factory=time.time)


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML-to-text extractor."""

    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []
        self._skip_tags = {"script", "style", "head"}
        self._in_skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._skip_tags:
            self._in_skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags:
            self._in_skip = max(0, self._in_skip - 1)

    def handle_data(self, data):
        if self._in_skip == 0:
            self._text_parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._text_parts)


def _extract_html_text(html: str) -> str:
    """Extract plain text from HTML."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks by approximate token count.

    Uses a simple word-based approximation: ~0.75 tokens per word.
    """
    words = text.split()
    if not words:
        return []

    # Approximate words per chunk (tokens / 0.75)
    words_per_chunk = max(1, int(chunk_size / 0.75))
    overlap_words = max(0, int(overlap / 0.75))

    chunks = []
    start = 0
    while start < len(words):
        end = start + words_per_chunk
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        start += words_per_chunk - overlap_words

    return chunks


def _checksum(content: str) -> str:
    """Compute SHA-256 checksum of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class KnowledgeTool(Tool):
    """Import documents and query a knowledge base via semantic search.

    Actions:
    - import_file: Import a single document
    - import_dir: Import all supported files in a directory
    - query: Search the knowledge base
    - list: Show imported documents
    - delete: Remove a document from the knowledge base
    """

    def __init__(self, sandbox: WorkspaceSandbox, embedding_store=None):
        self._sandbox = sandbox
        self._embedding_store = embedding_store
        self._knowledge_dir = Path(settings.knowledge_dir)
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._knowledge_dir / "index.json"
        self._documents: dict[str, DocumentMeta] = {}
        self._load_index()

    @property
    def name(self) -> str:
        return "knowledge"

    @property
    def description(self) -> str:
        return (
            "Import documents (PDF, CSV, HTML, Markdown, text, JSON) into a knowledge base "
            "and query them via semantic search. "
            "Actions: import_file, import_dir, query, list, delete."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["import_file", "import_dir", "query", "list", "delete"],
                    "description": "Action to perform",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path (for import_file/import_dir/delete)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for query action)",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (for query, default: 5)",
                    "default": 5,
                },
            },
            "required": ["action"],
        }

    def _load_index(self):
        """Load document index from disk."""
        if not self._index_path.exists():
            return
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            for item in data:
                doc = DocumentMeta(**item)
                self._documents[doc.file_path] = doc
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"Failed to load knowledge index: {e}")

    def _save_index(self):
        """Persist document index to disk."""
        try:
            data = [asdict(doc) for doc in self._documents.values()]
            self._index_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save knowledge index: {e}")

    async def _read_file(self, path: Path) -> str:
        """Read and extract text from a supported file."""
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return await self._read_pdf(path)
        elif suffix == ".csv":
            return await self._read_csv(path)
        elif suffix in (".html", ".htm"):
            async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
                html = await f.read()
            return _extract_html_text(html)
        else:
            # .txt, .md, .json — read as plain text
            async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
                return await f.read()

    async def _read_pdf(self, path: Path) -> str:
        """Extract text from a PDF file."""
        try:
            import pypdf
        except ImportError:
            return f"[PDF import requires pypdf: pip install pypdf] ({path.name})"

        reader = pypdf.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)

    async def _read_csv(self, path: Path) -> str:
        """Read CSV and format as text with headers."""
        async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
            content = await f.read()

        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return ""

        headers = rows[0]
        text_parts = []
        for row in rows[1:]:
            parts = [f"{h}: {v}" for h, v in zip(headers, row) if v.strip()]
            text_parts.append("; ".join(parts))

        return "\n".join(text_parts)

    async def _import_single_file(self, file_path: str) -> tuple[str, int]:
        """Import a single file. Returns (status_message, chunk_count)."""
        try:
            resolved = self._sandbox.resolve_path(file_path)
        except Exception as e:
            return f"Path blocked by sandbox: {e}", 0

        path = Path(resolved)
        if not path.exists():
            return f"File not found: {file_path}", 0
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return f"Unsupported file type: {path.suffix}", 0

        # Read and extract text
        content = await self._read_file(path)
        if not content.strip():
            return f"Empty content in {path.name}", 0

        # Check if already imported with same content
        checksum = _checksum(content)
        existing = self._documents.get(file_path)
        if existing and existing.checksum == checksum:
            return f"Already imported (unchanged): {path.name}", existing.chunk_count

        # Chunk the text
        chunks = _chunk_text(
            content,
            chunk_size=settings.knowledge_chunk_size,
            overlap=settings.knowledge_chunk_overlap,
        )

        if not chunks:
            return f"No content to index in {path.name}", 0

        # Store embeddings
        if self._embedding_store and self._embedding_store.is_available:
            items = [
                {
                    "text": chunk,
                    "source": "knowledge",
                    "section": path.name,
                    "metadata": {
                        "file_path": file_path,
                        "file_name": path.name,
                        "file_type": path.suffix.lower(),
                        "chunk_index": i,
                    },
                }
                for i, chunk in enumerate(chunks)
            ]
            await self._embedding_store.add_entries(items)
        else:
            # Fallback: store chunks as text files in knowledge dir
            chunk_dir = self._knowledge_dir / path.stem
            chunk_dir.mkdir(parents=True, exist_ok=True)
            for i, chunk in enumerate(chunks):
                chunk_path = chunk_dir / f"chunk_{i:04d}.txt"
                async with aiofiles.open(chunk_path, "w", encoding="utf-8") as f:
                    await f.write(chunk)

        # Update index
        self._documents[file_path] = DocumentMeta(
            file_path=file_path,
            file_name=path.name,
            file_type=path.suffix.lower(),
            checksum=checksum,
            chunk_count=len(chunks),
        )
        self._save_index()

        return f"Imported {path.name}: {len(chunks)} chunks", len(chunks)

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "import_file":
            return await self._action_import_file(**kwargs)
        elif action == "import_dir":
            return await self._action_import_dir(**kwargs)
        elif action == "query":
            return await self._action_query(**kwargs)
        elif action == "list":
            return self._action_list()
        elif action == "delete":
            return await self._action_delete(**kwargs)
        return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _action_import_file(self, path: str = "", **kwargs) -> ToolResult:
        if not path:
            return ToolResult(error="Path is required for import_file", success=False)

        msg, count = await self._import_single_file(path)
        return ToolResult(output=msg, success=count > 0 or "unchanged" in msg.lower())

    async def _action_import_dir(self, path: str = "", **kwargs) -> ToolResult:
        if not path:
            return ToolResult(error="Path is required for import_dir", success=False)

        try:
            resolved = self._sandbox.resolve_path(path)
        except Exception as e:
            return ToolResult(error=f"Path blocked by sandbox: {e}", success=False)

        dir_path = Path(resolved)
        if not dir_path.is_dir():
            return ToolResult(error=f"Not a directory: {path}", success=False)

        results = []
        total_chunks = 0
        for file_path in sorted(dir_path.rglob("*")):
            if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                msg, count = await self._import_single_file(str(file_path))
                results.append(msg)
                total_chunks += count

        if not results:
            return ToolResult(
                output=f"No supported files found in {path}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        summary = f"Imported {len(results)} files ({total_chunks} total chunks):\n"
        summary += "\n".join(f"  - {r}" for r in results)
        return ToolResult(output=summary)

    async def _action_query(self, query: str = "", top_k: int = 5, **kwargs) -> ToolResult:
        if not query:
            return ToolResult(error="Query is required for search", success=False)

        top_k = min(top_k, settings.knowledge_max_results)

        # Use embedding store if available
        if self._embedding_store and self._embedding_store.is_available:
            results = await self._embedding_store.search(
                query,
                top_k=top_k,
                source_filter="knowledge",
            )

            if not results:
                return ToolResult(output="No results found in knowledge base.")

            lines = [f"Found {len(results)} results:\n"]
            full_texts = []
            for i, r in enumerate(results, 1):
                source = r.get("metadata", {}).get("file_name", r.get("section", "unknown"))
                score = r.get("score", 0)
                text = r.get("text", "")
                lines.append(f"[{i}] ({score:.3f}) {source}\n    {text[:300]}\n")
                full_texts.append(text)

            # RLM enhancement: if combined results are large, process through
            # RLM for intelligent synthesis instead of raw chunk delivery
            combined = "\n\n".join(full_texts)
            rlm_output = await self._try_rlm_synthesis(query, combined)
            if rlm_output:
                return ToolResult(
                    output=(f"Found {len(results)} results (RLM-synthesized):\n\n{rlm_output}")
                )

            return ToolResult(output="\n".join(lines))

        # Fallback: simple text search across stored chunks
        return await self._fallback_search(query, top_k)

    async def _try_rlm_synthesis(self, query: str, combined_text: str) -> str | None:
        """Attempt RLM synthesis of large knowledge results.

        Returns synthesized text, or None if RLM is unavailable or context
        is below threshold.
        """
        try:
            from providers.rlm_provider import RLMProvider

            provider = RLMProvider()
            if not provider.should_use_rlm(combined_text):
                return None

            result = await provider.complete(
                query=f"Answer this question using the provided knowledge base results: {query}",
                context=combined_text,
                task_type="research",
            )
            if result and result.get("response"):
                return result["response"]
        except Exception as e:
            logger.debug("RLM synthesis unavailable: %s", e)
        return None

    async def _fallback_search(self, query: str, top_k: int) -> ToolResult:
        """Simple keyword search when no embedding API is available."""
        query_words = set(query.lower().split())
        scored = []

        for doc in self._documents.values():
            chunk_dir = self._knowledge_dir / Path(doc.file_name).stem
            if not chunk_dir.exists():
                continue
            for chunk_path in sorted(chunk_dir.glob("chunk_*.txt")):
                try:
                    async with aiofiles.open(chunk_path, encoding="utf-8") as f:
                        chunk_text = await f.read()
                    # Simple word overlap scoring
                    chunk_words = set(chunk_text.lower().split())
                    overlap = len(query_words & chunk_words)
                    if overlap > 0:
                        score = overlap / len(query_words)
                        scored.append((score, doc.file_name, chunk_text[:300]))
                except Exception:
                    continue

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            return ToolResult(output="No results found in knowledge base.")

        lines = [f"Found {min(len(scored), top_k)} results (keyword search):\n"]
        for i, (score, source, text) in enumerate(scored[:top_k], 1):
            lines.append(f"[{i}] ({score:.2f}) {source}\n    {text}\n")

        return ToolResult(output="\n".join(lines))

    def _action_list(self) -> ToolResult:
        if not self._documents:
            return ToolResult(
                output="Knowledge base is empty. Use import_file or import_dir to add documents."
            )

        lines = [f"{'File':<40} {'Type':<6} {'Chunks':<8} {'Imported':<20}"]
        for doc in self._documents.values():
            imported_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(doc.imported_at))
            lines.append(
                f"{doc.file_name:<40} {doc.file_type:<6} {doc.chunk_count:<8} {imported_str:<20}"
            )
        lines.append(
            f"\nTotal: {len(self._documents)} documents, "
            f"{sum(d.chunk_count for d in self._documents.values())} chunks"
        )
        return ToolResult(output="\n".join(lines))

    async def _action_delete(self, path: str = "", **kwargs) -> ToolResult:
        if not path:
            return ToolResult(error="Path is required for delete", success=False)

        doc = self._documents.pop(path, None)
        if not doc:
            # Try matching by filename
            matching = [k for k, v in self._documents.items() if v.file_name == path]
            if matching:
                doc = self._documents.pop(matching[0])

        if not doc:
            return ToolResult(error=f"Document not found: {path}", success=False)

        # Clean up chunk files
        chunk_dir = self._knowledge_dir / Path(doc.file_name).stem
        if chunk_dir.exists():
            import shutil

            shutil.rmtree(chunk_dir, ignore_errors=True)

        self._save_index()
        logger.info(f"Deleted knowledge document: {doc.file_name}")
        return ToolResult(output=f"Deleted {doc.file_name} ({doc.chunk_count} chunks removed)")
