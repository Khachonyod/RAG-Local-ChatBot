# core/document.py
import os
import pytesseract
from pdf2image import convert_from_path
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, UnstructuredExcelLoader
from langchain_core.documents import Document

def load_single_file(file_path: str, poppler_path: str, tesseract_cmd: str) -> list:
    """โหลดเนื้อหาจากไฟล์เดี่ยว รองรับ PDF (พร้อม OCR Fallback), TXT, WORD, EXCEL"""
    ext = os.path.splitext(file_path)[1].lower()
    docs = []
    
    if ext == '.pdf':
        docs = PyPDFLoader(file_path).load()
        total_text = "".join([d.page_content for d in docs]).strip()
        
        # รัน OCR หากตรวจพบว่าเป็นไฟล์ PDF จากการสแกน (มีตัวอักษรน้อยกว่ากำหนด)
        if len(total_text) < 50:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            images = convert_from_path(file_path, poppler_path=poppler_path)
            docs = [
                Document(
                    page_content=pytesseract.image_to_string(img, lang='tha+eng'), 
                    metadata={"source": file_path, "page": i}
                ) 
                for i, img in enumerate(images)
            ]
    elif ext == '.txt':
        docs = TextLoader(file_path, encoding='utf-8').load()
    elif ext in ['.doc', '.docx']:
        docs = Docx2txtLoader(file_path).load()
    elif ext in ['.xls', '.xlsx']:
        docs = UnstructuredExcelLoader(file_path).load()

    if docs:
        filename = os.path.basename(file_path)
        for d in docs: 
            d.metadata["filename"] = filename
            
    return docs