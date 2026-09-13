"""
backfill_questions.py
---------------------
Extract questions from every paper in the `courses` table and store them
in `paper_questions`. Safe to re-run (uses ON CONFLICT DO NOTHING).

Usage:
    python backfill_questions.py                # process all papers
    python backfill_questions.py --only-new     # only papers without an extract
    python backfill_questions.py --course CS-301
"""

import argparse
import os
import sys
import requests
import psycopg2
import psycopg2.extras
import time, re
from dotenv import load_dotenv

# Reuse the helpers we already wrote in app.py
from app import (
    get_db_connection,
    extract_pdf_text,
    ocr_with_groq,
    segment_questions,
)

load_dotenv()


def fetch_papers(cur, course_code=None, only_new=False):
    if only_new:
        sql = """
            SELECT c.id, c.course_code, c.exam_type, c.year, c.pdf_url
            FROM courses c
            LEFT JOIN paper_extracts pe ON pe.paper_id = c.id
            WHERE pe.paper_id IS NULL
        """
    else:
        sql = """
            SELECT c.id, c.course_code, c.exam_type, c.year, c.pdf_url
            FROM courses c
        """
    params = []
    if course_code:
        sql += " AND c.course_code = %s" if only_new else " WHERE c.course_code = %s"
        params.append(course_code)
    cur.execute(sql, params)
    return cur.fetchall()


def process_paper(cur, paper):
    pid = paper["id"]
    code = paper["course_code"]
    etype = paper["exam_type"]
    year = paper["year"]
    url = paper["pdf_url"]

    print(f"→ [{pid}] {code} {etype} {year}", end="  ", flush=True)

    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        pdf_bytes = r.content
    except Exception as e:
        print(f"FAILED download: {e}")
        return False

    mode, text, images = extract_pdf_text(pdf_bytes)

    if mode == "ocr":
        if not images:
            print("no images rendered")
            return False

        max_retries = 5
        for attempt in range(max_retries):
            try:
                text = ocr_with_groq(images)
                if text and text.strip():
                    break
                print("OCR returned empty, retrying...", end=" ")
                time.sleep(10)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    # Extract retry-after from the error message if present
                    m = re.search(r"try again in ([\d.]+)s", err)
                    wait = float(m.group(1)) if m else (2 ** attempt * 5)
                    wait = max(wait, 10)  # never less than 10s
                    print(f"rate limited, waiting {wait:.1f}s...", end=" ")
                    time.sleep(wait)
                else:
                    print(f"OCR error: {err[:80]}")
                    return False
        else:
            print("OCR failed after retries")
            return False


    print(f"mode={mode} chars={len(text)}", end="  ", flush=True)

    # Store the raw extract
    cur.execute("""
        INSERT INTO paper_extracts
            (paper_id, course_code, exam_type, year, extraction_mode, raw_text)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (paper_id) DO UPDATE
            SET raw_text = EXCLUDED.raw_text,
                extraction_mode = EXCLUDED.extraction_mode,
                extracted_at = CURRENT_TIMESTAMP
    """, (pid, code, etype, year, mode, text))

    # Segment + store questions
    questions = segment_questions(text)
    inserted = 0
    for q in questions:
        try:
            cur.execute("""
                INSERT INTO paper_questions
                    (course_code, exam_type, year, question_text, marks, source_paper_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (course_code, exam_type, year, question_text)
                DO NOTHING
            """, (code, etype, year, q["text"], q["marks"], pid))
            if cur.rowcount:
                inserted += 1
        except Exception as e:
            print(f"  (question insert skipped: {e})")

    print(f"questions={inserted}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-new", action="store_true",
                        help="Only process papers without an extract yet")
    parser.add_argument("--course", help="Limit to one course code")
    args = parser.parse_args()

    conn = get_db_connection()
    if conn is None:
        print("DB connection failed")
        sys.exit(1)

    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    papers = fetch_papers(cur, args.course, args.only_new)
    print(f"Processing {len(papers)} paper(s)...\n")

    ok = 0
    for p in papers:                                          # <-- the loop
        try:
            if process_paper(cur, p):
                ok += 1
                conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  ROLLBACK: {e}")
        print()                    # newline after each paper's log
        time.sleep(30) 

    cur.close()
    conn.close()
    print(f"\nDone. {ok}/{len(papers)} papers processed.")




if __name__ == "__main__":
    main()