"""
migrate.py — Migration CLI for Agent42 -> Paperclip company structure.

Copies Qdrant vectors (with company_id remapping and UUID5 regeneration)
and effectiveness SQLite rows (with agent_id preserved) from a standalone
Agent42 installation into a Paperclip-connected deployment.

Usage:
    python migrate.py \
        --frood-db .frood/effectiveness.db \
        --qdrant-url http://localhost:6333 \
        --target-qdrant-url http://localhost:6334 \
        --paperclip-company-id <uuid>

    python migrate.py --dry-run \
        --frood-db .frood/effectiveness.db \
        --qdrant-url http://localhost:6333 \
        --target-qdrant-url http://localhost:6334 \
        --paperclip-company-id <uuid>
"""

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

import aiosqlite

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

logger = logging.getLogger(__name__)

# Same namespace as memory/qdrant_store.py line 248
NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")

# Collection suffixes matching QdrantStore
COLLECTION_SUFFIXES = ["memory", "history", "conversations", "knowledge"]

# Effectiveness tables to migrate
EFFECTIVENESS_TABLES = [
    "tool_invocations",
    "routing_decisions",
    "spend_history",
    "run_transcripts",
]


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser with all required and optional flags."""
    parser = argparse.ArgumentParser(
        description="Migrate Agent42 agents into Paperclip company structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--frood-db",
        required=True,
        help="Path to source effectiveness.db",
    )
    parser.add_argument(
        "--qdrant-url",
        required=True,
        help="Source Qdrant server URL",
    )
    parser.add_argument(
        "--target-qdrant-url",
        required=True,
        help="Target Qdrant server URL",
    )
    parser.add_argument(
        "--paperclip-company-id",
        required=True,
        help="Target Paperclip company UUID",
    )
    parser.add_argument(
        "--collection-prefix",
        default="agent42",
        help="Qdrant collection prefix (default: agent42)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Points per scroll batch (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing to target",
    )
    parser.add_argument(
        "--target-db",
        default=None,
        help="Target effectiveness.db path (default: source with .migrated suffix)",
    )
    return parser


def remap_point(point, target_company_id: str) -> "PointStruct":
    """Remap a Qdrant point with new company_id and regenerated UUID5 ID.

    Preserves agent_id and all other payload fields. Regenerates point ID
    using deterministic UUID5 from content to avoid collisions.
    """
    payload = dict(point.payload)
    payload["company_id"] = target_company_id
    # agent_id preserved as-is (D-08)

    # Regenerate UUID5 point ID from content (D-10)
    content = f"{payload.get('source', '')}:{payload.get('text', '')}"
    new_id = str(uuid.uuid5(NAMESPACE, content))

    return PointStruct(id=new_id, vector=point.vector, payload=payload)


async def migrate_collection(
    src_client,
    dst_client,
    collection: str,
    company_id: str,
    batch_size: int,
    dry_run: bool,
) -> int:
    """Scroll source collection and upsert remapped points to target.

    Returns total number of points migrated.
    """
    offset = None
    total = 0

    while True:
        records, next_offset = src_client.scroll(
            collection_name=collection,
            offset=offset,
            limit=batch_size,
            with_vectors=True,
            with_payload=True,
        )
        if not records:
            break

        points = [remap_point(r, company_id) for r in records]
        if not dry_run:
            dst_client.upsert(collection_name=collection, points=points)
        total += len(points)

        if next_offset is None:
            break
        offset = next_offset

    return total


async def ensure_target_collections(dst_client, prefix: str) -> None:
    """Ensure target Qdrant has all required collections.

    Uses QdrantStore._ensure_collection pattern for each suffix.
    """
    from memory.qdrant_store import QdrantConfig, QdrantStore

    config = QdrantConfig(collection_prefix=prefix)
    store = QdrantStore.__new__(QdrantStore)
    store.config = config
    store._client = dst_client
    store._initialized_collections = set()

    for suffix in COLLECTION_SUFFIXES:
        store._ensure_collection(suffix)
        logger.info(f"Ensured collection: {prefix}_{suffix}")


async def migrate_effectiveness(src_db: str, dst_db: str) -> dict:
    """Copy all effectiveness rows from source to target DB.

    Uses INSERT OR IGNORE to handle re-runs safely.
    Returns dict with row counts per table.
    """
    from memory.effectiveness import EffectivenessStore

    # Ensure target DB has correct schema
    target_store = EffectivenessStore(dst_db)
    await target_store._ensure_db()

    counts = {}

    async with aiosqlite.connect(src_db) as src:
        async with aiosqlite.connect(dst_db) as dst:
            # tool_invocations
            cursor = await src.execute(
                "SELECT tool_name, task_type, task_id, success, duration_ms, ts, agent_id "
                "FROM tool_invocations"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await dst.execute(
                    "INSERT OR IGNORE INTO tool_invocations "
                    "(tool_name, task_type, task_id, success, duration_ms, ts, agent_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
            counts["tool_invocations"] = len(rows)

            # routing_decisions
            cursor = await src.execute(
                "SELECT run_id, agent_id, company_id, provider, model, tier, task_category, ts "
                "FROM routing_decisions"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await dst.execute(
                    "INSERT OR IGNORE INTO routing_decisions "
                    "(run_id, agent_id, company_id, provider, model, tier, task_category, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
            counts["routing_decisions"] = len(rows)

            # spend_history
            cursor = await src.execute(
                "SELECT agent_id, company_id, provider, model, input_tokens, output_tokens, "
                "cost_usd, hour_bucket, ts FROM spend_history"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await dst.execute(
                    "INSERT OR IGNORE INTO spend_history "
                    "(agent_id, company_id, provider, model, input_tokens, output_tokens, "
                    "cost_usd, hour_bucket, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
            counts["spend_history"] = len(rows)

            # run_transcripts
            cursor = await src.execute(
                "SELECT run_id, agent_id, company_id, task_type, summary, extracted, ts "
                "FROM run_transcripts"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await dst.execute(
                    "INSERT OR IGNORE INTO run_transcripts "
                    "(run_id, agent_id, company_id, task_type, summary, extracted, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
            counts["run_transcripts"] = len(rows)

            await dst.commit()

    logger.info(f"Effectiveness migration complete: {counts}")
    return counts


async def run_migration(args) -> None:
    """Execute the full migration pipeline."""
    # Validate source DB exists
    if not Path(args.frood_db).exists():
        logger.error(f"Source database not found: {args.frood_db}")
        sys.exit(1)

    if not QDRANT_AVAILABLE:
        logger.error("qdrant-client not installed — cannot migrate Qdrant data")
        sys.exit(1)

    # Target DB path
    target_db = args.target_db or f"{args.frood_db}.migrated"

    # Create Qdrant clients
    src_client = QdrantClient(url=args.qdrant_url)
    dst_client = QdrantClient(url=args.target_qdrant_url)

    # Ensure target collections exist
    await ensure_target_collections(dst_client, args.collection_prefix)

    # Migrate Qdrant collections
    total_points = 0
    for suffix in COLLECTION_SUFFIXES:
        collection_name = f"{args.collection_prefix}_{suffix}"
        count = await migrate_collection(
            src_client,
            dst_client,
            collection_name,
            args.paperclip_company_id,
            args.batch_size,
            args.dry_run,
        )
        total_points += count
        action = "Scanned" if args.dry_run else "Migrated"
        logger.info(f"{action} {count} points from {collection_name}")

    # Migrate effectiveness DB (unless dry_run)
    if not args.dry_run:
        counts = await migrate_effectiveness(args.frood_db, target_db)
        logger.info(
            f"Migration complete: {total_points} Qdrant points, effectiveness rows: {counts}"
        )
    else:
        logger.info(f"Dry run complete: {total_points} Qdrant points would be migrated")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    asyncio.run(run_migration(args))
