import os
import io
import re
import gc
import json
import time
import uuid
import shutil
import logging
import tempfile
import threading
import threading as _threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pandas as pd
import dateutil.parser
from dateutil import parser

import openpyxl
from io import BytesIO
from openpyxl.styles import PatternFill, Border, Side, Font, Alignment
from openpyxl.utils import get_column_letter

from dotenv import load_dotenv
from fastapi import (
    FastAPI, HTTPException, BackgroundTasks,
    Body, File, Form, UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# ── Optional: Polars (required for large-scale endpoint) ────────────────────
try:
    import polars as _pl_check
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False

# ── Optional: Google GenAI (Gemini) ─────────────────────────────────────────
try:
    from google import genai
except Exception:
    try:
        import google.genai as genai
    except Exception:
        genai = None

load_dotenv()


def _get_writable_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(
            os.environ.get(
                "POSTVALIDATION_DATA_DIR",
                os.path.join(os.environ.get("APPDATA", ""), "PostValidation"),
            )
        )
    else:
        base = Path("Required_files")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / relative_path
    return Path(relative_path)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

_allowed_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
ORIGINS = [o.strip() for o in _allowed_origins.split(",") if o.strip()] or [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1",
    "null",
]

app = FastAPI(
    title="Post-Validation Service",
    description="Standalone post-validation API extracted from Project Charlie.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/api/excel/sheets")
async def get_excel_sheets(
    file: UploadFile = File(...),
    customerName: str = Form(...),
    instanceName: str = Form(...)
):
    """
    Upload an Excel file and return:
      - List of sheet names
      - Columns from each sheet
    Also saves the Excel file inside Required_files/Post-Validation_Excels
    using an iterator (1, 2, 3...) for duplicate uploads.
    """
    try:
        # Read file bytes
        content = await file.read()
        filename = file.filename.lower()

        if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
            return JSONResponse(
                content={"error": "Unsupported file type. Upload .xlsx or .xls only."},
                status_code=400,
            )

        # Read Excel content once
        excel_file = pd.ExcelFile(io.BytesIO(content))
        sheet_names = excel_file.sheet_names

        # Extract columns for each sheet
        columns_dict = {}
        for sheet in sheet_names:
            df = excel_file.parse(sheet)
            columns_dict[sheet] = df.columns.tolist()

        # Prepare save directory
        save_dir = _get_writable_dir() / "Post-Validation_Excels"
        save_dir.mkdir(parents=True, exist_ok=True)

        # File name pattern: Customer_Instance_#.xlsx
        base_name = f"{customerName}_{instanceName}"
        existing_files = list(save_dir.glob(f"{base_name}_*.xlsx"))

        # Determine next iterator number
        next_index = len(existing_files) + 1
        save_excel_name = f"{base_name}_{next_index}.xlsx"
        save_path = save_dir / save_excel_name

        # Save the file
        with open(save_path, "wb") as f:
            f.write(content)

        # Return structured response
        return {
            "sheets": sheet_names,
            "columns": columns_dict,
            "saved_as": save_excel_name,
            "message": "Excel uploaded and processed successfully."
        }

    except Exception as e:
        return JSONResponse(
            content={"error": f"Failed to read Excel file: {str(e)}"},
            status_code=500,
        )
    
GOOGLE_API_KEY = os.environ.get('GEMINI_API_KEY', '')
if genai is None:
    logging.info("GenAI client not installed; GenAI features are disabled.")
elif not GOOGLE_API_KEY:
    logging.info("GEMINI_API_KEY not set; GenAI features are disabled until configured.")

def get_smart_mapping_from_gemini(legacy_cols: List[str], oracle_cols: List[str]):
    """
    Updated to return Mapping + Data Type Detection
    """
    fallback_result = {
        "mapping": {},
        "date_columns": [],
        "timestamp_columns": []
    }
    
    # Simple exact match fallback
    oracle_cols_lower = {col.lower(): col for col in oracle_cols}
    for l_col in legacy_cols:
        if l_col.lower() in oracle_cols_lower:
            fallback_result["mapping"][l_col] = oracle_cols_lower[l_col.lower()]

    if not GOOGLE_API_KEY or genai is None:
        return fallback_result

    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)

        prompt = f"""
            You are a Data Integration Expert.
            Legacy Columns: {json.dumps(legacy_cols)}
            Oracle Columns: {json.dumps(oracle_cols)}

            Task:
            1. Map 'Legacy Columns' to semantically similar 'Oracle Columns'.
               If a legacy column has NO suitable semantic match in the Oracle columns,
               map it to an empty string "" (blank). Do NOT force a mapping.
            2. Identify which 'Legacy Columns' likely contain DATES (e.g., DOB, Start Date).
            3. Identify which 'Legacy Columns' likely contain TIMESTAMPS (e.g., Created At, Last Update).

            IMPORTANT: Every legacy column MUST appear as a key in the mapping.
            If there is no good match, set its value to "" (empty string).

            Return JSON format:
            {{
                "mapping": {{ "LegacyCol": "OracleCol or empty string", ... }},
                "date_columns": [ "LegacyCol1", ... ],
                "timestamp_columns": [ "LegacyCol2", ... ]
            }}
        """

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        text = response.text
        # response_mime_type is application/json so text is already JSON;
        # fall back to regex extraction in case of extra surrounding text
        try:
            ai_data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match:
                return fallback_result
            ai_data = json.loads(match.group(0))

        # Validate AI suggestions — only keep targets that actually exist in oracle_cols.
        # Gemini sometimes hallucinates column names; discard those entirely.
        oracle_set       = set(oracle_cols)
        oracle_lower_map = {c.lower(): c for c in oracle_cols}
        validated_ai = {}
        for src, tgt in ai_data.get("mapping", {}).items():
            if not tgt:
                continue  # AI said no match — let fallback decide
            if tgt in oracle_set:
                validated_ai[src] = tgt
            elif tgt.lower() in oracle_lower_map:
                validated_ai[src] = oracle_lower_map[tgt.lower()]
            # else: hallucinated name — discard

        # Merge: start with fallback exact-matches, then layer validated AI on top.
        # AI only overrides when it found a real oracle column.
        final_mapping = {**fallback_result["mapping"], **validated_ai}
        return {
            "mapping": final_mapping,
            "date_columns": ai_data.get("date_columns", []),
            "timestamp_columns": ai_data.get("timestamp_columns", [])
        }

    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return fallback_result


@app.post("/api/hdl/gemini-map")
def gemini_map(payload: Dict = Body(...)):
    """Return a smart mapping between legacy (source) and oracle (target) columns.

    Expected payload shape (example):
    {
      "legacy_columns": [...],
      "oracle_columns": [...],
      "suggested_mapping": {"LegacyCol": "OracleCol"},
      "date_columns": [ ... ]
    }

    The endpoint will call `get_smart_mapping_from_gemini` when configured, fall
    back to exact-matches otherwise, then merge any `suggested_mapping` values
    supplied by the caller (these take precedence).
    """
    try:
        legacy_cols = payload.get("legacy_columns") or payload.get("source_columns") or []
        oracle_cols = payload.get("oracle_columns") or payload.get("target_columns") or []
        client_suggested = payload.get("suggested_mapping", {}) or {}
        client_date_cols = payload.get("date_columns", []) or []

        if not isinstance(legacy_cols, list) or not isinstance(oracle_cols, list):
            raise HTTPException(status_code=400, detail="`legacy_columns` and `oracle_columns` must be lists")

        ai_result = get_smart_mapping_from_gemini(legacy_cols, oracle_cols)

        # Merge AI mapping with client suggestions. Client suggestions override.
        final_mapping = dict(ai_result.get("mapping", {}))
        for k, v in client_suggested.items():
            if k in legacy_cols:
                final_mapping[k] = v

        # Build response in the format the frontend expects
        response = {
            "legacy_columns": legacy_cols,
            "oracle_columns": oracle_cols,
            "suggested_mapping": final_mapping,
            "date_columns": sorted(list(set(ai_result.get("date_columns", []) + client_date_cols))),
            "timestamp_columns": sorted(list(set(ai_result.get("timestamp_columns", []))))
        }

        return JSONResponse(content=response, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error in gemini_map endpoint")
        raise HTTPException(status_code=500, detail=str(e))


import re
from dateutil import parser

ORACLE_MIN_YEAR = -4712
ORACLE_MAX_YEAR = 9999

def normalize_dates(df, explicit_cols):
    def safe_parse(val):
        if pd.isna(val) or str(val).strip() == "":
            return ""

        val_str = str(val).strip()

        # Excel serial date handling
        if re.fullmatch(r"\d{5,}", val_str):
            try:
                return pd.to_datetime(float(val), unit="d", origin="1899-12-30") \
                         .strftime("%Y/%m/%d")
            except:
                return ""

        try:
            dt = parser.parse(
                val_str,
                dayfirst=True,
                yearfirst=False,
                fuzzy=True
            )

            year = dt.year

            # Oracle year boundaries
            if year < ORACLE_MIN_YEAR or year > ORACLE_MAX_YEAR:
                return ""

            return f"{year:04d}/{dt.month:02d}/{dt.day:02d}"

        except Exception:
            # Final fallback: keep original string (Oracle may still accept)
            return val_str

    for col in df.columns:
        if col in explicit_cols or pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].apply(safe_parse)

    return df



# ── Mapping job tracker (same pattern as validation jobs) ────────────────
import threading as _threading
_mapping_jobs: Dict[str, Dict[str, Any]] = {}
_mapping_jobs_lock = _threading.Lock()

def _compute_smooth_eta(job: dict) -> Optional[float]:
    """
    Compute a smooth, realistic ETA using exponential moving average (EMA)
    of the progress rate. Avoids wild swings early on.
    """
    prog = job.get("progress", 0)
    if prog >= 100:
        return 0.0
    if prog <= 0:
        return None

    now = time.time()
    started = job.get("started_at")
    if not started:
        return None

    elapsed = now - started
    if elapsed < 1.5:
        return None  # too early, not enough data

    # Track progress history: list of (timestamp, progress) snapshots
    history = job.setdefault("_eta_history", [])
    # Deduplicate: only append if progress actually changed
    if not history or history[-1][1] != prog:
        history.append((now, prog))
    # Keep last 20 snapshots to avoid unbounded memory
    if len(history) > 20:
        job["_eta_history"] = history[-20:]
        history = job["_eta_history"]

    if len(history) < 2:
        # Only one data point — use simple linear estimate
        rate = prog / elapsed  # %/sec
        raw_eta = (100 - prog) / rate
        return round(min(raw_eta, 7200), 1)  # cap at 2h

    # Compute recent rates between consecutive snapshots
    rates = []
    for i in range(1, len(history)):
        dt = history[i][0] - history[i - 1][0]
        dp = history[i][1] - history[i - 1][1]
        if dt > 0.1 and dp > 0:
            rates.append(dp / dt)  # %/sec for this interval

    if not rates:
        # Progress hasn't changed — use overall linear
        rate = prog / elapsed
        raw_eta = (100 - prog) / max(rate, 1e-6)
        return round(min(raw_eta, 7200), 1)

    # EMA of rates (alpha = 0.35 → recent rates weighed more)
    alpha = 0.35
    ema_rate = rates[0]
    for r in rates[1:]:
        ema_rate = alpha * r + (1 - alpha) * ema_rate

    # Also compute overall linear rate and blend (70% EMA, 30% linear)
    linear_rate = prog / elapsed
    blended_rate = 0.7 * ema_rate + 0.3 * linear_rate

    if blended_rate <= 1e-6:
        return round(min((100 - prog) / max(linear_rate, 1e-6), 7200), 1)

    raw_eta = (100 - prog) / blended_rate

    # Smooth against previous ETA to avoid jumps (EMA on the ETA itself)
    prev_eta = job.get("eta_seconds")
    if prev_eta is not None and prev_eta > 0:
        smoothed = 0.4 * raw_eta + 0.6 * prev_eta
    else:
        smoothed = raw_eta

    return round(max(0, min(smoothed, 7200)), 1)  # clamp 0–7200s


def _mapping_job_update(job_id: str, **kwargs):
    with _mapping_jobs_lock:
        if job_id in _mapping_jobs:
            _mapping_jobs[job_id].update(kwargs)
            job = _mapping_jobs[job_id]
            job["eta_seconds"] = _compute_smooth_eta(job)

def _mapping_job_get(job_id: str) -> Optional[Dict]:
    with _mapping_jobs_lock:
        return _mapping_jobs.get(job_id, {}).copy()


def _read_file_bytes(file_bytes: bytes, filename: str = ""):
    """Read Excel or CSV from bytes, return DataFrame."""
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    if ext == ".csv":
        return pd.read_csv(io.BytesIO(file_bytes))
    else:
        return pd.read_excel(io.BytesIO(file_bytes))


def _run_mapping_job(job_id: str, legacy_bytes: bytes, oracle_bytes: bytes,
                     legacy_filename: str = "", oracle_filename: str = ""):
    """Background thread: read files → call Gemini → store result."""
    logger.info(f"[Mapping] Starting job {job_id[:8]}, legacy_file='{legacy_filename}', oracle_file='{oracle_filename}'")
    try:
        # ── Stage 1: Read Legacy File ──
        _mapping_job_update(job_id, progress=10, stage="Reading source file")
        try:
            legacy_df = _read_file_bytes(legacy_bytes, legacy_filename)
            legacy_columns = legacy_df.columns.astype(str).str.strip().tolist()
        except Exception as e:
            _mapping_job_update(job_id, status="failed", error=f"Failed to read Legacy file: {str(e)}")
            return

        # ── Stage 2: Read Oracle File ──
        _mapping_job_update(job_id, progress=25, stage="Reading target file")
        try:
            oracle_df = _read_file_bytes(oracle_bytes, oracle_filename)
            oracle_columns = oracle_df.columns.astype(str).str.strip().tolist()
        except Exception as e:
            _mapping_job_update(job_id, status="failed", error=f"Failed to read Target file: {str(e)}")
            return

        # ── Stage 3: Gemini AI Mapping ──
        _mapping_job_update(job_id, progress=40, stage="Gemini analyzing columns")
        ai_result = get_smart_mapping_from_gemini(legacy_columns, oracle_columns)
        _mapping_job_update(job_id, progress=80, stage="Parsing AI response")

        # ── Stage 4: Build result ──
        _mapping_job_update(job_id, progress=95, stage="Finalizing mapping")
        result = {
            "legacy_columns": legacy_columns,
            "oracle_columns": oracle_columns,
            "suggested_mapping": ai_result["mapping"],
            "date_columns": ai_result.get("date_columns", []),
            "timestamp_columns": ai_result.get("timestamp_columns", []),
            "message": "Columns analyzed successfully."
        }

        _mapping_job_update(job_id, status="complete", progress=100, stage="Done", result=result)

    except Exception as e:
        _mapping_job_update(job_id, status="failed", error=f"Processing Error: {str(e)}")


@app.post("/api/excel/columns/mapping")
async def get_excel_columns_mapping_async(
    background_tasks: BackgroundTasks,
    legacyFile: UploadFile = File(...),
    oracleFile: UploadFile = File(...),
    legacySheet: str = Form(default=""),
    oracleSheet: str = Form(default=""),
    customerName: str = Form(...),
    instanceName: str = Form(...)
):
    """
    Async job-based mapping. Returns { job_id } immediately.
    Poll GET /api/excel/columns/mapping/status/{job_id} for progress.
    """
    job_id = str(uuid.uuid4())

    legacy_bytes = await legacyFile.read()
    oracle_bytes = await oracleFile.read()

    with _mapping_jobs_lock:
        _mapping_jobs[job_id] = {
            "status": "running",
            "progress": 0,
            "stage": "Uploading files",
            "error": None,
            "result": None,
            "started_at": time.time(),
            "eta_seconds": None,
        }

    legacy_fname = legacyFile.filename or ""
    oracle_fname = oracleFile.filename or ""
    logger.info(f"[Mapping] Submitting job {job_id[:8]}, legacy='{legacy_fname}', oracle='{oracle_fname}'")

    background_tasks.add_task(
        _run_mapping_job, job_id, legacy_bytes, oracle_bytes,
        legacy_fname, oracle_fname
    )

    return {"job_id": job_id}


@app.get("/api/excel/columns/mapping/status/{job_id}")
async def get_mapping_status(job_id: str):
    """
    Returns current progress of a mapping job.
    When status == 'complete', the result payload is included.
    """
    job = _mapping_job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Mapping job not found")

    resp = {
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "error": job.get("error"),
        "eta_seconds": job.get("eta_seconds"),
    }

    if job.get("status") == "complete" and job.get("result"):
        resp["result"] = job["result"]
        # Clean up the job after delivering result
        with _mapping_jobs_lock:
            _mapping_jobs.pop(job_id, None)

    return resp


# --- OPTIMIZED VALIDATION LOGIC STARTS HERE ---

# ═══════════════════════════════════════════════════════════════════════════
# POLARS-NATIVE HIGH-PERFORMANCE ENGINE  (10M+ row optimization)
# ═══════════════════════════════════════════════════════════════════════════

def _polars_read_file(file_path: str, sheet_name=None):
    """Read CSV/Excel into Polars LazyFrame. Avoids pandas entirely.
    For CSV: uses scan_csv (lazy, memory-mapped, multi-threaded).
    For Excel: uses calamine (Rust, 5-10x faster than openpyxl).
    """
    import polars as pl
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        return pl.scan_csv(
            file_path, infer_schema_length=0,
            try_parse_dates=False, null_values=[""]
        )

    # ── Excel handling ──
    sheet_id_param = None
    sheet_name_param = None

    if sheet_name is None:
        sheet_id_param = 1          # Polars is 1-indexed
    elif isinstance(sheet_name, int):
        sheet_id_param = max(sheet_name, 1)
    elif isinstance(sheet_name, str):
        stripped = sheet_name.strip()
        if not stripped:
            sheet_id_param = 1
        else:
            try:
                idx = int(stripped)
                sheet_id_param = max(idx + 1, 1) if idx == 0 else idx
            except ValueError:
                sheet_name_param = stripped

    df = None
    for engine in ("calamine", "xlsx2csv"):
        try:
            kw = {"engine": engine}
            if sheet_id_param is not None:
                kw["sheet_id"] = sheet_id_param
            elif sheet_name_param is not None:
                kw["sheet_name"] = sheet_name_param
            df = pl.read_excel(file_path, **kw)
            break
        except Exception:
            continue

    if df is None:
        sp = 0
        if sheet_name_param:
            sp = sheet_name_param
        elif sheet_id_param:
            sp = max(sheet_id_param - 1, 0)
        pdf = pd.read_excel(file_path, sheet_name=sp, dtype=str, engine="openpyxl")
        df = pl.from_pandas(pdf)

    df = df.cast({c: pl.Utf8 for c in df.columns})
    renames = {c: c.strip() for c in df.columns if c != c.strip()}
    if renames:
        df = df.rename(renames)
    return df.lazy()


_COMMON_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
]


def _detect_date_fmt(values, formats=_COMMON_DATE_FORMATS):
    """Sample values to auto-detect date format. Returns format string or None."""
    vals = [str(v).strip() for v in values[:30]
            if v is not None and str(v).strip() not in ("", "nan", "None", "NaN", "NaT")]
    if not vals:
        return None
    for fmt in formats:
        ok = 0
        for v in vals[:15]:
            try:
                datetime.strptime(v, fmt)
                ok += 1
            except Exception:
                pass
        if ok >= max(len(vals[:15]) * 0.6, 1):
            return fmt
    return None


def _pl_is_date_like_column(df, col_name, sample_size=50):
    """Check if a Polars column likely contains date values by sampling."""
    import polars as pl
    if col_name not in df.columns:
        return False
    sample = (df[col_name].cast(pl.Utf8).fill_null("")
              .head(sample_size)
              .to_list())
    # Filter non-empty, non-null values
    vals = [v.strip() for v in sample if v.strip() not in ('', 'nan', 'None', 'NaN', 'NaT')]
    if not vals:
        return False
    parsed = 0
    for val in vals:
        # Skip pure numbers without date separators
        try:
            float(val)
            if not any(sep in val for sep in ['-', '/', '.']):
                continue
        except ValueError:
            pass
        if not any(sep in val for sep in ['-', '/', '.', 'T']):
            continue
        try:
            from dateutil import parser as du_parser
            dt = du_parser.parse(val, fuzzy=False)
            if 1900 <= dt.year <= 2100:
                parsed += 1
        except Exception:
            pass
    return parsed >= max(len(vals) * 0.6, 1)


def _pl_apply_date_normalization(df, date_cols, all_cols, auto_detect=False, compare_cols=None):
    """Apply date normalization on an eager Polars DataFrame.
    Auto-detects format per column via sampling, then applies single-format parse.
    If auto_detect=True, also scans compare_cols for date-like columns.
    """
    import polars as pl

    # Auto-detect date columns if requested
    actual_date_cols = set(date_cols) if date_cols else set()
    if auto_detect and compare_cols:
        for col in compare_cols:
            if col not in actual_date_cols and col in df.columns:
                if _pl_is_date_like_column(df, col):
                    actual_date_cols.add(col)
                    logger.info(f"  Auto-detected date column (Polars): {col}")

    for col in actual_date_cols:
        if col not in all_cols or col not in df.columns:
            continue
        sample = df[col].cast(pl.Utf8).fill_null("").head(50).drop_nulls().to_list()
        # Filter out empty/sentinel values
        sample = [s.strip() for s in sample if s.strip() not in ('', 'nan', 'None', 'NaN', 'NaT')]
        fmt = _detect_date_fmt(sample)
        if fmt:
            try:
                if "H" in fmt or "M" in fmt:
                    df = df.with_columns(
                        pl.col(col).cast(pl.Utf8).fill_null("")
                        .str.strptime(pl.Datetime, fmt, strict=False)
                        .dt.strftime("%Y/%m/%d").fill_null("").alias(col)
                    )
                else:
                    df = df.with_columns(
                        pl.col(col).cast(pl.Utf8).fill_null("")
                        .str.strptime(pl.Date, fmt, strict=False)
                        .dt.strftime("%Y/%m/%d").fill_null("").alias(col)
                    )
            except Exception:
                # Fallback: try pandas-based parsing for this column
                try:
                    col_pandas = df[col].cast(pl.Utf8).fill_null("").to_pandas()
                    normalized = _smart_parse_dates(col_pandas)
                    df = df.with_columns(pl.Series(col, normalized.values).cast(pl.Utf8))
                except Exception:
                    pass
        else:
            # No format detected by strptime — try dateutil-based parsing
            try:
                col_pandas = df[col].cast(pl.Utf8).fill_null("").to_pandas()
                if _is_date_like_column(col_pandas):
                    normalized = _smart_parse_dates(col_pandas)
                    df = df.with_columns(pl.Series(col, normalized.values).cast(pl.Utf8))
            except Exception:
                pass
    return df


def _pl_detect_numeric_cols(df_l, df_o, cols_to_compare):
    """Detect numeric columns using Polars-native sampling. Zero pandas."""
    import polars as pl
    numeric_columns = set()
    sentinel = ["", "nan", "None", "NaN"]
    for col in cols_to_compare:
        try:
            sample = pl.concat([
                df_l.select(pl.col(col).cast(pl.Utf8)).head(2500),
                df_o.select(pl.col(col).cast(pl.Utf8)).head(2500),
            ])
            non_empty = sample.filter(~pl.col(col).is_in(sentinel))
            if len(non_empty) == 0:
                continue
            cleaned = non_empty.with_columns(
                pl.col(col).str.replace_all("[%,]", "")
                .cast(pl.Float64, strict=False).alias("_ntest")
            )
            num_count = cleaned.select(pl.col("_ntest").is_not_null().sum()).item()
            total = len(non_empty)
            has_dash = non_empty.select(
                pl.col(col).str.contains(r"\-").mean()
            ).item() or 0.0
            if (num_count / total) >= 0.8 and has_dash < 0.2:
                numeric_columns.add(col)
        except Exception:
            continue
    return numeric_columns


def _pl_clean_str_expr(col_name, case_sensitive=True):
    """Polars expression: clean string for comparison."""
    import polars as pl
    expr = (
        pl.col(col_name).cast(pl.Utf8).fill_null("")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
        .str.replace_all(",", "")
        .str.replace_all(r"\.0+$", "")
        .str.replace_all("(?i)^nan$", "")
        .str.replace_all("(?i)^none$", "")
        .fill_null("")
    )
    if not case_sensitive:
        expr = expr.str.to_lowercase()
    return expr


def _pl_clean_num_expr(col_name):
    """Polars expression: clean & cast to Float64 for numeric comparison."""
    import polars as pl
    return (
        pl.col(col_name).cast(pl.Utf8).fill_null("")
        .str.replace_all("%", "")
        .str.replace_all(",", "")
        .str.strip_chars()
        .str.replace_all("^$", "NaN")
        .cast(pl.Float64, strict=False)
        .round(4)
    )

def _polars_write_source_target_csv(joined, leg_only, orc_only, cols_to_compare, csv_path, internal_key):
    """Write full source/target data directly from Polars to CSV. Zero pandas.
    Column order: all PS (_S) columns first, then all OC (_T) columns, then Record Status."""
    import polars as pl
    # All PS columns first, then all OC columns (not interleaved)
    s_exprs = [pl.col(col).cast(pl.Utf8).fill_null("").alias(f"{col}_S") for col in cols_to_compare]
    t_exprs = [pl.col(f"{col}_T").cast(pl.Utf8).fill_null("").alias(f"{col}_T") for col in cols_to_compare]
    matched = joined.select(s_exprs + t_exprs + [pl.lit("MATCHED").alias("Record Status")])
    parts = [matched]

    if len(leg_only) > 0:
        l_s = [
            (pl.col(col).cast(pl.Utf8).fill_null("") if col in leg_only.columns else pl.lit("")).alias(f"{col}_S")
            for col in cols_to_compare
        ]
        l_t = [pl.lit("").alias(f"{col}_T") for col in cols_to_compare]
        parts.append(leg_only.select(l_s + l_t + [pl.lit("MISSING_IN_TARGET").alias("Record Status")]))

    if len(orc_only) > 0:
        o_s = [pl.lit("").alias(f"{col}_S") for col in cols_to_compare]
        o_t = [
            (pl.col(col).cast(pl.Utf8).fill_null("") if col in orc_only.columns else pl.lit("")).alias(f"{col}_T")
            for col in cols_to_compare
        ]
        parts.append(orc_only.select(o_s + o_t + [pl.lit("MISSING_IN_SOURCE").alias("Record Status")]))

    full = pl.concat(parts)
    full.write_csv(csv_path)
    return len(full)


def _is_date_like_column(series: pd.Series, sample_size: int = 50) -> bool:
    """
    Heuristic: check if a column likely contains date values by sampling.
    Returns True if >= 60% of non-empty sampled values parse as dates.
    """
    non_empty = series.dropna().astype(str).str.strip()
    non_empty = non_empty[~non_empty.isin(['', 'nan', 'None', 'NaN', 'NaT'])]
    if len(non_empty) == 0:
        return False
    sample = non_empty.head(sample_size).tolist()
    parsed = 0
    for val in sample:
        # Skip pure numbers (could be IDs, amounts etc.)
        try:
            float(val)
            # If it's a pure number with no date separators, skip
            if not any(sep in val for sep in ['-', '/', '.']):
                continue
        except ValueError:
            pass
        # Must contain date-like separators
        if not any(sep in val for sep in ['-', '/', '.', 'T']):
            continue
        try:
            from dateutil import parser as du_parser
            dt = du_parser.parse(val, fuzzy=False)
            if 1900 <= dt.year <= 2100:
                parsed += 1
        except Exception:
            pass
    return parsed >= max(len(sample) * 0.6, 1)


def _smart_parse_dates(series: pd.Series) -> pd.Series:
    """
    Parse a date column trying multiple strategies:
    1. pd.to_datetime default (handles YYYY-MM-DD, ISO, etc.)
    2. pd.to_datetime with dayfirst=True (handles DD-MM-YYYY, DD/MM/YYYY)
    3. dateutil.parser as final fallback for remaining unparsed values
    Returns series formatted as YYYY/MM/DD strings.
    """
    original = series.copy()
    str_vals = original.astype(str).str.strip()
    str_vals = str_vals.replace({'nan': '', 'None': '', 'NaN': '', 'NaT': ''})

    # Track which values are non-empty
    non_empty_mask = str_vals != ''
    result = pd.Series('', index=series.index)

    if non_empty_mask.sum() == 0:
        return result

    # Strategy 1: Try default pd.to_datetime (handles YYYY-MM-DD, ISO)
    parsed1 = pd.to_datetime(str_vals[non_empty_mask], errors='coerce')
    success1 = parsed1.notna()
    result.loc[success1[success1].index] = parsed1[success1].dt.strftime('%Y/%m/%d')

    # Strategy 2: For remaining unparsed, try dayfirst=True (DD-MM-YYYY)
    remaining = non_empty_mask & ~success1.reindex(series.index, fill_value=False)
    if remaining.sum() > 0:
        parsed2 = pd.to_datetime(str_vals[remaining], errors='coerce', dayfirst=True)
        success2 = parsed2.notna()
        result.loc[success2[success2].index] = parsed2[success2].dt.strftime('%Y/%m/%d')
        remaining = remaining & ~success2.reindex(series.index, fill_value=False)

    # Strategy 3: dateutil.parser for any still remaining
    if remaining.sum() > 0:
        from dateutil import parser as du_parser
        for idx in remaining[remaining].index:
            try:
                dt = du_parser.parse(str(str_vals.loc[idx]), dayfirst=True, fuzzy=True)
                result.loc[idx] = dt.strftime('%Y/%m/%d')
            except Exception:
                result.loc[idx] = str_vals.loc[idx]  # Keep original if unparseable

    return result


def fast_normalize_dates(df: pd.DataFrame, explicit_cols: Set[str]) -> pd.DataFrame:
    """
    Vectorized date normalization with smart multi-format parsing.
    Handles DD-MM-YYYY, MM-DD-YYYY, YYYY-MM-DD, and other formats.
    """
    # 1. Identify date columns (Explicit + Auto-detected)
    target_cols = [col for col in df.columns if col in explicit_cols or pd.api.types.is_datetime64_any_dtype(df[col])]

    for col in target_cols:
        df[col] = _smart_parse_dates(df[col])

    return df

def fast_generate_key(df: pd.DataFrame, columns: List[str]) -> pd.Series:
    """
    Vectorized key generation. 
    Replaces slow .agg('|'.join, axis=1) with vectorized string addition.
    """
    if not columns:
        return pd.Series([""] * len(df), index=df.index)
    res = df[columns[0]].astype(str).fillna("")
    for col in columns[1:]:
        res = res + "|" + df[col].astype(str).fillna("")
        
    return res



MAX_COLUMNS_PER_SHEET = 450

def enforce_sheet_column_limit(df: pd.DataFrame, sheet_name: str):
    col_count = df.shape[1]
    if col_count > MAX_COLUMNS_PER_SHEET:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Sheet '{sheet_name}' exceeds column limit. "
                f"Found {col_count} columns, maximum allowed is {MAX_COLUMNS_PER_SHEET}. "
                f"Please reduce mappings or included columns."
            )
        )

EXCEL_MAX_ROWS = 1_048_000 
def write_df_excel_paginated(
    writer,
    df: pd.DataFrame,
    base_sheet_name: str,
    max_rows: int = EXCEL_MAX_ROWS
):
    if len(df) <= max_rows:
        df.to_excel(writer, index=False, sheet_name=base_sheet_name)
        return [base_sheet_name]

    sheet_names = []
    for idx, start in enumerate(range(0, len(df), max_rows), start=1):
        sheet_name = f"{base_sheet_name}_{idx}"
        df.iloc[start:start + max_rows].to_excel(
            writer,
            index=False,
            sheet_name=sheet_name
        )
        sheet_names.append(sheet_name)

    return sheet_names


@app.post("/api/excel/post_validation/validate")
async def post_validation_excel(
    background_tasks: BackgroundTasks,
    legacyFile: UploadFile = File(...),
    oracleFile: UploadFile = File(...),
    customerName: str = Form(...),
    instanceName: str = Form(...),
    mappings: str = Form(...),
    keyColumns: str = Form(...),
    includedColumns: str = Form(default="[]"),
    dateColumns: str = Form(default="[]"),
    timestampColumns: str = Form(default="[]"),
    dateColumnstarget: str = Form(default="[]"),
    timestampColumnstarget: str = Form(default="[]"),
    legacySheet: str = Form(default=None),
    oracleSheet: str = Form(default=None),
    includeSourceTargetFiles: bool = Form(default=False),
    sourceLabel: str = Form(default="Source"),
    targetLabel: str = Form(default="Target"),
    caseSensitive: bool = Form(default=True)
):
    """
    OPTIMIZED Post-validation endpoint with FAST STYLING.
    Fixes: 
    1. Comment columns styled Orange with Borders.
    2. ROBUST String comparison (ignores 100 vs 100.0 differences).
    3. Consistent Excel Engine usage.
    4. PRE-NORMALIZES Key Columns to ensure correct row merging across systems.
    5. IMPROVED NUMERIC DETECTION for sparse columns (prevents false positive string mismatches).
    """
    logger.info("Starting ULTRA-OPTIMIZED validation (Polars-native pipeline)...")
    start_time = time.time()
    src_label = (sourceLabel or "Source").strip() or "Source"
    tgt_label = (targetLabel or "Target").strip() or "Target"
    case_sensitive = caseSensitive

    temp_dir = tempfile.mkdtemp()
    main_output_path = os.path.join(temp_dir, "PostValidation_Main.xlsx")
    source_target_csv_path = os.path.join(temp_dir, "SourceTarget_Data.csv")

    INTERNAL_KEY = "_derived_key"

    try:
        # --- [1. Parse Inputs] ---
        mappings_dict: Dict[str, str] = json.loads(mappings)
        included_cols_list: List[str] = json.loads(includedColumns)
        key_cols_list: List[str] = json.loads(keyColumns)
        
        # --- [1.1 Build Configuration DataFrame (New Tab Logic)] ---
        # Reconstructs the UI table state based on the inputs received
        config_rows = []
        
        # Combine date lists for easy lookup
        legacy_date_list = json.loads(dateColumns) + json.loads(timestampColumns)
        target_date_list = json.loads(dateColumnstarget) + json.loads(timestampColumnstarget)
        legacy_date_set = set(legacy_date_list)
        target_date_set = set(target_date_list)
        
        for source_col, target_col in mappings_dict.items():
            is_key = source_col in key_cols_list
            # Check if either source or target is marked as date
            is_date = (source_col in legacy_date_set) or (target_col in target_date_set)
            is_included = source_col in included_cols_list
            
            config_rows.append({
                f"{src_label} Column": source_col,
                f"{tgt_label} Column": target_col,
                "Is Key?": "Yes" if is_key else "No",
                "Is Date?": "Yes" if is_date else "No",
                "Validate": "Yes", # Implicitly Yes since it is in the mappings dict
                "Include in Report": "Yes" if is_included else "No"
            })
        
        config_df = pd.DataFrame(config_rows)
        # Enforce column limits on this new DF
        if len(config_df.columns) > 0:
             enforce_sheet_column_limit(config_df, "Configuration")

        legacy_date_cols = set(json.loads(dateColumns) + json.loads(timestampColumns))
        target_date_cols = set(json.loads(dateColumnstarget) + json.loads(timestampColumnstarget))

        if not mappings_dict: raise ValueError("Mappings is empty")
        if not key_cols_list: raise ValueError("Key columns list is empty")

        # --- [2. Read Files — Polars Native Engine (5-10x faster)] ---
        import polars as pl
        import gc
        t_io = time.time()
        legacy_path = os.path.join(temp_dir, f"src_{legacyFile.filename}")
        oracle_path = os.path.join(temp_dir, f"tgt_{oracleFile.filename}")
        legacy_sheet_param = legacySheet if legacySheet and legacySheet.strip() else None
        oracle_sheet_param = oracleSheet if oracleSheet and oracleSheet.strip() else None

        # Stream uploads to disk (8MB chunks — memory efficient)
        for upload, dest in [(legacyFile, legacy_path), (oracleFile, oracle_path)]:
            with open(dest, "wb") as f:
                while True:
                    chunk = await upload.read(8 * 1024 * 1024)
                    if not chunk: break
                    f.write(chunk)

        # Polars native read (multi-threaded, zero-copy)
        logger.info(f"Reading files with Polars native... Legacy Sheet: {legacySheet}, Oracle Sheet: {oracleSheet}")
        _lf_legacy = _polars_read_file(legacy_path, legacy_sheet_param)
        _lf_oracle = _polars_read_file(oracle_path, oracle_sheet_param)
        legacy_df = _lf_legacy.collect()
        oracle_df = _lf_oracle.collect()
        del _lf_legacy, _lf_oracle; gc.collect()
        legacy_row_count = len(legacy_df)
        oracle_row_count = len(oracle_df)
        logger.info(f"Files read in {time.time() - t_io:.2f}s — Legacy: {legacy_row_count:,}, Oracle: {oracle_row_count:,} rows")

        # --- [2.1] Align Oracle columns to Legacy column space (case-insensitive) ---
        oracle_to_legacy_map = {v: k for k, v in mappings_dict.items()}
        # Build case-insensitive lookup for oracle rename
        oracle_to_legacy_lower = {v.strip().lower(): k for k, v in mappings_dict.items()}

        cols_to_rename = {}
        for col in oracle_df.columns:
            if col in oracle_to_legacy_map:
                cols_to_rename[col] = oracle_to_legacy_map[col]
            elif col.strip().lower() in oracle_to_legacy_lower:
                cols_to_rename[col] = oracle_to_legacy_lower[col.strip().lower()]

        oracle_renamed = oracle_df.rename(cols_to_rename) if cols_to_rename else oracle_df
        del oracle_df

        # Also normalise legacy column names to match mapping keys (case-insensitive)
        legacy_mapped_lower = {k.strip().lower(): k for k in mappings_dict.keys()}
        legacy_cols_rename = {}
        for col in legacy_df.columns:
            lk = col.strip().lower()
            if lk in legacy_mapped_lower and col != legacy_mapped_lower[lk]:
                legacy_cols_rename[col] = legacy_mapped_lower[lk]
        if legacy_cols_rename:
            legacy_df = legacy_df.rename(legacy_cols_rename)

        # Resolve key_cols_list against actual oracle columns (case-insensitive)
        oracle_col_lower = {c.strip().lower(): c for c in oracle_renamed.columns}
        legacy_col_lower = {c.strip().lower(): c for c in legacy_df.columns}
        key_cols_list = [
            oracle_col_lower.get(k.strip().lower(), k) for k in key_cols_list
        ]
        # Rebuild mappings_dict to match actual column names
        resolved_mappings = {}
        for l_col, o_col in mappings_dict.items():
            actual_l = legacy_col_lower.get(l_col.strip().lower(), l_col)
            actual_o = oracle_col_lower.get(l_col.strip().lower(), l_col)
            resolved_mappings[actual_l] = o_col
        mappings_dict = resolved_mappings

        missing_keys = [k for k in key_cols_list if k not in oracle_renamed.columns]
        if missing_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Key columns missing in Oracle after rename: {missing_keys}"
            )

        if len(legacy_df.columns) > 450 or len(oracle_renamed.columns) > 450:
             raise HTTPException(status_code=400, detail="File has too many columns. Max allowed is 450.")

        # Validate columns existence
        missing = []
        for l, o in mappings_dict.items():
            if l not in legacy_df.columns: missing.append(f"{src_label} column '{l}' not found in sheet '{legacy_sheet_param}'")
            if l not in oracle_renamed.columns: missing.append(f"{tgt_label} column '{o}' not found in sheet '{oracle_sheet_param}'")
        
        if missing:
            raise HTTPException(status_code=400, detail={"errors": missing})

        # Resolve included_cols_list and date column sets to match actual names
        included_cols_list = [
            oracle_col_lower.get(c.strip().lower(), legacy_col_lower.get(c.strip().lower(), c))
            for c in included_cols_list
        ]
        legacy_date_cols = {
            legacy_col_lower.get(c.strip().lower(), c) for c in legacy_date_cols
        }
        oracle_to_legacy_lower_map = {v.strip().lower(): k for k, v in
                                       {k: v for k, v in zip(mappings_dict.keys(), [oracle_to_legacy_map.get(k, k) for k in mappings_dict.values()])}.items()}
        target_date_cols_resolved = set()
        for c in target_date_cols:
            # target dates are in oracle-original space; map to legacy then resolve
            mapped = oracle_to_legacy_map.get(c, c)
            actual = oracle_col_lower.get(mapped.strip().lower(), legacy_col_lower.get(mapped.strip().lower(), mapped))
            target_date_cols_resolved.add(actual)
        target_date_cols = target_date_cols_resolved

        # --- [POLARS-NATIVE] Normalize Key Columns ---
        logger.info("Normalizing Key Columns (Polars)...")
        key_norm_exprs = [
            pl.col(col).cast(pl.Utf8).fill_null("")
            .str.strip_chars()
            .str.replace_all(r"\.0+$", "")
            .str.replace_all("^nan$", "")
            .str.replace_all("^None$", "")
            .str.replace_all("^NaN$", "")
            .alias(col)
            for col in key_cols_list
            if col in legacy_df.columns
        ]
        if key_norm_exprs:
            legacy_df = legacy_df.with_columns(key_norm_exprs)
            oracle_renamed = oracle_renamed.with_columns(key_norm_exprs)

        # --- [POLARS-NATIVE] Date Normalization ---
        logger.info("Normalizing dates (Polars) with auto-detection...")
        # Pre-compute comparison columns for auto-detect
        _pre_cols_to_compare = list(mappings_dict.keys())
        _pre_cols_to_compare = [c for c in _pre_cols_to_compare if c in legacy_df.columns and c in oracle_renamed.columns]
        legacy_df = _pl_apply_date_normalization(legacy_df, legacy_date_cols, list(legacy_df.columns),
                                                  auto_detect=True, compare_cols=_pre_cols_to_compare)
        oracle_renamed = _pl_apply_date_normalization(oracle_renamed, target_date_cols, list(oracle_renamed.columns),
                                                       auto_detect=True, compare_cols=_pre_cols_to_compare)

        # --- [POLARS-NATIVE] Key Generation ---
        logger.info("Generating keys (Polars)...")
        key_expr = pl.col(key_cols_list[0]).cast(pl.Utf8).fill_null("")
        for c in key_cols_list[1:]:
            key_expr = key_expr + pl.lit("|") + pl.col(c).cast(pl.Utf8).fill_null("")
        legacy_df = legacy_df.with_columns(key_expr.alias(INTERNAL_KEY))
        oracle_renamed = oracle_renamed.with_columns(key_expr.alias(INTERNAL_KEY))

        # --- [4.5 Positional row-numbering for duplicate keys] ---
        # When multiple rows share the same composite key (e.g. GL journal lines),
        # add a row number within each key group so row-1 of key "A" in legacy
        # matches row-1 of key "A" in oracle.  Prevents cross-join explosion.
        _leg_dup_count = legacy_df.select(pl.col(INTERNAL_KEY).is_duplicated().sum()).item()
        _orc_dup_count = oracle_renamed.select(pl.col(INTERNAL_KEY).is_duplicated().sum()).item()
        if _leg_dup_count > 0 or _orc_dup_count > 0:
            logger.info(f"Duplicate keys found (Legacy: {_leg_dup_count:,}, Oracle: {_orc_dup_count:,}) — adding positional row numbers")
            legacy_df = legacy_df.with_columns(
                pl.int_range(pl.len()).over(INTERNAL_KEY).cast(pl.Utf8).alias("_rn")
            )
            oracle_renamed = oracle_renamed.with_columns(
                pl.int_range(pl.len()).over(INTERNAL_KEY).cast(pl.Utf8).alias("_rn")
            )
            legacy_df = legacy_df.with_columns(
                (pl.col(INTERNAL_KEY) + pl.lit("|_rn=") + pl.col("_rn")).alias(INTERNAL_KEY)
            ).drop("_rn")
            oracle_renamed = oracle_renamed.with_columns(
                (pl.col(INTERNAL_KEY) + pl.lit("|_rn=") + pl.col("_rn")).alias(INTERNAL_KEY)
            ).drop("_rn")
            logger.info(f"Positional keys assigned — Legacy: {len(legacy_df):,}, Oracle: {len(oracle_renamed):,}")

        # --- [5. Comparison Logic — POLARS MULTI-THREADED ENGINE] ---
        logger.info("Comparing data (Polars multi-threaded engine)...")
        t_compare = time.time()

        cols_to_compare = list(mappings_dict.keys())
        cols_to_compare = [c for c in cols_to_compare if c in legacy_df.columns and c in oracle_renamed.columns]

        # Already Polars DataFrames — select only needed columns for comparison
        pl_legacy = legacy_df.select([INTERNAL_KEY] + cols_to_compare)
        pl_oracle = oracle_renamed.select([INTERNAL_KEY] + cols_to_compare)

        # Free pandas DataFrames for comparison columns (keep originals for missing records)
        gc.collect()

        # --- Detect numeric columns (Polars-native, no pandas) ---
        numeric_columns = _pl_detect_numeric_cols(pl_legacy, pl_oracle, cols_to_compare)
        logger.info(f"Numeric columns detected: {numeric_columns}")

        # --- INNER JOIN on _derived_key (Polars hash join — O(n)) ---
        joined = pl_legacy.join(pl_oracle, on=INTERNAL_KEY, suffix="_T", how="inner")
        del pl_oracle; gc.collect()
        logger.info(f"Polars join complete: {len(joined):,} matched rows in {time.time() - t_compare:.2f}s")

        # --- Build clean + diff expressions for ALL columns at once (multi-threaded) ---
        diff_exprs = []
        for col in cols_to_compare:
            l_col = col
            o_col = f"{col}_T"
            if col in numeric_columns:
                diff_exprs.append(_pl_clean_num_expr(l_col).alias(f"__ln_{col}"))
                diff_exprs.append(_pl_clean_num_expr(o_col).alias(f"__on_{col}"))
            else:
                diff_exprs.append(_pl_clean_str_expr(l_col, case_sensitive).alias(f"__ls_{col}"))
                diff_exprs.append(_pl_clean_str_expr(o_col, case_sensitive).alias(f"__os_{col}"))

        # Materialize all cleaned columns in ONE pass (multi-threaded)
        joined_clean = joined.with_columns(diff_exprs)

        # --- Build boolean diff mask columns ---
        mask_exprs = []
        for col in cols_to_compare:
            if col in numeric_columns:
                ln = f"__ln_{col}"
                on = f"__on_{col}"
                mask_exprs.append(
                    (
                        (pl.col(ln).is_not_null() & pl.col(on).is_not_null()
                         & ((pl.col(ln) - pl.col(on)).abs() > 0.0001))
                        | (pl.col(ln).is_null() ^ pl.col(on).is_null())
                    ).alias(f"__diff_{col}")
                )
            else:
                ls = f"__ls_{col}"
                os_ = f"__os_{col}"
                mask_exprs.append(
                    (pl.col(ls).fill_null("") != pl.col(os_).fill_null("")).alias(f"__diff_{col}")
                )

        joined_diffs = joined_clean.with_columns(mask_exprs)

        # --- [6. Extract Discrepancies — Polars unpivot] ---
        diff_col_names = [f"__diff_{col}" for col in cols_to_compare]
        # Check if ANY diffs exist (fast boolean reduce)
        has_any_diff = joined_diffs.select(diff_col_names).sum().row(0)
        total_diff_count = sum(has_any_diff)

        if total_diff_count > 0:
            # Extract discrepancies by building union of per-column filters
            disc_parts = []
            for col in cols_to_compare:
                diff_flag = f"__diff_{col}"
                col_label = f"{col} - {mappings_dict.get(col, col)}"
                filtered = joined_diffs.filter(pl.col(diff_flag))
                if len(filtered) == 0:
                    continue
                part = filtered.select([
                    pl.col(INTERNAL_KEY),
                    pl.lit(col_label).alias("Column Name"),
                    pl.col(col).cast(pl.Utf8).fill_null("").alias(f"{src_label} Value"),
                    pl.col(f"{col}_T").cast(pl.Utf8).fill_null("").alias(f"{tgt_label} Value"),
                ])
                disc_parts.append(part)

            if disc_parts:
                discrepancies_pl = pl.concat(disc_parts)
            else:
                discrepancies_pl = pl.DataFrame({
                    INTERNAL_KEY: [], "Column Name": [],
                    f"{src_label} Value": [], f"{tgt_label} Value": []
                })

            # Add context columns (key + included) — Polars native
            context_cols = list(dict.fromkeys(key_cols_list + included_cols_list))
            valid_context_cols = [c for c in context_cols if c in legacy_df.columns]
            if valid_context_cols:
                ctx_pl = legacy_df.select([INTERNAL_KEY] + valid_context_cols).unique(subset=[INTERNAL_KEY])
                discrepancies_pl = discrepancies_pl.join(ctx_pl, on=INTERNAL_KEY, how="left")
                del ctx_pl

            # Convert to pandas for Excel output
            validation_df = discrepancies_pl.drop(INTERNAL_KEY).to_pandas()

            # Order columns
            final_report_cols = key_cols_list + [c for c in included_cols_list if c not in key_cols_list] + ["Column Name", f"{src_label} Value", f"{tgt_label} Value"]
            final_report_cols = [c for c in final_report_cols if c in validation_df.columns]
            validation_df = validation_df[final_report_cols]
        else:
            validation_df = pd.DataFrame([{"Status": "All mapped columns matched perfectly"}])
        
        # --- SORT Data Discrepancies BEFORE pagination ---
        if "Column Name" in validation_df.columns and not validation_df.empty:
            sort_cols = ["Column Name"] + [
                c for c in key_cols_list if c in validation_df.columns
            ]
            validation_df = validation_df.sort_values(
                by=sort_cols,
                kind="mergesort"
            ).reset_index(drop=True)

        # --- [NEW] Add Comment Columns to Discrepancies ---
        comment_cols = ["Mythics Comments", "Oracle Comments", "ParkView Comments"]
        for col in comment_cols:
            validation_df[col] = ""

        # --- [6.1] Discrepancy Count Per Column (for Summary) ---
        column_discrepancy_counts = []
        logger.info("Calculating discrepancy counts per column...")
        if "Status" not in validation_df.columns and not validation_df.empty:
            col_counts = (
                validation_df["Column Name"]
                .value_counts()
                .sort_values(ascending=False)
            )
            for col_name, count in col_counts.items():
                column_discrepancy_counts.append(["", col_name, int(count), "", "", ""])

        # --- [7. Missing Records — Polars ANTI JOIN (O(n) hash join)] ---
        t_miss = time.time()
        pl_matched_keys = pl.DataFrame({INTERNAL_KEY: joined_diffs[INTERNAL_KEY]})

        # Anti-join directly on Polars DataFrames (zero conversion overhead)
        legacy_only_pl = legacy_df.join(pl_matched_keys, on=INTERNAL_KEY, how="anti").drop(INTERNAL_KEY)
        oracle_only_pl = oracle_renamed.join(pl_matched_keys, on=INTERNAL_KEY, how="anti").drop(INTERNAL_KEY)
        del pl_matched_keys

        # Convert small missing-record sets to pandas for Excel output
        legacy_only_df = legacy_only_pl.to_pandas()
        oracle_only_df = oracle_only_pl.to_pandas()
        logger.info(f"Missing records: {len(legacy_only_df):,} in Oracle, {len(oracle_only_df):,} in PS — {time.time() - t_miss:.2f}s")

        # --- [NEW] Add Comment Columns to Missing Record DFs ---
        for col in comment_cols:
            legacy_only_df[col] = ""
            oracle_only_df[col] = ""

        # --- [8. Full Data Report — CSV directly from Polars (no pandas overhead)] ---
        t_csv = time.time()

        # Convert small missing-record DFs to Polars for the CSV writer
        _leg_only_pl = legacy_only_pl
        _orc_only_pl = oracle_only_pl

        _polars_write_source_target_csv(
            joined_diffs, _leg_only_pl, _orc_only_pl,
            cols_to_compare, source_target_csv_path, INTERNAL_KEY
        )
        logger.info(f"Full data CSV written in {time.time() - t_csv:.2f}s")

        # Free large Polars DataFrames (row counts already saved)
        del joined, joined_diffs, joined_clean, pl_legacy
        del _leg_only_pl, _orc_only_pl
        del legacy_df, oracle_renamed
        gc.collect()

        # --- [9. Generate Summary] ---
        total_discrepancies = len(validation_df) if "Status" not in validation_df.columns else 0
        count_missing_ps = len(legacy_only_df)
        count_missing_oc = len(oracle_only_df)
        grand_total = count_missing_ps + count_missing_oc + total_discrepancies

        summary_data = [
            ["", "Comparison Statistics", "", "", "", ""],
            ["", f"{src_label} File Name", legacyFile.filename, "", "", ""],
            ["", f"{src_label} Records Count", legacy_row_count, "", "", ""],
            ["", f"{tgt_label} File Name", oracleFile.filename, "", "", ""],
            ["", f"{tgt_label} Records Count", oracle_row_count, "", "", ""],
            ["", "Validation DateTime", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "", "", ""],
            ["", "", "", "", "", ""],

            ["", "Missing Records Summary", "", "Mythics Comments", "Oracle Comments", "ParkView Comments"],
            ["", f"Records Missing in {src_label}", count_missing_oc, "", "", ""],
            ["", f"Records Missing in {tgt_label}", count_missing_ps, "", "", ""],
            ["", "Total Missing Records", count_missing_ps + count_missing_oc, "", "", ""],
            ["", "", "", "", "", ""],

            ["", "Data Discrepancies Summary", "", "Mythics Comments", "Oracle Comments", "ParkView Comments"],
            *column_discrepancy_counts,
            ["", "Total Data Discrepancies", total_discrepancies, "", "", ""],
            ["", "", "", "", "", ""],

            ["", "Total Validation Issues", grand_total, "", "", ""]
        ]

        summary_df = pd.DataFrame(summary_data)

        # --- [10. Write to Excel with Perfect Styling] ---


        logger.info("Writing and Styling Excel...")
        

        def style_configuration_sheet(workbook, sheet_name="Configuration"):
            if sheet_name not in workbook.sheetnames:
                return

            ws = workbook[sheet_name]
            ws.freeze_panes = "A2"

            # Header styling
            for cell in ws[1]:
                cell.fill = fill_green
                cell.font = font_white
                cell.alignment = align_center
                cell.border = border_thin

            # Body styling
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.border = border_thin

                    # Center align Yes / No / Validate columns
                    if str(cell.value).strip().lower() in {"yes", "no"}:
                        cell.alignment = align_center

            # Auto column width
            for col in ws.iter_cols(max_row=ws.max_row):
                max_length = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                ws.column_dimensions[col_letter].width = min(max(max_length + 2, 12), 45)

        sheet_missing_ps = f"Missing in {src_label}"
        sheet_missing_oc = f"Missing in {tgt_label}"
        sheet_discrepancies = "Data Discrepancies"
        sheet_full_data = f"{src_label} - {tgt_label} Data"

        enforce_sheet_column_limit(summary_df, "Summary")
        enforce_sheet_column_limit(validation_df, "Data Discrepancies")
        enforce_sheet_column_limit(legacy_only_df, f"Missing in {tgt_label}")
        enforce_sheet_column_limit(oracle_only_df, f"Missing in {src_label}")

        # Define Styling Functions (same as before but included for completeness)
        font_white = Font(name="Calibri", size=9, color="FFFFFF", bold=True)
        font_black = Font(name="Calibri", size=9, color="000000", bold=True)
        font_bold_black = Font(name="Calibri", size=9, bold=True)
        fill_header_ps = PatternFill("solid", fgColor="1F497D")
        fill_header_oc = PatternFill("solid", fgColor="31869B")
        fill_header_err = PatternFill("solid", fgColor="C0504D")
        fill_green = PatternFill("solid", fgColor="00B050")
        fill_grey = PatternFill("solid", fgColor="D9D9D9")
        fill_orange = PatternFill("solid", fgColor="FF9900")
        border_thin = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        align_center = Alignment(horizontal="center", vertical="center")

        def style_full_data_header_only(ws, num_comparison_cols):
            border_ps_last  = Border(left=Side(style="thin"), top=Side(style="thin"), bottom=Side(style="thin"), right=Side(style="medium"))
            border_oc_first = Border(left=Side(style="medium"), top=Side(style="thin"), bottom=Side(style="thin"), right=Side(style="thin"))
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = font_white
                cell.alignment = align_center
                if cell.column <= num_comparison_cols:
                    cell.fill = fill_header_ps
                    cell.border = border_ps_last if cell.column == num_comparison_cols else border_thin
                else:
                    cell.fill = fill_header_oc
                    cell.border = border_oc_first if cell.column == num_comparison_cols + 1 else border_thin
            for col in ws.iter_cols(max_row=50):
                max_length = 0
                col_letter = get_column_letter(col[0].column)
                if col[0].value: max_length = len(str(col[0].value))
                for cell in col[1:]:
                    if cell.value: max_length = max(max_length, len(str(cell.value)))
                ws.column_dimensions[col_letter].width = min(max((max_length + 2) * 1.2, 10), 60)

        def style_sheet_header(workbook, sheet_name, fill_color):
            if sheet_name in workbook.sheetnames:
                ws = workbook[sheet_name]
                ws.freeze_panes = "A2"
                comment_col_indices = []
                for cell in ws[1]:
                    cell.fill = fill_color
                    cell.font = font_white
                    cell.alignment = align_center
                    cell.border = border_thin
                    if cell.value in comment_cols:
                        cell.fill = fill_orange
                        cell.font = font_black
                        comment_col_indices.append(cell.column)
                # Auto-width: only sample first 50 rows for speed
                for col in ws.iter_cols(max_row=min(50, ws.max_row)):
                    max_length = 0
                    col_letter = get_column_letter(col[0].column)
                    if col[0].value: max_length = len(str(col[0].value))
                    for cell in col[1:]:
                        if cell.value: max_length = max(max_length, len(str(cell.value)))
                    ws.column_dimensions[col_letter].width = min(max((max_length + 2) * 1.2, 10), 60)
                # Comment column borders — cap at 5000 rows to avoid O(n) styling
                if comment_col_indices:
                    border_limit = min(ws.max_row, 5000)
                    for col_idx in comment_col_indices:
                        for col_cells in ws.iter_cols(min_col=col_idx, max_col=col_idx, min_row=2, max_row=border_limit):
                            for cell in col_cells:
                                cell.border = border_thin

        # Generate Files — optimized: full data as CSV, styled report as xlsx
        with pd.ExcelWriter(main_output_path, engine="openpyxl") as main_writer:
            summary_df.to_excel(main_writer, index=False, header=False, sheet_name="Summary")
            config_df.to_excel(main_writer, index=False, sheet_name="Configuration")
            oracle_only_df.to_excel(main_writer, index=False, sheet_name=sheet_missing_ps)
            legacy_only_df.to_excel(main_writer, index=False, sheet_name=sheet_missing_oc)

            write_df_excel_paginated(main_writer, validation_df, sheet_discrepancies)
            main_workbook = main_writer.book
            if includeSourceTargetFiles:
                # Load from CSV (capped at 1M rows for Excel)
                try:
                    _st_df = pd.read_csv(source_target_csv_path, dtype=str, nrows=EXCEL_MAX_ROWS)
                    write_df_excel_paginated(main_writer, _st_df, sheet_full_data)
                    del _st_df
                except Exception as _csv_err:
                    logger.warning(f"Could not include source/target data: {_csv_err}")

            # Apply Styles
            style_sheet_header(main_workbook, sheet_missing_ps, fill_header_ps)
            style_sheet_header(main_workbook, sheet_missing_oc, fill_header_oc)
            for sheet in main_workbook.sheetnames:
                if sheet.startswith(sheet_discrepancies):
                    style_sheet_header(main_workbook, sheet, fill_header_err)
            style_configuration_sheet(main_workbook, "Configuration")
            main_workbook["Configuration"].sheet_state = "hidden"
            if includeSourceTargetFiles:
                for sheet_name in main_workbook.sheetnames:
                    if sheet_name.startswith(sheet_full_data):
                        style_full_data_header_only(main_workbook[sheet_name], len(cols_to_compare))

            # Summary Styling
            ws_sum = main_workbook["Summary"]
            ws_sum.sheet_view.showGridLines = False
            ws_sum.column_dimensions['A'].width = 2
            ws_sum.column_dimensions['B'].width = 45
            for c_char in ['C', 'D', 'E', 'F']: ws_sum.column_dimensions[c_char].width = 25
            
            for row in ws_sum.iter_rows(min_row=1, max_row=ws_sum.max_row):
                if len(row) < 3: continue
                cell_b = row[1]
                if not cell_b.value: continue
                cell_b.border = border_thin
                row[2].border = border_thin
                comment_cells = [ws_sum.cell(row=cell_b.row, column=c) for c in [4, 5, 6]]
                
                if cell_b.value in ["Missing Records Summary", "Data Discrepancies Summary"]:
                    ws_sum.merge_cells(start_row=cell_b.row, start_column=2, end_row=cell_b.row, end_column=3)
                    cell_b.fill = fill_green
                    cell_b.font = font_white
                    cell_b.alignment = align_center
                    ws_sum.row_dimensions[cell_b.row].height = 20
                    for c in comment_cells:
                        c.fill = fill_orange
                        c.font = font_black
                        c.alignment = align_center
                        c.border = border_thin
                elif "Total" in str(cell_b.value) or "Comparison Statistics" in str(cell_b.value):
                    if "Comparison Statistics" in str(cell_b.value):
                         ws_sum.merge_cells(start_row=cell_b.row, start_column=2, end_row=cell_b.row, end_column=3)
                         cell_b.alignment = align_center
                         ws_sum.row_dimensions[cell_b.row].height = 20
                         cell_b.fill = fill_green
                         cell_b.font = font_white
                    else:
                        cell_b.fill = fill_grey
                        row[2].fill = fill_grey
                        cell_b.font = font_bold_black
                        row[2].font = font_bold_black
                        row[2].alignment = align_center
                else:
                    cell_b.fill = fill_green
                    cell_b.font = font_white
                    row[2].alignment = align_center
                    for c in comment_cells: c.border = border_thin

        logger.info(f"Process completed in {time.time() - start_time:.2f} seconds.")

        def _clean(path):
            try: shutil.rmtree(path, ignore_errors=True)
            except: pass

        background_tasks.add_task(_clean, temp_dir)
        report_ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        return FileResponse(
            main_output_path,
            filename=f"MythicsValidationResults_{report_ts}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Processing Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================================
# LARGE-SCALE POST-VALIDATION ENDPOINT (Polars Engine — supports 10M+ rows)
# =====================================================================================
# Async job-based architecture:
#   1. POST /validate_large  → saves files, returns { job_id } immediately
#   2. GET  /status/{job_id} → returns { progress, stage, status, error? }
#   3. GET  /download/{job_id} → streams the result .xlsx once status == "complete"
# =====================================================================================


# ── In-memory job tracker ────────────────────────────────────────────────
import threading as _threading

_validation_jobs: Dict[str, Dict[str, Any]] = {}
_validation_jobs_lock = _threading.Lock()

def _job_update(job_id: str, **kwargs):
    """Thread-safe update of a job's progress dict."""
    with _validation_jobs_lock:
        if job_id in _validation_jobs:
            _validation_jobs[job_id].update(kwargs)
            job = _validation_jobs[job_id]
            job["eta_seconds"] = _compute_smooth_eta(job)

def _job_get(job_id: str) -> Optional[Dict]:
    with _validation_jobs_lock:
        return _validation_jobs.get(job_id, {}).copy()


# ── Stale job cleanup (runs on every new job submission) ─────────────
_STALE_JOB_MAX_AGE = 60 * 60  # 1 hour

def _cleanup_stale_jobs():
    """Remove completed/failed jobs older than 1 hour to prevent memory leaks."""
    now = time.time()
    stale_ids = []
    with _validation_jobs_lock:
        for jid, job in _validation_jobs.items():
            if job.get("status") in ("complete", "failed"):
                age = now - job.get("started_at", now)
                if age > _STALE_JOB_MAX_AGE:
                    stale_ids.append(jid)
        for jid in stale_ids:
            job = _validation_jobs.pop(jid, {})
            td = job.get("temp_dir")
            if td and os.path.exists(td):
                shutil.rmtree(td, ignore_errors=True)
    if stale_ids:
        logger.info(f"Cleaned up {len(stale_ids)} stale validation job(s)")

@app.post("/api/excel/post_validation/validate_large")
async def post_validation_large_scale(
    background_tasks: BackgroundTasks,
    legacyFile: UploadFile = File(...),
    oracleFile: UploadFile = File(...),
    customerName: str = Form(...),
    instanceName: str = Form(...),
    mappings: str = Form(...),
    keyColumns: str = Form(...),
    includedColumns: str = Form(default="[]"),
    dateColumns: str = Form(default="[]"),
    timestampColumns: str = Form(default="[]"),
    dateColumnstarget: str = Form(default="[]"),
    timestampColumnstarget: str = Form(default="[]"),
    legacySheet: str = Form(default=None),
    oracleSheet: str = Form(default=None),
    includeSourceTargetFiles: bool = Form(default=False),
    sourceLabel: str = Form(default="Source"),
    targetLabel: str = Form(default="Target"),
    caseSensitive: bool = Form(default=True)
):
    """
    Accepts files & config, returns { job_id } immediately.
    Processing runs in a background thread with live progress tracking.
    Poll GET /api/excel/post_validation/status/{job_id} for progress.
    """
    if not POLARS_AVAILABLE:
        raise HTTPException(status_code=501, detail="Polars is not installed. Run: pip install polars")

    # Housekeeping: clean up stale jobs from previous runs
    _cleanup_stale_jobs()

    # ── Generate job ID & save files to disk ────────────────────────────
    job_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()

    legacy_path = os.path.join(temp_dir, f"src_{legacyFile.filename}")
    oracle_path = os.path.join(temp_dir, f"tgt_{oracleFile.filename}")

    for upload, dest in [(legacyFile, legacy_path), (oracleFile, oracle_path)]:
        with open(dest, "wb") as fh:
            while True:
                chunk = await upload.read(8 * 1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)

    # ── Register job ────────────────────────────────────────────────────
    with _validation_jobs_lock:
        _validation_jobs[job_id] = {
            "status": "running",
            "progress": 0,
            "stage": "Uploading files",
            "error": None,
            "temp_dir": temp_dir,
            "zip_path": None,
            "zip_filename": None,  # legacy key names (now stores .xlsx path)
            "legacy_filename": legacyFile.filename,
            "oracle_filename": oracleFile.filename,
            "started_at": time.time(),
        }

    # ── Capture all form values (strings) for the background thread ────
    job_params = {
        "legacy_path": legacy_path,
        "oracle_path": oracle_path,
        "legacy_filename": legacyFile.filename,
        "oracle_filename": oracleFile.filename,
        "mappings": mappings,
        "keyColumns": keyColumns,
        "includedColumns": includedColumns,
        "dateColumns": dateColumns,
        "timestampColumns": timestampColumns,
        "dateColumnstarget": dateColumnstarget,
        "timestampColumnstarget": timestampColumnstarget,
        "legacySheet": legacySheet,
        "oracleSheet": oracleSheet,
        "includeSourceTargetFiles": includeSourceTargetFiles,
        "sourceLabel": sourceLabel,
        "targetLabel": targetLabel,
        "caseSensitive": caseSensitive,
        "temp_dir": temp_dir,
    }

    # Launch processing in a background thread (does NOT block event loop)
    _threading.Thread(
        target=_run_validation_job,
        args=(job_id, job_params),
        daemon=True,
        name=f"validation-{job_id[:8]}",
    ).start()

    return {"job_id": job_id}

# --- Data Transformation for the Source Code 
@app.post("/api/excel/post_validation/data_mapping")
async def post_validation_data_mapping(
    legacyFile: UploadFile = File(...),
    oracleFile: UploadFile = File(...),
    mappingFile: UploadFile = File(None),
    customerName: str = Form(...),
    instanceName: str = Form(...),
    legacySheet: str = Form(default=None),
    oracleSheet: str = Form(default=None),
):
    """Simple synchronous mapping endpoint used by the frontend.
    Returns column lists and a suggested mapping dict. If a mappingFile (JSON)
    is provided the server will return it as the suggested mapping.
    """
    try:
        legacy_bytes = await legacyFile.read()
        oracle_bytes = await oracleFile.read()

        # Use helper to parse into pandas DataFrame
        try:
            df_legacy = _read_file_bytes(legacy_bytes, legacyFile.filename)
            df_oracle = _read_file_bytes(oracle_bytes, oracleFile.filename)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded files: {e}")

        legacy_cols = [str(c) for c in list(df_legacy.columns)]
        oracle_cols = [str(c) for c in list(df_oracle.columns)]

        suggested = {}
        # If mappingFile provided and is Excel/CSV, try to read mapping pairs from it
        if mappingFile is not None:
            try:
                mf_bytes = await mappingFile.read()
                # Parse using existing helper which reads csv/xlsx
                df_map = _read_file_bytes(mf_bytes, mappingFile.filename)
                # Normalize column names
                cols_lc = {c.lower(): c for c in df_map.columns}
                # Common header name candidates for source and target
                src_cands = ["source", "legacy", "from", "src", "source_column", "sourcecol"]
                tgt_cands = ["target", "oracle", "to", "tgt", "target_column", "targetcol"]

                src_col = None
                tgt_col = None
                for cand in src_cands:
                    if cand in cols_lc:
                        src_col = cols_lc[cand]
                        break
                for cand in tgt_cands:
                    if cand in cols_lc:
                        tgt_col = cols_lc[cand]
                        break

                # If headers not found, but there are at least two columns, use first two
                if src_col is None or tgt_col is None:
                    if len(df_map.columns) >= 2:
                        src_col = src_col or df_map.columns[0]
                        tgt_col = tgt_col or df_map.columns[1]

                if src_col and tgt_col:
                    for _, row in df_map[[src_col, tgt_col]].dropna(how='all').iterrows():
                        s = str(row[src_col]).strip()
                        t = str(row[tgt_col]).strip()
                        if s and t:
                            suggested[s] = t
            except Exception:
                # ignore parse errors and fall back to heuristic
                suggested = {}

        # If no mapping file was provided, use Gemini AI for smart column mapping
        date_columns = []
        if not suggested:
            ai_result = get_smart_mapping_from_gemini(legacy_cols, oracle_cols)
            suggested = ai_result.get("mapping", {})
            date_columns = ai_result.get("date_columns", [])

        # Ensure mapping entries only apply to the uploaded source (legacy) columns.
        legacy_lower_map = {c.lower(): c for c in legacy_cols}
        filtered = {}
        for s, t in suggested.items():
            if s in legacy_cols:
                filtered[s] = t
            else:
                sl = s.lower()
                if sl in legacy_lower_map:
                    filtered[legacy_lower_map[sl]] = t
                # otherwise ignore mappings that don't reference the source file

        return {
            "legacy_columns": legacy_cols,
            "oracle_columns": oracle_cols,
            "suggested_mapping": filtered,
            "date_columns": date_columns,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Value-Level Transformation Endpoint
@app.post("/api/excel/post_validation/transform")
async def post_validation_transform(
    sourceFile:  UploadFile = File(...),
    mappingFile: UploadFile = File(...),
):
    """
    Apply value-level transformations to sourceFile using rules defined in mappingFile.

    Mapping file column detection (case-insensitive, positional fallback):
      3+ cols → column_name | old_value | new_value  (targeted per source column)
      2  cols → old_value   | new_value              (applied to ALL source columns)

    Returns a transformed .xlsx blob.  Transform statistics are reported in
    response headers so the frontend can display them without parsing the file.
    """
    try:
        source_bytes  = await sourceFile.read()
        mapping_bytes = await mappingFile.read()

        # ── Parse source file ──────────────────────────────────────────────
        try:
            df = _read_file_bytes(source_bytes, sourceFile.filename)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read source file: {e}")

        # ── Parse mapping/rules file ───────────────────────────────────────
        try:
            df_map = _read_file_bytes(mapping_bytes, mappingFile.filename)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read mapping file: {e}")

        # ── Detect which columns represent column_name / old_value / new_value ──
        col_name_cands  = ["column_name", "column", "col", "field", "attribute"]
        old_value_cands = ["old_value", "from", "old", "original", "source_value"]
        new_value_cands = ["new_value", "to", "new", "replacement", "target_value"]

        cols_lc = {str(c).strip().lower(): str(c) for c in df_map.columns}

        def _pick(candidates):
            for cand in candidates:
                if cand in cols_lc:
                    return cols_lc[cand]
            return None

        num_map_cols  = len(df_map.columns)
        col_name_col  = None
        old_value_col = None
        new_value_col = None
        apply_all_cols = False   # True → 2-col mode, replace in every source column

        if num_map_cols >= 3:
            col_name_col  = _pick(col_name_cands)
            old_value_col = _pick(old_value_cands)
            new_value_col = _pick(new_value_cands)
            # Positional fallback when headers are not recognized
            if not col_name_col or not old_value_col or not new_value_col:
                col_name_col  = df_map.columns[0]
                old_value_col = df_map.columns[1]
                new_value_col = df_map.columns[2]
        elif num_map_cols == 2:
            apply_all_cols = True
            old_value_col  = df_map.columns[0]
            new_value_col  = df_map.columns[1]
        else:
            raise HTTPException(
                status_code=400,
                detail="Mapping file must have at least 2 columns (old_value, new_value)."
            )

        # ── Build rules list ───────────────────────────────────────────────
        rules = []  # each rule: { col: str|None, old: str, new: str }
        for _, row in df_map.dropna(subset=[old_value_col, new_value_col], how="any").iterrows():
            old_val = str(row[old_value_col]).strip()
            new_val = str(row[new_value_col]).strip()
            if not old_val:
                continue
            if apply_all_cols:
                target_col = None
            else:
                raw_col = row[col_name_col]
                target_col = str(raw_col).strip() if pd.notna(raw_col) else None
                if not target_col or target_col.lower() == "nan":
                    target_col = None
            rules.append({"col": target_col, "old": old_val, "new": new_val})

        # ── Apply transformations ──────────────────────────────────────────
        df_work      = df.copy().astype(object)   # object dtype avoids coercion errors
        df_cols_set  = set(df_work.columns.astype(str))

        rules_applied  = 0
        cells_changed  = 0
        cols_changed   = set()
        total_rules    = len(rules)

        for rule in rules:
            old_val    = rule["old"]
            new_val    = rule["new"]
            rule_col   = rule["col"]
            rule_hit   = False

            target_cols = (
                [rule_col] if rule_col and rule_col in df_cols_set
                else ([] if rule_col else list(df_work.columns))
            )

            for col in target_cols:
                series    = df_work[col].astype(str)
                mask      = series == old_val
                hit_count = int(mask.sum())
                if hit_count > 0:
                    df_work.loc[mask, col] = new_val
                    cells_changed += hit_count
                    cols_changed.add(str(col))
                    rule_hit = True

            if rule_hit:
                rules_applied += 1

        # ── Serialize result to xlsx bytes ─────────────────────────────────
        out_buf = BytesIO()
        df_work.to_excel(out_buf, index=False)
        out_buf.seek(0)

        stem         = Path(sourceFile.filename).stem if sourceFile.filename else "source"
        out_filename = f"{stem}_transformed.xlsx"

        return StreamingResponse(
            out_buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition":          f'attachment; filename="{out_filename}"',
                "X-Transform-Rules-Applied":    str(rules_applied),
                "X-Transform-Cells-Changed":    str(cells_changed),
                "X-Transform-Columns-Changed":  str(len(cols_changed)),
                "X-Transform-Total-Rules":      str(total_rules),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in post_validation_transform")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/excel/post_validation/status/{job_id}")
async def get_validation_status(job_id: str):
    """
    Returns current progress of a validation job.
    Response: { status, progress, stage, error? }
      - status: "running" | "complete" | "failed"
      - progress: 0–100
      - stage: human-readable description of current step
    """
    job = _job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "error": job.get("error"),
        "eta_seconds": job.get("eta_seconds"),
    }



@app.get("/api/excel/post_validation/download/{job_id}")
async def download_validation_result(job_id: str, background_tasks: BackgroundTasks):
    """
    Downloads the validation result (.xlsx) once the job is complete.
    After download, schedules cleanup of temp files.
    """
    job = _job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "running":
        raise HTTPException(status_code=202, detail="Job still running")
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=job.get("error", "Unknown error"))

    zip_path = job.get("zip_path")
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=410, detail="Result file no longer available")

    temp_dir = job.get("temp_dir")

    def _cleanup(path, jid):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass
        with _validation_jobs_lock:
            _validation_jobs.pop(jid, None)

    background_tasks.add_task(_cleanup, temp_dir, job_id)

    # Detect file type from extension to support both .xlsx and .zip outputs
    dl_filename = job.get("zip_filename", "MythicsValidationResults.xlsx")
    if zip_path.endswith(".zip"):
        media = "application/zip"
    else:
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(
        zip_path,
        filename=dl_filename,
        media_type=media,
    )



# ── Background Processing Function ──────────────────────────────────────
def _run_validation_job(job_id: str, p: dict):
    """
    Runs the full Polars validation pipeline in a background thread.
    Updates _validation_jobs[job_id] with progress at each stage.
    """
    # Enable Rust backtraces for diagnosing Polars native crashes
    os.environ.setdefault("RUST_BACKTRACE", "1")
    os.environ.setdefault("POLARS_VERBOSE", "1")

    temp_dir = p["temp_dir"]
    src_label = (p.get("sourceLabel") or "Source").strip() or "Source"
    tgt_label = (p.get("targetLabel") or "Target").strip() or "Target"
    case_sensitive = p.get("caseSensitive", True)
    main_output_path = os.path.join(temp_dir, "PostValidation_Main.xlsx")
    full_data_csv_path = os.path.join(temp_dir, "PeopleSoft_OracleCloud_FullData.csv")
    discrepancies_csv_path = os.path.join(temp_dir, "DataDiscrepancies_Full.csv")
    missing_oracle_csv_path = os.path.join(temp_dir, "Missing_In_Oracle.csv")
    missing_ps_csv_path = os.path.join(temp_dir, "Missing_In_PeopleSoft.csv")
    INTERNAL_KEY = "_derived_key"

    try:
        start_time = time.time()
        import gc
        import polars as pl

        # ── Stage 1: Parse Inputs (2%) ──────────────────────────────────
        _job_update(job_id, progress=2, stage="Parsing configuration")
        logger.info(f"[{job_id[:8]}] Parsing inputs...")

        mappings_dict: Dict[str, str] = json.loads(p["mappings"])
        included_cols_list: List[str] = json.loads(p["includedColumns"])
        key_cols_list: List[str] = json.loads(p["keyColumns"])
        legacy_date_set = set(json.loads(p["dateColumns"]) + json.loads(p["timestampColumns"]))
        target_date_set = set(json.loads(p["dateColumnstarget"]) + json.loads(p["timestampColumnstarget"]))

        if not mappings_dict:
            raise ValueError("Mappings dictionary is empty")
        if not key_cols_list:
            raise ValueError("Key columns list is empty")

        config_rows = []
        for source_col, target_col in mappings_dict.items():
            config_rows.append({
                f"{src_label} Column": source_col,
                f"{tgt_label} Column": target_col,
                "Is Key?": "Yes" if source_col in key_cols_list else "No",
                "Is Date?": "Yes" if (source_col in legacy_date_set or target_col in target_date_set) else "No",
                "Validate": "Yes",
                "Include in Report": "Yes" if source_col in included_cols_list else "No",
            })
        config_df = pd.DataFrame(config_rows)

        # ── Stage 2: Load Files with calamine (5–20%) ──────────────────
        _job_update(job_id, progress=5, stage="Reading source file (calamine)")
        logger.info(f"[{job_id[:8]}] Loading files with calamine...")

        _job_update(job_id, progress=8, stage="Reading source file (Polars native)")
        _lf_legacy = _polars_read_file(p["legacy_path"], p["legacySheet"])
        legacy_df = _lf_legacy.collect().to_pandas()
        del _lf_legacy
        legacy_df.columns = legacy_df.columns.astype(str).str.strip()

        _job_update(job_id, progress=15, stage="Reading target file (Polars native)")
        _lf_oracle = _polars_read_file(p["oracle_path"], p["oracleSheet"])
        oracle_df = _lf_oracle.collect().to_pandas()
        del _lf_oracle
        oracle_df.columns = oracle_df.columns.astype(str).str.strip()

        legacy_count = len(legacy_df)
        oracle_count = len(oracle_df)
        _job_update(job_id, progress=20,
                    stage=f"Files loaded — {legacy_count:,} + {oracle_count:,} rows")
        logger.info(f"[{job_id[:8]}] Loaded — Legacy: {legacy_count:,}, Oracle: {oracle_count:,}")

        # ── Stage 3: Column Alignment & Validation (25%) ────────────────
        _job_update(job_id, progress=22, stage="Aligning column names")

        oracle_to_legacy = {v: k for k, v in mappings_dict.items()}
        oracle_to_legacy_lower = {v.strip().lower(): k for k, v in mappings_dict.items()}

        cols_to_rename = {}
        for col in oracle_df.columns:
            if col in oracle_to_legacy:
                cols_to_rename[col] = oracle_to_legacy[col]
            elif col.strip().lower() in oracle_to_legacy_lower:
                cols_to_rename[col] = oracle_to_legacy_lower[col.strip().lower()]

        oracle_renamed = oracle_df.rename(columns=cols_to_rename)
        del oracle_df
        gc.collect()

        # Normalise legacy column names to match mapping keys (case-insensitive)
        legacy_mapped_lower = {k.strip().lower(): k for k in mappings_dict.keys()}
        legacy_cols_rename = {}
        for col in legacy_df.columns:
            lk = col.strip().lower()
            if lk in legacy_mapped_lower and col != legacy_mapped_lower[lk]:
                legacy_cols_rename[col] = legacy_mapped_lower[lk]
        if legacy_cols_rename:
            legacy_df = legacy_df.rename(columns=legacy_cols_rename)

        legacy_cols = list(legacy_df.columns)
        oracle_cols = list(oracle_renamed.columns)

        # Resolve key_cols_list and mappings_dict against actual column names
        oracle_col_lower = {c.strip().lower(): c for c in oracle_cols}
        legacy_col_lower = {c.strip().lower(): c for c in legacy_cols}
        key_cols_list = [
            oracle_col_lower.get(k.strip().lower(), k) for k in key_cols_list
        ]
        resolved_mappings = {}
        for l_col, o_col in mappings_dict.items():
            actual_legacy = legacy_col_lower.get(l_col.strip().lower(), l_col)
            actual_oracle = oracle_col_lower.get(l_col.strip().lower(), l_col)
            common_name = actual_oracle if actual_oracle in oracle_cols else actual_legacy
            resolved_mappings[common_name] = o_col
        mappings_dict = resolved_mappings

        # Resolve included_cols_list and date sets
        included_cols_list = [
            oracle_col_lower.get(c.strip().lower(), legacy_col_lower.get(c.strip().lower(), c))
            for c in included_cols_list
        ]
        legacy_date_set = {
            legacy_col_lower.get(c.strip().lower(), c) for c in legacy_date_set
        }
        target_date_set_resolved = set()
        for c in target_date_set:
            mapped = oracle_to_legacy.get(c, c)
            actual = oracle_col_lower.get(mapped.strip().lower(), mapped)
            target_date_set_resolved.add(actual)
        target_date_set = target_date_set_resolved

        missing_keys = [k for k in key_cols_list if k not in oracle_renamed.columns]
        if missing_keys:
            raise ValueError(f"Key columns missing in Oracle after rename: {missing_keys}")

        missing = []
        for l_col, o_col in mappings_dict.items():
            if l_col not in legacy_df.columns:
                missing.append(f"{src_label} column '{l_col}' not found")
            if l_col not in oracle_renamed.columns:
                missing.append(f"{tgt_label} column '{o_col}' not found after rename")
        if missing:
            raise ValueError(f"Column errors: {'; '.join(missing)}")

        cols_to_compare = [k for k in mappings_dict if k in legacy_df.columns and k in oracle_renamed.columns]
        _job_update(job_id, progress=25, stage=f"Validating {len(cols_to_compare)} mapped columns")

        # ── Stage 4: Normalise keys & dates (28–35%) ──────────────────
        _job_update(job_id, progress=28, stage="Normalising keys & dates")

        def normalize_key_columns(df, key_cols):
            for col in key_cols:
                if col in df.columns:
                    df[col] = (
                        df[col].astype(str).str.strip()
                        .str.replace(r'\.0+$', '', regex=True)
                        .replace({'nan': '', 'None': '', 'NaN': ''})
                        .fillna('')
                    )
            return df

        legacy_df = normalize_key_columns(legacy_df, key_cols_list)
        oracle_renamed = normalize_key_columns(oracle_renamed, key_cols_list)

        legacy_date_cols_present = {c for c in legacy_date_set if c in legacy_df.columns}
        target_date_cols_mapped = set()
        for col in target_date_set:
            mapped = oracle_to_legacy.get(col, col)
            if mapped in oracle_renamed.columns:
                target_date_cols_mapped.add(mapped)

        # Auto-detect date columns from ALL comparison columns (catches unmarked dates)
        logger.info(f"[{job_id[:8]}] Auto-detecting date columns from {len(cols_to_compare)} comparison columns...")
        auto_detected_date_cols = set()
        for col in cols_to_compare:
            is_date_in_legacy = col in legacy_df.columns and _is_date_like_column(legacy_df[col])
            is_date_in_oracle = col in oracle_renamed.columns and _is_date_like_column(oracle_renamed[col])
            if is_date_in_legacy or is_date_in_oracle:
                auto_detected_date_cols.add(col)
        
        # Merge explicit + auto-detected
        all_legacy_date_cols = legacy_date_cols_present | auto_detected_date_cols
        all_oracle_date_cols = target_date_cols_mapped | auto_detected_date_cols
        
        if auto_detected_date_cols - legacy_date_cols_present:
            logger.info(f"[{job_id[:8]}] Auto-detected additional date columns: "
                        f"{auto_detected_date_cols - legacy_date_cols_present}")

        legacy_df = fast_normalize_dates(legacy_df, all_legacy_date_cols)
        oracle_renamed = fast_normalize_dates(oracle_renamed, all_oracle_date_cols)

        _job_update(job_id, progress=32, stage="Generating composite keys")
        legacy_df[INTERNAL_KEY] = fast_generate_key(legacy_df, key_cols_list)
        oracle_renamed[INTERNAL_KEY] = fast_generate_key(oracle_renamed, key_cols_list)

        _job_update(job_id, progress=35, stage="Keys generated — starting comparison")
        logger.info(f"[{job_id[:8]}] Normalisation complete")

        # ── Stage 5: Detect numeric columns (Polars-native sampling) ────
        _job_update(job_id, progress=37, stage="Detecting column data types")
        logger.info(f"[{job_id[:8]}] Converting to Polars for numeric detection...")
        _pl_l_detect = pl.from_pandas(legacy_df[[INTERNAL_KEY] + cols_to_compare])
        _pl_o_detect = pl.from_pandas(oracle_renamed[[INTERNAL_KEY] + cols_to_compare])
        numeric_cols = _pl_detect_numeric_cols(_pl_l_detect, _pl_o_detect, cols_to_compare)
        del _pl_l_detect, _pl_o_detect
        gc.collect()
        logger.info(f"[{job_id[:8]}] Numeric columns: {numeric_cols}")

        # ── Stage 5b: Key uniqueness — positional row numbering (prevents join explosion) ────
        _job_update(job_id, progress=38, stage="Handling duplicate keys")
        legacy_key_dupes = legacy_df[INTERNAL_KEY].duplicated().sum()
        oracle_key_dupes = oracle_renamed[INTERNAL_KEY].duplicated().sum()
        logger.info(f"[{job_id[:8]}] Key duplicates — Legacy: {legacy_key_dupes:,}, Oracle: {oracle_key_dupes:,}")

        # Instead of dropping duplicates (which loses data), add a positional
        # row-number within each key group so that row 1 of key "A" in legacy
        # matches row 1 of key "A" in oracle.  This keeps ALL rows and avoids
        # cross-join explosion (100×100 → 100 instead of 10 000).
        if legacy_key_dupes > 0 or oracle_key_dupes > 0:
            logger.info(f"[{job_id[:8]}] Adding positional row number within each key group")
            legacy_df["_rn"] = legacy_df.groupby(INTERNAL_KEY).cumcount().astype(str)
            oracle_renamed["_rn"] = oracle_renamed.groupby(INTERNAL_KEY).cumcount().astype(str)
            legacy_df[INTERNAL_KEY] = legacy_df[INTERNAL_KEY] + "|_rn=" + legacy_df["_rn"]
            oracle_renamed[INTERNAL_KEY] = oracle_renamed[INTERNAL_KEY] + "|_rn=" + oracle_renamed["_rn"]
            legacy_df.drop(columns=["_rn"], inplace=True)
            oracle_renamed.drop(columns=["_rn"], inplace=True)
            logger.info(f"[{job_id[:8]}] Positional keys assigned — Legacy: {len(legacy_df):,}, Oracle: {len(oracle_renamed):,}")
            gc.collect()

        # ── Stage 6: Polars comparison engine (40–60%) ────────────────
        _job_update(job_id, progress=40, stage="Joining source & target (Polars)")
        logger.info(f"[{job_id[:8]}] Converting legacy to Polars ({legacy_count:,} rows, {len(cols_to_compare)} cols)...")

        try:
            pl_legacy = pl.from_pandas(legacy_df[[INTERNAL_KEY] + cols_to_compare])
            logger.info(f"[{job_id[:8]}] Legacy converted to Polars OK")
        except Exception as conv_err:
            logger.error(f"[{job_id[:8]}] Failed converting legacy to Polars: {conv_err}")
            raise

        try:
            pl_oracle = pl.from_pandas(oracle_renamed[[INTERNAL_KEY] + cols_to_compare])
            logger.info(f"[{job_id[:8]}] Oracle converted to Polars OK")
        except Exception as conv_err:
            logger.error(f"[{job_id[:8]}] Failed converting oracle to Polars: {conv_err}")
            raise

        # Free pandas DataFrames references for the comparison columns early
        # (we still keep legacy_df and oracle_renamed for context columns/missing records later)
        gc.collect()

        logger.info(f"[{job_id[:8]}] Starting inner join on '{INTERNAL_KEY}'...")
        try:
            joined = pl_legacy.join(pl_oracle, on=INTERNAL_KEY, suffix="_T", how="inner")
        except Exception as join_err:
            logger.error(f"[{job_id[:8]}] Polars join failed: {join_err}")
            raise
        del pl_legacy, pl_oracle
        gc.collect()

        matched_count = len(joined)
        _job_update(job_id, progress=42,
                    stage=f"Joined {matched_count:,} matched rows — comparing")
        logger.info(f"[{job_id[:8]}] Polars join: {matched_count:,} matched rows")

        # Safety: abort if join exploded beyond expected size
        max_expected = max(legacy_count, oracle_count) * 3
        if matched_count > max_expected:
            logger.error(f"[{job_id[:8]}] JOIN EXPLOSION detected: {matched_count:,} rows "
                         f"(expected max ~{max_expected:,}). Likely non-unique keys.")
            raise ValueError(
                f"Join produced {matched_count:,} rows (source has {legacy_count:,}). "
                f"Key columns may not be unique. Please verify key column selection."
            )

        # Save matched keys for later anti-join (small memory footprint)
        matched_keys_series = joined[INTERNAL_KEY].clone()

        # Write full data CSV directly from Polars (avoids giant pandas intermediate later)
        # Column order: all PS (_S) first, then all OC (_T), then Record Status
        _job_update(job_id, progress=44, stage="Writing matched data to CSV")
        logger.info(f"[{job_id[:8]}] Writing full matched data CSV...")
        num_comparison_cols = len(cols_to_compare)
        full_select = (
            [pl.col(col).cast(pl.Utf8).fill_null("").alias(f"{col}_S") for col in cols_to_compare]
            + [pl.col(f"{col}_T").cast(pl.Utf8).fill_null("").alias(f"{col}_T") for col in cols_to_compare]
            + [pl.lit("MATCHED").alias("Record Status")]
        )
        joined.select(full_select).write_csv(full_data_csv_path)
        gc.collect()
        logger.info(f"[{job_id[:8]}] Matched full data written to CSV")

        # Build diff expressions — process in batches for memory safety
        _job_update(job_id, progress=46, stage="Cleaning data for comparison")
        logger.info(f"[{job_id[:8]}] Building cleaning expressions for {len(cols_to_compare)} columns...")

        # Process cleaning + diff in batches to limit peak memory
        BATCH_SIZE = 50  # columns per batch
        col_batches = [cols_to_compare[i:i+BATCH_SIZE] for i in range(0, len(cols_to_compare), BATCH_SIZE)]

        all_diff_results = {}  # col_name -> boolean Series
        for batch_idx, col_batch in enumerate(col_batches):
            logger.info(f"[{job_id[:8]}] Processing column batch {batch_idx+1}/{len(col_batches)} "
                        f"({len(col_batch)} columns)")

            diff_exprs = []
            for col in col_batch:
                l_col = col
                o_col = f"{col}_T"
                if col in numeric_cols:
                    diff_exprs.append(_pl_clean_num_expr(l_col).alias(f"__ln_{col}"))
                    diff_exprs.append(_pl_clean_num_expr(o_col).alias(f"__on_{col}"))
                else:
                    diff_exprs.append(_pl_clean_str_expr(l_col, case_sensitive).alias(f"__ls_{col}"))
                    diff_exprs.append(_pl_clean_str_expr(o_col, case_sensitive).alias(f"__os_{col}"))

            batch_clean = joined.select([pl.col(INTERNAL_KEY)] + [pl.col(c) for c in col_batch]
                                          + [pl.col(f"{c}_T") for c in col_batch]).with_columns(diff_exprs)

            # Compute diff masks for this batch
            for col in col_batch:
                if col in numeric_cols:
                    ln, on = f"__ln_{col}", f"__on_{col}"
                    diff_series = (
                        (batch_clean[ln].is_not_null() & batch_clean[on].is_not_null()
                         & ((batch_clean[ln] - batch_clean[on]).abs() > 0.0001))
                        | (batch_clean[ln].is_null() ^ batch_clean[on].is_null())
                    )
                else:
                    ls, os_ = f"__ls_{col}", f"__os_{col}"
                    diff_series = batch_clean[ls].fill_null("") != batch_clean[os_].fill_null("")
                all_diff_results[col] = diff_series.sum()  # Just count, not full series

            del batch_clean
            gc.collect()

        _job_update(job_id, progress=55, stage="Extracting discrepancies")
        logger.info(f"[{job_id[:8]}] Column diff counts computed")

        # ── Stage 7: Extract discrepancies (55–62%) ───────────────────
        # all_diff_results has col -> count of diffs (from batched processing)
        total_diff_count = sum(all_diff_results.values())
        cols_with_diffs = [col for col, cnt in all_diff_results.items() if cnt > 0]
        logger.info(f"[{job_id[:8]}] Total diff count: {total_diff_count:,}, "
                    f"columns with diffs: {len(cols_with_diffs)}")

        if total_diff_count > 0 and cols_with_diffs:
            disc_parts = []
            # Second pass: extract actual discrepancy rows only for columns with diffs
            for col_idx, col in enumerate(cols_with_diffs):
                col_label = f"{col} - {mappings_dict.get(col, col)}"
                l_col = col
                o_col = f"{col}_T"

                # Rebuild clean + diff for just this one column (memory-safe)
                if col in numeric_cols:
                    col_clean = joined.select([
                        pl.col(INTERNAL_KEY),
                        pl.col(l_col),
                        pl.col(o_col),
                        _pl_clean_num_expr(l_col).alias("__cl"),
                        _pl_clean_num_expr(o_col).alias("__co"),
                    ])
                    diff_mask = (
                        (col_clean["__cl"].is_not_null() & col_clean["__co"].is_not_null()
                         & ((col_clean["__cl"] - col_clean["__co"]).abs() > 0.0001))
                        | (col_clean["__cl"].is_null() ^ col_clean["__co"].is_null())
                    )
                else:
                    col_clean = joined.select([
                        pl.col(INTERNAL_KEY),
                        pl.col(l_col),
                        pl.col(o_col),
                        _pl_clean_str_expr(l_col, case_sensitive).alias("__cl"),
                        _pl_clean_str_expr(o_col, case_sensitive).alias("__co"),
                    ])
                    diff_mask = col_clean["__cl"].fill_null("") != col_clean["__co"].fill_null("")

                filtered = col_clean.filter(diff_mask)
                if len(filtered) > 0:
                    part = filtered.select([
                        pl.col(INTERNAL_KEY),
                        pl.lit(col_label).alias("Column Name"),
                        pl.col(l_col).cast(pl.Utf8).fill_null("").alias(f"{src_label} Value"),
                        pl.col(o_col).cast(pl.Utf8).fill_null("").alias(f"{tgt_label} Value"),
                    ])
                    disc_parts.append(part)
                del col_clean, filtered
                gc.collect()

            if disc_parts:
                discrepancies_pl = pl.concat(disc_parts)
                del disc_parts
            else:
                discrepancies_pl = pl.DataFrame({
                    INTERNAL_KEY: [], "Column Name": [],
                    f"{src_label} Value": [], f"{tgt_label} Value": []
                })

            # Add context columns
            context_cols = list(dict.fromkeys(key_cols_list + included_cols_list))
            valid_ctx = [c for c in context_cols if c in legacy_df.columns]
            if valid_ctx:
                ctx_pl = pl.from_pandas(
                    legacy_df[[INTERNAL_KEY] + valid_ctx].drop_duplicates(subset=INTERNAL_KEY)
                )
                discrepancies_pl = discrepancies_pl.join(ctx_pl, on=INTERNAL_KEY, how="left")

            total_discrepancies = len(discrepancies_pl)

            # CSV export for very large discrepancy sets
            if total_discrepancies > 1_000_000:
                discrepancies_pl.drop(INTERNAL_KEY).write_csv(discrepancies_csv_path)

            validation_df = discrepancies_pl.drop(INTERNAL_KEY).to_pandas()
            del discrepancies_pl
            gc.collect()

            # Order columns
            final_report_cols = key_cols_list + [c for c in included_cols_list if c not in key_cols_list] + ["Column Name", f"{src_label} Value", f"{tgt_label} Value"]
            final_report_cols = [c for c in final_report_cols if c in validation_df.columns]
            validation_df = validation_df[final_report_cols]
        else:
            total_discrepancies = 0
            validation_df = pd.DataFrame([{"Status": "All mapped columns matched perfectly"}])

        _job_update(job_id, progress=62,
                    stage=f"Found {total_discrepancies:,} discrepancies")
        logger.info(f"[{job_id[:8]}] Total discrepancies: {total_discrepancies:,}")

        # Sort discrepancies
        if "Column Name" in validation_df.columns and not validation_df.empty:
            sort_cols = ["Column Name"] + [c for c in key_cols_list if c in validation_df.columns]
            validation_df = validation_df.sort_values(by=sort_cols, kind="mergesort").reset_index(drop=True)

        comment_cols = ["Mythics Comments", "Oracle Comments", "ParkView Comments"]
        for col in comment_cols:
            validation_df[col] = ""

        # ── Stage 8: Discrepancy Counts ───────────────────────────────
        column_discrepancy_counts = []
        if "Status" not in validation_df.columns and not validation_df.empty:
            col_counts = validation_df["Column Name"].value_counts().sort_values(ascending=False)
            for col_name, count in col_counts.items():
                column_discrepancy_counts.append(["", col_name, int(count), "", "", ""])

        # ── Stage 9: Missing Records (Polars ANTI JOIN) ───────────────
        _job_update(job_id, progress=64, stage="Finding missing records")

        pl_legacy_keys = pl.from_pandas(legacy_df[[INTERNAL_KEY]])
        pl_oracle_keys = pl.from_pandas(oracle_renamed[[INTERNAL_KEY]])
        pl_matched_keys = pl.DataFrame({INTERNAL_KEY: matched_keys_series})

        legacy_missing_keys = pl_legacy_keys.join(pl_matched_keys, on=INTERNAL_KEY, how="anti")
        oracle_missing_keys = pl_oracle_keys.join(pl_matched_keys, on=INTERNAL_KEY, how="anti")

        legacy_missing_set = set(legacy_missing_keys[INTERNAL_KEY].to_list())
        oracle_missing_set = set(oracle_missing_keys[INTERNAL_KEY].to_list())

        legacy_only_df = legacy_df[legacy_df[INTERNAL_KEY].isin(legacy_missing_set)].copy()
        oracle_only_df = oracle_renamed[oracle_renamed[INTERNAL_KEY].isin(oracle_missing_set)].copy()

        if INTERNAL_KEY in legacy_only_df.columns:
            legacy_only_df.drop(columns=[INTERNAL_KEY], inplace=True)
        if INTERNAL_KEY in oracle_only_df.columns:
            oracle_only_df.drop(columns=[INTERNAL_KEY], inplace=True)

        count_missing_oracle = len(legacy_only_df)
        count_missing_ps = len(oracle_only_df)

        _job_update(job_id, progress=68,
                    stage=f"Missing: {count_missing_oracle:,} in {tgt_label}, {count_missing_ps:,} in {src_label}")

        # CSV export for large missing sets
        if count_missing_oracle > 1_000_000:
            legacy_only_df.to_csv(missing_oracle_csv_path, index=False)
        if count_missing_ps > 1_000_000:
            oracle_only_df.to_csv(missing_ps_csv_path, index=False)

        for col in comment_cols:
            legacy_only_df[col] = ""
            oracle_only_df[col] = ""

        # ── Stage 10: Full Data Report (78%) ──────────────────────────
        _job_update(job_id, progress=78, stage="Appending missing records to full data CSV")

        # CSV header order (matched data already written from Polars earlier)
        full_csv_header_cols = [f"{c}_S" for c in cols_to_compare] + [f"{c}_T" for c in cols_to_compare] + ["Record Status"]

        # Append missing-in-target rows to CSV
        if count_missing_oracle > 0:
            l_rename = {c: f"{c}_S" for c in cols_to_compare if c in legacy_only_df.columns}
            ps_missing_df = legacy_only_df.rename(columns=l_rename)
            for c in cols_to_compare:
                if f"{c}_S" not in ps_missing_df.columns:
                    ps_missing_df[f"{c}_S"] = ""
                ps_missing_df[f"{c}_T"] = ""
            ps_missing_df["Record Status"] = "MISSING_IN_TARGET"
            ps_missing_df = ps_missing_df.reindex(columns=full_csv_header_cols, fill_value="")
            ps_missing_df.to_csv(full_data_csv_path, mode='a', header=False, index=False)
            del ps_missing_df

        # Append missing-in-source rows to CSV
        if count_missing_ps > 0:
            o_rename = {c: f"{c}_T" for c in cols_to_compare if c in oracle_only_df.columns}
            oc_missing_csv_df = oracle_only_df.rename(columns=o_rename)
            for c in cols_to_compare:
                oc_missing_csv_df[f"{c}_S"] = ""
                if f"{c}_T" not in oc_missing_csv_df.columns:
                    oc_missing_csv_df[f"{c}_T"] = ""
            oc_missing_csv_df["Record Status"] = "MISSING_IN_SOURCE"
            oc_missing_csv_df = oc_missing_csv_df.reindex(columns=full_csv_header_cols, fill_value="")
            oc_missing_csv_df.to_csv(full_data_csv_path, mode='a', header=False, index=False)
            del oc_missing_csv_df

        include_src_tgt = p.get("includeSourceTargetFiles", False)

        # Lazy-load full data from CSV only when needed for Excel (with row cap)
        full_data_for_excel = None
        if include_src_tgt and os.path.exists(full_data_csv_path):
            try:
                full_data_for_excel = pd.read_csv(full_data_csv_path, dtype=str, nrows=EXCEL_MAX_ROWS)
            except Exception as csv_err:
                logger.warning(f"[{job_id[:8]}] Could not reload full data CSV for Excel: {csv_err}")

        # Free large Polars/pandas objects
        del joined, legacy_df, oracle_renamed
        del matched_keys_series
        gc.collect()
        logger.info(f"[{job_id[:8]}] Polars processing done in {time.time() - start_time:.2f}s")

        # ── Stage 13: Generate Summary (82%) ───────────────────────────
        _job_update(job_id, progress=82, stage="Generating summary statistics")

        grand_total = count_missing_oracle + count_missing_ps + total_discrepancies
        summary_data = [
            ["", "Comparison Statistics", "", "", "", ""],
            ["", f"{src_label} File Name", p["legacy_filename"], "", "", ""],
            ["", f"{src_label} Records Count", f"{legacy_count:,}", "", "", ""],
            ["", f"{tgt_label} File Name", p["oracle_filename"], "", "", ""],
            ["", f"{tgt_label} Records Count", f"{oracle_count:,}", "", "", ""],
            ["", "Validation DateTime", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "", "", ""],
            ["", "", "", "", "", ""],
            ["", "Missing Records Summary", "", "Mythics Comments", "Oracle Comments", "ParkView Comments"],
            ["", f"Records Missing in {src_label}", f"{count_missing_ps:,}", "", "", ""],
            ["", f"Records Missing in {tgt_label}", f"{count_missing_oracle:,}", "", "", ""],
            ["", "Total Missing Records", f"{count_missing_oracle + count_missing_ps:,}", "", "", ""],
            ["", "", "", "", "", ""],
            ["", "Data Discrepancies Summary", "", "Mythics Comments", "Oracle Comments", "ParkView Comments"],
            *column_discrepancy_counts,
            ["", "Total Data Discrepancies", f"{total_discrepancies:,}", "", "", ""],
            ["", "", "", "", "", ""],
            ["", "Total Validation Issues", f"{grand_total:,}", "", "", ""],
        ]
        summary_df = pd.DataFrame(summary_data)

        # ── Stage 14: Write Styled Excel (85–95%) ─────────────────────
        _job_update(job_id, progress=85, stage="Writing styled Excel report")

        font_white = Font(name="Calibri", size=9, color="FFFFFF", bold=True)
        font_black = Font(name="Calibri", size=9, color="000000", bold=True)
        font_bold_black = Font(name="Calibri", size=9, bold=True)
        fill_header_ps = PatternFill("solid", fgColor="1F497D")
        fill_header_oc = PatternFill("solid", fgColor="31869B")
        fill_header_err = PatternFill("solid", fgColor="C0504D")
        fill_green = PatternFill("solid", fgColor="00B050")
        fill_grey = PatternFill("solid", fgColor="D9D9D9")
        fill_orange = PatternFill("solid", fgColor="FF9900")
        border_thin = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )
        align_center = Alignment(horizontal="center", vertical="center")

        sheet_missing_ps = f"Missing in {src_label}"
        sheet_missing_oc = f"Missing in {tgt_label}"
        sheet_discrepancies = "Data Discrepancies"

        def _style_header(wb, sn, fill):
            if sn not in wb.sheetnames:
                return
            ws = wb[sn]
            ws.freeze_panes = "A2"
            comment_idxs = []
            for cell in ws[1]:
                cell.fill, cell.font = fill, font_white
                cell.alignment, cell.border = align_center, border_thin
                if cell.value in comment_cols:
                    cell.fill, cell.font = fill_orange, font_black
                    comment_idxs.append(cell.column)
            for col in ws.iter_cols(max_row=min(50, ws.max_row)):
                ml = max((len(str(c.value)) if c.value else 0) for c in col)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max((ml + 2) * 1.2, 10), 60)
            for ci in comment_idxs:
                border_cap = min(ws.max_row, 5000)
                for cells in ws.iter_cols(min_col=ci, max_col=ci, min_row=2, max_row=border_cap):
                    for c in cells:
                        c.border = border_thin

        def _style_config(wb, sn="Configuration"):
            if sn not in wb.sheetnames:
                return
            ws = wb[sn]
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.fill, cell.font = fill_green, font_white
                cell.alignment, cell.border = align_center, border_thin
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.border = border_thin
                    if str(cell.value).strip().lower() in {"yes", "no"}:
                        cell.alignment = align_center
            for col in ws.iter_cols(max_row=ws.max_row):
                ml = max((len(str(c.value)) if c.value else 0) for c in col)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(ml + 2, 12), 45)

        def _style_full_data_header(ws, n_compare_cols):
            """Style the full-data sheet with dual-colour headers (PS blue | OC teal)
            and a medium border separating the two groups."""
            border_ps_last  = Border(left=Side(style="thin"), top=Side(style="thin"), bottom=Side(style="thin"), right=Side(style="medium"))
            border_oc_first = Border(left=Side(style="medium"), top=Side(style="thin"), bottom=Side(style="thin"), right=Side(style="thin"))
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = font_white
                cell.alignment = align_center
                if cell.column <= n_compare_cols:
                    cell.fill = fill_header_ps
                    cell.border = border_ps_last if cell.column == n_compare_cols else border_thin
                else:
                    cell.fill = fill_header_oc
                    cell.border = border_oc_first if cell.column == n_compare_cols + 1 else border_thin
            for col_cells in ws.iter_cols(max_row=min(50, ws.max_row)):
                ml = max((len(str(c.value)) if c.value else 0) for c in col_cells)
                ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(
                    max((ml + 2) * 1.2, 10), 60
                )

        _job_update(job_id, progress=88, stage="Styling Excel sheets")

        sheet_full_data = f"{src_label} - {tgt_label} Data"

        with pd.ExcelWriter(main_output_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, index=False, header=False, sheet_name="Summary")
            config_df.to_excel(writer, index=False, sheet_name="Configuration")
            oracle_only_df.to_excel(writer, index=False, sheet_name=sheet_missing_ps)
            legacy_only_df.to_excel(writer, index=False, sheet_name=sheet_missing_oc)
            write_df_excel_paginated(writer, validation_df, sheet_discrepancies)

            # Optionally include full data in the main workbook
            if include_src_tgt and full_data_for_excel is not None and not full_data_for_excel.empty:
                write_df_excel_paginated(writer, full_data_for_excel, sheet_full_data)

            wb = writer.book
            _style_header(wb, sheet_missing_ps, fill_header_ps)
            _style_header(wb, sheet_missing_oc, fill_header_oc)
            for sn in wb.sheetnames:
                if sn.startswith(sheet_discrepancies):
                    _style_header(wb, sn, fill_header_err)
            _style_config(wb)
            wb["Configuration"].sheet_state = "hidden"

            # Style full data sheets inside main workbook (if included)
            if include_src_tgt:
                for sn in wb.sheetnames:
                    if sn.startswith(sheet_full_data):
                        _style_full_data_header(wb[sn], num_comparison_cols)

            # Summary styling
            ws_sum = wb["Summary"]
            ws_sum.sheet_view.showGridLines = False
            ws_sum.column_dimensions["A"].width = 2
            ws_sum.column_dimensions["B"].width = 45
            for ch in ("C", "D", "E", "F"):
                ws_sum.column_dimensions[ch].width = 25

            for row in ws_sum.iter_rows(min_row=1, max_row=ws_sum.max_row):
                if len(row) < 3:
                    continue
                cell_b = row[1]
                if not cell_b.value:
                    continue
                cell_b.border = border_thin
                row[2].border = border_thin
                cc = [ws_sum.cell(row=cell_b.row, column=c) for c in (4, 5, 6)]

                if cell_b.value in ("Missing Records Summary", "Data Discrepancies Summary"):
                    ws_sum.merge_cells(start_row=cell_b.row, start_column=2,
                                       end_row=cell_b.row, end_column=3)
                    cell_b.fill, cell_b.font = fill_green, font_white
                    cell_b.alignment = align_center
                    ws_sum.row_dimensions[cell_b.row].height = 20
                    for c in cc:
                        c.fill, c.font = fill_orange, font_black
                        c.alignment, c.border = align_center, border_thin
                elif "Total" in str(cell_b.value) or "Comparison Statistics" in str(cell_b.value):
                    if "Comparison Statistics" in str(cell_b.value):
                        ws_sum.merge_cells(start_row=cell_b.row, start_column=2,
                                           end_row=cell_b.row, end_column=3)
                        cell_b.alignment = align_center
                        ws_sum.row_dimensions[cell_b.row].height = 20
                        cell_b.fill, cell_b.font = fill_green, font_white
                    else:
                        cell_b.fill = fill_grey
                        row[2].fill = fill_grey
                        cell_b.font = font_bold_black
                        row[2].font = font_bold_black
                        row[2].alignment = align_center
                else:
                    cell_b.fill, cell_b.font = fill_green, font_white
                    row[2].alignment = align_center
                    for c in cc:
                        c.border = border_thin

        # ── Stage 14b: Cleanup auxiliary data ──────────────────────────
        if full_data_for_excel is not None:
            del full_data_for_excel
            gc.collect()

        # ── Stage 15: Finalize output (96%) ────────────────────────────
        _job_update(job_id, progress=96, stage="Finalizing output")

        report_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"MythicsValidationResults_{report_ts}.xlsx"

        elapsed = time.time() - start_time
        logger.info(f"[{job_id[:8]}] === COMPLETE in {elapsed:.2f}s | "
                     f"{legacy_count + oracle_count:,} total rows ===")

        # ── Mark Complete ──────────────────────────────────────────────
        _job_update(job_id, progress=100, stage="Validation complete",
                    status="complete", zip_path=main_output_path,
                    zip_filename=output_filename)

    except Exception as e:
        logger.error(f"[{job_id[:8]}] Validation failed: {str(e)}", exc_info=True)
        _job_update(job_id, status="failed", error=str(e),
                    stage=f"Failed: {str(e)[:100]}")
    except BaseException as e:
        # Catch SystemExit, KeyboardInterrupt, MemoryError, etc.
        logger.critical(f"[{job_id[:8]}] CRITICAL FAILURE (BaseException): {type(e).__name__}: {str(e)}", exc_info=True)
        _job_update(job_id, status="failed", error=f"{type(e).__name__}: {str(e)}",
                    stage=f"Critical failure: {type(e).__name__}")
    finally:
        import gc
        gc.collect()
        # Flush all log handlers
        for handler in logging.root.handlers:
            handler.flush()
        # Clean up temp files if job failed (successful jobs are cleaned after download)
        try:
            job = _job_get(job_id)
            if job and job.get("status") == "failed":
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"[{job_id[:8]}] Cleaned up temp dir after failure")
        except Exception:
            pass

@app.post("/get-sheets")
async def get_sheets(file: UploadFile = File(...)):
    """
    Returns a list of all worksheet names in the Excel file.
    """
    try:
        contents = await file.read()
        # Use ExcelFile to read metadata without loading the entire dataframe
        with io.BytesIO(contents) as bio:
            xls = pd.ExcelFile(bio, engine='openpyxl')
            return {"sheets": xls.sheet_names}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading sheets: {str(e)}")

@app.post("/extract-headers")
async def extract_headers(
    file: UploadFile = File(...), 
    sheet_name: str = Form(None) # Updated to accept sheet_name
):
    """
    Reads headers from a specific sheet. 
    If sheet_name is not provided, defaults to the first sheet.
    """
    try:
        contents = await file.read()
        with io.BytesIO(contents) as bio:
            # Read only the first few rows for performance
            if sheet_name:
                df = pd.read_excel(bio, sheet_name=sheet_name, nrows=5, engine='openpyxl')
            else:
                df = pd.read_excel(bio, nrows=5, engine='openpyxl')
                
        headers = df.columns.tolist()
        return {"headers": headers}
    except ValueError as ve:
         raise HTTPException(status_code=400, detail=f"Sheet '{sheet_name}' not found.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading headers: {str(e)}")

@app.post("/convert-excel")
async def convert_excel(
    structure_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    # New Sheet Parameters
    structure_sheet: str = Form(None),
    target_sheet: str = Form(None),
    # Existing Mapping Parameters
    legacy_col: str = Form(...),
    oracle_col: str = Form(...),
    attribute_col: str = Form(None),
    target_col: str = Form(None),
):
    """
    Transforms data using specific sheets for Structure and Target files.
    """
    try:
        # 1. Read Structure File (Mapping Logic)
        structure_content = await structure_file.read()
        try:
            # Load specific sheet if provided, else default (0)
            sheet_arg = structure_sheet if structure_sheet else 0
            df_structure = pd.read_excel(io.BytesIO(structure_content), sheet_name=sheet_arg, engine='openpyxl')
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error reading Structure file: {str(e)}")

        # Validate structure columns
        if legacy_col not in df_structure.columns or oracle_col not in df_structure.columns:
            raise HTTPException(status_code=400, detail="Selected mapping columns not found in Structure sheet.")

        # 2. Read Target File (Data to Transform)
        target_content = await target_file.read()
        try:
            sheet_arg = target_sheet if target_sheet else 0
            df_target = pd.read_excel(io.BytesIO(target_content), sheet_name=sheet_arg, engine='openpyxl')
        except Exception as e:
             raise HTTPException(status_code=400, detail=f"Error reading Target file: {str(e)}")

        transform_log = []

        # --- LOGIC BRANCHING ---
        if attribute_col and attribute_col in df_structure.columns:
            # === DYNAMIC MODE ===
            # Normalize attribute column for matching
            df_structure[attribute_col] = df_structure[attribute_col].astype(str).str.strip()
            
            for col in df_target.columns:
                col_name = str(col).strip()
                
                # Check if this column name is defined in the structure file
                if col_name in df_structure[attribute_col].values:
                    # Filter structure rules for this specific column
                    subset = df_structure[df_structure[attribute_col] == col_name]
                    
                    # Create Map: Legacy -> Oracle
                    mapping = dict(zip(subset[legacy_col], subset[oracle_col]))
                    
                    # Apply Map
                    df_target[col] = df_target[col].map(mapping).fillna(df_target[col])
                    transform_log.append(col_name)

        else:
            # === SINGLE COLUMN MODE ===
            if not target_col:
                raise HTTPException(status_code=400, detail="Target column must be specified if Attribute column is not used.")
            
            if target_col in df_target.columns:
                mapping_df = df_structure[[legacy_col, oracle_col]].drop_duplicates(subset=[legacy_col])
                mapping_dict = dict(zip(mapping_df[legacy_col], mapping_df[oracle_col]))
                df_target[target_col] = df_target[target_col].map(mapping_dict).fillna(df_target[target_col])
            else:
                 raise HTTPException(status_code=400, detail=f"Column '{target_col}' not found in Target sheet.")

        # 3. Save to Buffer
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_target.to_excel(writer, index=False)
        
        output.seek(0)

        filename_prefix = "Dynamic_Transformed" if attribute_col else f"Transformed_{target_col}"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename_prefix}.xlsx"'
        }
        return StreamingResponse(output, headers=headers, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transformation failed: {str(e)}")
    


# --- PeopleSoft Finance
@app.get("/api/utils/finance/menu-items")
async def get_finance_menu_items():
    """
    Returns a list of predefined menu items for PeopleSoft Finance.
    returns the json file content as is.
    """
    try:
        menu_file_path = _get_resource_path("Required_files/finance_menu_items.json")
        with open(menu_file_path, "r") as f:
            menu_items = json.load(f)
            final = {
                "status": 200,
                "menu_items": menu_items
            }
        return final
    except Exception as e:
        return JSONResponse(
            content={"error": f"Failed to load menu items: {str(e)}"},
            status_code=500,
        )
        
