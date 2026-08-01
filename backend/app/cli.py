from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Document, KnowledgeChunk
from app.db.session import SessionLocal, init_db
from app.services.evaluation import (
    evaluate_answers,
    evaluate_retrieval,
    load_evaluation_cases,
    write_evaluation_report,
)
from app.services.hybrid_retrieval import retrieve_chunks
from app.services.indexing import index_document
from app.services.manifest import scan_source_directory
from app.services.parsers import parse_document
from app.services.parsers.converter import find_soffice
from app.services.parsers.registry import PARSER_VERSION
from app.services.vector_indexing import index_chunk_vectors


def command_scan() -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    init_db()
    with SessionLocal() as db:
        result = scan_source_directory(db, settings)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


def command_stats() -> int:
    init_db()
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Document)) or 0
        by_status = dict(
            db.execute(
                select(Document.ingest_status, func.count(Document.id)).group_by(
                    Document.ingest_status
                )
            ).all()
        )
        by_extension = dict(
            db.execute(
                select(Document.extension, func.count(Document.id)).group_by(Document.extension)
            ).all()
        )
        indexed_chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    print(
        json.dumps(
            {
                "total": total,
                "indexed_chunks": indexed_chunks,
                "by_status": by_status,
                "by_extension": by_extension,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_parse(
    limit: int,
    extensions: list[str] | None,
    *,
    force: bool = False,
) -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    init_db()
    normalized_extensions = None
    if extensions:
        normalized_extensions = [
            item if item.startswith(".") else f".{item}" for item in extensions
        ]
    with SessionLocal() as db:
        filters = [Document.is_active.is_(True)]
        if not force:
            filters.append(Document.ingest_status.in_(["discovered", "failed"]))
        if normalized_extensions:
            filters.append(Document.extension.in_(normalized_extensions))
        documents = list(
            db.scalars(
                select(Document)
                .where(*filters)
                .order_by(Document.sequence_no.asc().nulls_last())
                .limit(limit)
            ).all()
        )
        results = []
        for document in documents:
            try:
                document.ingest_status = "parsing"
                db.commit()
                output = parse_document(document, settings)
                document.parsed_artifact_path = str(output)
                document.parser_version = PARSER_VERSION
                db.commit()
                chunk_count = index_document(document, db)
                results.append(
                    {
                        "doc_id": document.doc_id,
                        "status": "indexed",
                        "output": str(output),
                        "chunk_count": chunk_count,
                    }
                )
            except Exception as exc:
                document.ingest_status = "failed"
                document.error_code = type(exc).__name__
                document.error_message = str(exc)[:4000]
                db.commit()
                results.append({"doc_id": document.doc_id, "status": "failed", "error": str(exc)})
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "indexed" for item in results) else 1


def command_index(limit: int) -> int:
    init_db()
    with SessionLocal() as db:
        documents = list(
            db.scalars(
                select(Document)
                .where(
                    Document.is_active.is_(True),
                    Document.ingest_status.in_(["parsed", "indexed"]),
                    Document.parsed_artifact_path.is_not(None),
                )
                .order_by(Document.sequence_no.asc().nulls_last())
                .limit(limit)
            ).all()
        )
        results = []
        for document in documents:
            try:
                chunk_count = index_document(document, db)
                results.append(
                    {
                        "doc_id": document.doc_id,
                        "status": "indexed",
                        "chunk_count": chunk_count,
                    }
                )
            except Exception as exc:
                document.ingest_status = "failed"
                document.error_code = type(exc).__name__
                document.error_message = str(exc)[:4000]
                db.commit()
                results.append(
                    {"doc_id": document.doc_id, "status": "failed", "error": str(exc)}
                )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "indexed" for item in results) else 1


def command_search(question: str, top_k: int) -> int:
    settings = get_settings()
    init_db()
    with SessionLocal() as db:
        retrieval = retrieve_chunks(
            db,
            question,
            settings=settings,
            top_k=top_k,
        )
    print(
        json.dumps(
            {
                "retrieval_mode": retrieval.mode,
                "warnings": retrieval.warnings,
                "evidence": [hit.to_evidence() for hit in retrieval.hits],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if retrieval.hits else 2


def command_doctor() -> int:
    settings = get_settings()
    init_db()
    soffice = find_soffice()
    with SessionLocal() as db:
        legacy_total = (
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.is_active.is_(True),
                    Document.extension.in_([".doc", ".xls"]),
                )
            )
            or 0
        )
        legacy_pending = (
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.is_active.is_(True),
                    Document.extension.in_([".doc", ".xls"]),
                    Document.ingest_status != "indexed",
                )
            )
            or 0
        )
    report = {
        "source_data_available": settings.source_data_dir.is_dir(),
        "qa_workbook_available": settings.qa_workbook_path.is_file(),
        "libreoffice_available": soffice is not None,
        "libreoffice_path": soffice,
        "legacy_total": legacy_total,
        "legacy_pending": legacy_pending,
        "embedding_configured": settings.embedding_is_configured,
        "embedding_provider": settings.embedding_provider,
        "qdrant_url": settings.qdrant_url,
        "llm_configured": settings.llm_is_configured,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["source_data_available"] else 2


def command_convert_legacy(limit: int) -> int:
    if find_soffice() is None:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "未找到 LibreOffice/soffice",
                    "action": "请在 Docker 镜像或已安装 LibreOffice 的服务器运行同一命令",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    return command_parse(limit, [".doc", ".xls"])


def command_vector_index(limit: int | None) -> int:
    settings = get_settings()
    init_db()
    try:
        with SessionLocal() as db:
            report = index_chunk_vectors(db, settings, limit=limit)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


def command_evaluate(
    source_type: str | None,
    limit: int | None,
    top_k: int,
    mode: str,
) -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    init_db()
    cases = load_evaluation_cases(
        settings.qa_workbook_path,
        source_type=source_type,
        limit=limit,
    )
    with SessionLocal() as db:
        report = evaluate_retrieval(
            db,
            cases,
            top_k=top_k,
            mode=mode,
            settings=settings,
        )
    label = source_type or "all"
    output_path = settings.evaluation_dir / f"retrieval_{label}_{mode}.json"
    write_evaluation_report(report, output_path)
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report_path"] = str(output_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_evaluate_answers(
    source_type: str | None,
    limit: int | None,
    top_k: int,
    retrieval_mode: str,
) -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    init_db()
    cases = load_evaluation_cases(
        settings.qa_workbook_path,
        source_type=source_type,
        limit=limit,
    )
    with SessionLocal() as db:
        report = evaluate_answers(
            db,
            cases,
            settings=settings,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )
    label = source_type or "all"
    output_path = settings.evaluation_dir / f"answers_{label}_{retrieval_mode}.json"
    write_evaluation_report(report, output_path)
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report_path"] = str(output_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="可信监管 RAG 数据管理 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scan", help="扫描原始文件并生成 manifest")
    subparsers.add_parser("stats", help="输出文件台账统计")
    subparsers.add_parser("doctor", help="检查数据、旧格式转换和模型运行条件")
    parse_parser = subparsers.add_parser("parse", help="解析一批待处理文件")
    parse_parser.add_argument("--limit", type=int, default=10)
    parse_parser.add_argument("--extension", action="append", dest="extensions")
    parse_parser.add_argument(
        "--force",
        action="store_true",
        help="重新解析并替换已有派生知识块，不修改原始文件",
    )
    index_parser = subparsers.add_parser("index", help="为已解析文件建立知识块索引")
    index_parser.add_argument("--limit", type=int, default=100)
    legacy_parser = subparsers.add_parser(
        "convert-legacy",
        help="转换、解析并索引一批 DOC/XLS；缺少 LibreOffice 时不会改写状态",
    )
    legacy_parser.add_argument("--limit", type=int, default=500)
    vector_parser = subparsers.add_parser(
        "vector-index",
        help="使用已配置的 Embedding 服务重建 Qdrant 向量索引",
    )
    vector_parser.add_argument("--limit", type=int)
    search_parser = subparsers.add_parser("search", help="检索已索引的证据")
    search_parser.add_argument("question")
    search_parser.add_argument("--top-k", type=int, default=5)
    evaluate_parser = subparsers.add_parser("evaluate", help="运行甲方 QA 检索基线评测")
    evaluate_parser.add_argument("--source-type", choices=["excel", "word", "pdf"])
    evaluate_parser.add_argument("--limit", type=int)
    evaluate_parser.add_argument("--top-k", type=int, default=5)
    evaluate_parser.add_argument(
        "--mode",
        choices=["lexical", "hybrid"],
        default="lexical",
    )
    answer_parser = subparsers.add_parser(
        "evaluate-answers",
        help="评测选择题答案准确率、可映射率和答案引用命中率",
    )
    answer_parser.add_argument("--source-type", choices=["excel", "word", "pdf"])
    answer_parser.add_argument("--limit", type=int)
    answer_parser.add_argument("--top-k", type=int, default=5)
    answer_parser.add_argument(
        "--retrieval-mode",
        choices=["lexical", "hybrid"],
        default="hybrid",
    )
    return parser


def main() -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    configure_logging(settings.log_level)
    args = build_parser().parse_args()
    if args.command == "scan":
        return command_scan()
    if args.command == "stats":
        return command_stats()
    if args.command == "doctor":
        return command_doctor()
    if args.command == "parse":
        return command_parse(args.limit, args.extensions, force=args.force)
    if args.command == "index":
        return command_index(args.limit)
    if args.command == "convert-legacy":
        return command_convert_legacy(args.limit)
    if args.command == "vector-index":
        return command_vector_index(args.limit)
    if args.command == "search":
        return command_search(args.question, args.top_k)
    if args.command == "evaluate":
        return command_evaluate(args.source_type, args.limit, args.top_k, args.mode)
    if args.command == "evaluate-answers":
        return command_evaluate_answers(
            args.source_type,
            args.limit,
            args.top_k,
            args.retrieval_mode,
        )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
