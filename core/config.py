# core/config.py
import os
import shutil
from dotenv import load_dotenv

load_dotenv()

def _resolve_executable(env_key: str, exe_name: str, fallback_paths: list) -> str | None:
    """ลำดับการค้นหา: 1) .env  2) PATH ของระบบ  3) ตำแหน่งที่พบบ่อย"""
    from_env = os.getenv(env_key)
    if from_env and os.path.exists(from_env):
        return from_env
    
    from_path = shutil.which(exe_name)
    if from_path:
        return from_path
    
    for path in fallback_paths:
        if os.path.exists(path):
            return path
        
    return None # ไม่พบ - ให้ OCR fallback แจ้ง error ตอนใช้งานจริงแทนที่จะ crash ตอน import

TESSERACT_CMD = _resolve_executable(
    "TESSERACT_CMD", "tesseract",
    [r"C:\Program Files\Tesseract-OCR\tesseract.exe", "/usr/bin/tesseract", "/usr/local/bin/tesseract"]
)

POPPLER_PATH = os.getenv("POPPLER_PATH") # poppler ไม่มี exe เดี่ยวให้ shutil.which เช็ค ต้องระบุ path ตรงๆ

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

SESSION_FILE = os.getenv("SESSION_FILE", "sessions.json")
PERSIST_DIR = os.path.join(os.getcwd(), os.getenv("CHROMA_DIR", "chroma_db"))