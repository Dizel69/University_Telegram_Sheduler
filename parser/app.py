from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
from io import BytesIO
from utils import extract_images_from_page, simple_normalize_text, guess_type_from_text, extract_times, extract_date, ICON_DIR
from typing import List, Dict, Any
import os
import tempfile
import uuid
import shutil

app = FastAPI(title="M15 PDF Parser")

# Allow CORS from local dev frontend (and others) so browser uploads work
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.getenv("PARSER_UPLOAD_DIR", "/tmp/parser_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/upload_pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF allowed")

    tmp_name = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}.pdf")
    with open(tmp_name, "wb") as f:
        content = await file.read()
        f.write(content)

    previews = []
    try:
        with pdfplumber.open(tmp_name) as pdf:
            for pnum, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                norm_text = simple_normalize_text(page_text)
                images = extract_images_from_page(page)

                parts = [p.strip() for p in page_text.split('\n\n') if p.strip()]
                for part in parts:
                    txt = simple_normalize_text(part)
                    if not txt:
                        continue
                    typ = guess_type_from_text(txt)
                    start, end = extract_times(txt)
                    date = extract_date(txt)
                    previews.append({
                        "page": pnum,
                        "raw": txt,
                        "type": typ,
                        "start": start,
                        "end": end,
                        "date": date,
                        "images": images
                    })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"error parsing pdf: {e}")

    return JSONResponse({"preview": previews, "icons_dir": ICON_DIR})
