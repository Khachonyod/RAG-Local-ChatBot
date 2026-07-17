# core/text_utils.py
"""
ตัวช่วยตัดคำสำหรับ BM25

ปัญหาเดิม: ใช้ text.split() ซึ่งตัดคำตามช่องว่าง แต่ภาษาไทยไม่มีช่องว่างระหว่างคำ
ทำให้ทั้งประโยคภาษาไทยถูกนับเป็น token เดียว BM25 จึงแทบไม่ทำงานกับข้อความไทยเลย

วิธีแก้: ใช้ pythainlp.word_tokenize ตัดคำไทยจริง ๆ ก่อน
(รองรับข้อความผสมไทย-อังกฤษ/ตัวเลขในตัวอยู่แล้ว เพราะ engine 'newmm'
จะแยก non-Thai substring ออกมาเป็น token ของมันเองโดยอัตโนมัติ)
"""
import re
from functools import lru_cache

try:
    from pythainlp.tokenize import word_tokenize as _pythai_word_tokenize
    _HAS_PYTHAINLP = True
except ImportError:
    _HAS_PYTHAINLP = False

# ตัด whitespace/newline ที่ไม่มีความหมายทิ้ง เพื่อไม่ให้กลายเป็น token ขยะ
_WHITESPACE_RE = re.compile(r"\s+")
# คำ stopword ไทยพื้นฐานที่พบบ่อยมาก แต่ไม่ช่วยแยกแยะเนื้อหา (ช่วยลด noise ให้ BM25)
_THAI_STOPWORDS = {
    "ที่", "และ", "ใน", "การ", "เป็น", "ของ", "ให้", "ได้", "มี", "ไม่",
    "จะ", "กับ", "แต่", "ก็", "อยู่", "ไป", "มา", "นี้", "นั้น", "ๆ",
    "แล้ว", "ซึ่ง", "หรือ", "จาก", "โดย", "ด้วย", "คือ", "อีก", "เพื่อ",
}


@lru_cache(maxsize=1)
def _warn_once():
    print(
        "[WARNING] ไม่พบ pythainlp — ใช้ .split() แบบเดิม (BM25 จะทำงานได้ไม่ดีกับข้อความไทย) "
        "แนะนำให้ติดตั้งด้วย: pip install pythainlp"
    )
    return True


def thai_tokenize(text: str) -> list[str]:
    """
    ตัดคำข้อความ (ไทยผสมอังกฤษ) ให้เหมาะกับการทำ BM25 index/query

    ใช้ฟังก์ชันนี้แทน text.split() ทุกจุดที่เคยใช้ตอนสร้าง/ค้น BM25 corpus
    """
    if not text:
        return []

    if not _HAS_PYTHAINLP:
        _warn_once()
        return text.split()

    tokens = _pythai_word_tokenize(text, engine="newmm", keep_whitespace=False)

    cleaned = []
    for tok in tokens:
        tok = _WHITESPACE_RE.sub("", tok)
        if not tok:
            continue
        if tok in _THAI_STOPWORDS:
            continue
        cleaned.append(tok.lower())

    return cleaned
