"""Batch job planning helpers for Agoda crawls."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from agoda_crawler.utils import make_daily_output_path


@dataclass(frozen=True)
class CrawlJob:
    destination: str
    check_in: str
    check_out: str
    output_path: Path


@dataclass(frozen=True)
class CrawlJobResult:
    job: CrawlJob
    records: List[Dict]
    debug_records: List[Dict] | None = None


def parse_destinations(destinations: str, fallback: str) -> List[str]:
    values = [part.strip() for part in destinations.split(",") if part.strip()]
    return values or [fallback]


def parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Date must be YYYY-MM-DD or DD/MM/YYYY: {value}")


def iter_stays(args) -> List[tuple[str, str]]:
    if bool(args.date_start) != bool(args.date_end):
        raise ValueError("--date-start and --date-end must be used together")

    if args.date_start and args.date_end:
        current = parse_date(args.date_start)
        end = parse_date(args.date_end)
        if end < current:
            raise ValueError("--date-end must be on or after --date-start")

        stays: List[tuple[str, str]] = []
        while current <= end:
            check_out = current + timedelta(days=1)
            stays.append((current.isoformat(), check_out.isoformat()))
            current += timedelta(days=1)
        return stays

    return [(parse_date(args.check_in).isoformat(), parse_date(args.check_out).isoformat())]


def annotate_record(record: Dict, destination: str, check_in: str, check_out: str) -> Dict:
    enriched = dict(record)
    enriched["destination"] = destination
    enriched["check_in"] = check_in
    enriched["check_out"] = check_out
    return enriched


def output_path_for_stay(args, check_in: str, total_stays: int) -> Path:
    return make_daily_output_path(args.output_dir, check_in)


def build_crawl_jobs(
    args,
    destinations: List[str],
    stays: List[tuple[str, str]],
) -> List[CrawlJob]:
    jobs: List[CrawlJob] = []
    for check_in, check_out in stays:
        output_path = output_path_for_stay(args, check_in, len(stays))
        for destination in destinations:
            jobs.append(
                CrawlJob(
                    destination=destination,
                    check_in=check_in,
                    check_out=check_out,
                    output_path=output_path,
                )
            )
    return jobs


def chunk_jobs(jobs: List[CrawlJob], worker_count: int) -> List[List[CrawlJob]]:
    chunks: List[List[CrawlJob]] = [[] for _ in range(worker_count)]
    for index, job in enumerate(jobs):
        chunks[index % worker_count].append(job)
    return [chunk for chunk in chunks if chunk]


def jobs_for_stay(jobs: List[CrawlJob], check_in: str) -> List[CrawlJob]:
    return [job for job in jobs if job.check_in == check_in]


def ordered_results(
    jobs: List[CrawlJob],
    results: List[CrawlJobResult],
) -> List[CrawlJobResult]:
    remaining = list(results)
    ordered: List[CrawlJobResult] = []
    for job in jobs:
        for index, result in enumerate(remaining):
            if result.job == job:
                ordered.append(result)
                remaining.pop(index)
                break
    ordered.extend(remaining)
    return ordered
