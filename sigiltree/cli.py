"""CLI entry point for sigil tree pipeline."""

import argparse
import logging
import sys
from pathlib import Path


def cmd_index(args):
    from sigiltree.indexer import index_corpus
    corpus = Path(args.corpus_path)
    artifacts = Path(args.artifact_dir)
    if not corpus.is_dir():
        print(f"Corpus path not found: {corpus}", file=sys.stderr)
        sys.exit(1)
    stats = index_corpus(corpus, artifacts)
    return stats


def cmd_embed(args):
    from sigiltree.embeddings import compute_embeddings
    artifacts = Path(args.artifact_dir)
    if not artifacts.is_dir():
        print(f"Artifact dir not found: {artifacts}", file=sys.stderr)
        sys.exit(1)
    stats = compute_embeddings(artifacts, batch_size=args.batch_size)
    return stats


def cmd_nn(args):
    from sigiltree.embeddings import nearest_neighbors
    from sigiltree import db
    artifacts = Path(args.artifact_dir)
    results = nearest_neighbors(artifacts, args.family, args.image_id, k=args.k)
    conn = db.open_db(artifacts)
    for nid, sim in results:
        cur = conn.execute("SELECT filename FROM images WHERE image_id = ?", (nid,))
        row = cur.fetchone()
        fname = row[0] if row else nid
        print(f"  {sim:.4f}  {nid}  {fname}")
    conn.close()


def cmd_contrasts(args):
    from sigiltree.contrasts import build_contrasts
    artifacts = Path(args.artifact_dir)
    if not artifacts.is_dir():
        print(f"Artifact dir not found: {artifacts}", file=sys.stderr)
        sys.exit(1)
    stats = build_contrasts(artifacts)
    return stats


def cmd_atlas(args):
    artifacts = Path(args.artifact_dir)
    if not artifacts.is_dir():
        print(f"Artifact dir not found: {artifacts}", file=sys.stderr)
        sys.exit(1)
    if args.levels <= 1:
        from sigiltree.atlas import build_atlas
        stats = build_atlas(artifacts, level=0, seed=args.seed)
    else:
        from sigiltree.atlas import build_atlas_recursive
        stats = build_atlas_recursive(artifacts, max_levels=args.levels, seed=args.seed)
    return stats


def cmd_serve(args):
    from sigiltree.viewer_server import run_server
    artifacts = Path(args.artifact_dir)
    if not artifacts.is_dir():
        print(f"Artifact dir not found: {artifacts}", file=sys.stderr)
        sys.exit(1)
    run_server(artifacts, host=args.host, port=args.port)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(prog="sigiltree", description="Sigil Tree corpus tools")
    sub = parser.add_subparsers(dest="command")

    p_index = sub.add_parser("index", help="Index a corpus and build artifacts")
    p_index.add_argument("corpus_path", help="Path to image corpus directory")
    p_index.add_argument("artifact_dir", help="Path to artifact output directory")

    p_embed = sub.add_parser("embed", help="Compute embedding families")
    p_embed.add_argument("artifact_dir", help="Path to artifact directory")
    p_embed.add_argument("--batch-size", type=int, default=32)

    p_nn = sub.add_parser("nn", help="Query nearest neighbors")
    p_nn.add_argument("artifact_dir", help="Path to artifact directory")
    p_nn.add_argument("--family", required=True, choices=["clip", "dino", "texture"])
    p_nn.add_argument("--image-id", required=True, help="Query image ID")
    p_nn.add_argument("--k", type=int, default=20)

    sub.add_parser("contrasts", help="Build contrast library").add_argument(
        "artifact_dir", help="Path to artifact directory"
    )

    p_atlas = sub.add_parser("atlas", help="Build atlas levels")
    p_atlas.add_argument("artifact_dir", help="Path to artifact directory")
    p_atlas.add_argument("--levels", type=int, default=1, help="Number of levels to build")
    p_atlas.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    p_serve = sub.add_parser("serve", help="Launch the thumbnail grid viewer")
    p_serve.add_argument("artifact_dir", help="Path to artifact directory")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8777)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "index":
        cmd_index(args)
    elif args.command == "embed":
        cmd_embed(args)
    elif args.command == "nn":
        cmd_nn(args)
    elif args.command == "contrasts":
        cmd_contrasts(args)
    elif args.command == "atlas":
        cmd_atlas(args)
    elif args.command == "serve":
        cmd_serve(args)


if __name__ == "__main__":
    main()
