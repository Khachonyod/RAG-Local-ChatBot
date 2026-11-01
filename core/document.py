import os
import zipfile
import xml.etree.ElementTree as ET
import pandas as pd
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader
)

try:
    from pdf2image import convert_from_path
    import pytesseract
    _HAS_OCR_LIBS = True
except ImportError:
    _HAS_OCR_LIBS = False

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_DOCX_W = f"{{{_DOCX_NS['w']}}}"


def _load_docx_by_page_breaks(file_path: str) -> list[Document]:
    """Load DOCX text into page documents using explicit page breaks."""
    with zipfile.ZipFile(file_path) as archive:
        document_xml = ET.fromstring(archive.read("word/document.xml"))

    body = document_xml.find("w:body", _DOCX_NS)
    if body is None:
        raise ValueError(f"ไม่พบเนื้อหาเอกสาร Word: {file_path}")

    documents = []
    page_number = 1
    page_text = []
    filename = os.path.basename(file_path)

    def finish_page():
        content = "".join(page_text).strip()
        if content:
            documents.append(Document(
                page_content=content,
                metadata={"source": filename, "page": page_number - 1},
            ))

    def start_new_page():
        nonlocal page_number, page_text
        finish_page()
        page_number += 1
        page_text = []

    def iter_paragraphs(element):
        for child in element:
            if child.tag == f"{_DOCX_W}p":
                yield child
            elif child.tag == f"{_DOCX_W}tbl":
                yield from iter_paragraphs(child)
            else:
                yield from iter_paragraphs(child)

    for paragraph in iter_paragraphs(body):
        paragraph_properties = paragraph.find("w:pPr", _DOCX_NS)
        if paragraph_properties is not None and paragraph_properties.find(
            "w:pageBreakBefore", _DOCX_NS
        ) is not None:
            start_new_page()

        for element in paragraph.iter():
            if element.tag == f"{_DOCX_W}t":
                page_text.append(element.text or "")
            elif element.tag == f"{_DOCX_W}tab":
                page_text.append("\t")
            elif element.tag == f"{_DOCX_W}br":
                if element.get(f"{_DOCX_W}type") == "page":
                    start_new_page()
                else:
                    page_text.append("\n")

        page_text.append("\n")

        section_properties = (
            paragraph_properties.find("w:sectPr", _DOCX_NS)
            if paragraph_properties is not None
            else None
        )
        if section_properties is not None:
            section_type = section_properties.find("w:type", _DOCX_NS)
            break_type = (
                section_type.get(f"{_DOCX_W}val")
                if section_type is not None
                else "nextPage"
            )
            if break_type == "nextPage":
                start_new_page()
            elif break_type in {"oddPage", "evenPage"}:
                start_new_page()
                desired_parity = 1 if break_type == "oddPage" else 0
                if page_number % 2 != desired_parity:
                    page_number += 1

    finish_page()
    return documents


def _ocr_pdf(file_path: str, poppler_path: str | None, tesseract_cmd: str | None) -> list:
    """
    OCR ไฟล์ PDF ที่เป็นภาพสแกน (ไม่มี text layer ให้ PyPDFLoader ดึงได้)
    แปลงแต่ละหน้าเป็นรูปภาพด้วย pdf2image (ต้องใช้ Poppler) แล้วอ่านตัวอักษรด้วย pytesseract
    """
    if not _HAS_OCR_LIBS:
        raise RuntimeError(
            "ไฟล์นี้เป็น PDF แบบภาพสแกน (ไม่มี text layer) แต่ไม่พบไลบรารีสำหรับ OCR "
            "กรุณาติดตั้งด้วย: pip install pdf2image pytesseract"
        )
    if not tesseract_cmd:
        raise RuntimeError(
            "ไฟล์นี้เป็น PDF แบบภาพสแกน ต้องใช้ Tesseract OCR แต่ไม่พบโปรแกรม Tesseract ในเครื่อง "
            "กรุณาติดตั้งและตั้งค่า TESSERACT_CMD ใน .env"
        )
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    convert_kwargs = {"poppler_path": poppler_path} if poppler_path else {}
    images = convert_from_path(file_path, **convert_kwargs)

    documents = []
    for i, image in enumerate(images):
        text = pytesseract.image_to_string(image, lang="tha+eng")
        if text.strip():
            documents.append(Document(
                page_content=text,
                metadata={"source": os.path.basename(file_path), "page": i}
            ))
    return documents


def load_single_file(file_path: str, poppler_path: str | None = None, tesseract_cmd: str | None = None):
    """
    ฟังก์ชันสำหรับโหลดและแปลงไฟล์เอกสารต่างๆ ให้อยู่ในรูปแบบ Document Object
    รองรับ: .csv, .xlsx, .xls, .pdf, .docx, .txt
    """
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    
    documents = []

    # ---------------------------------------------------------
    # 1. จัดการไฟล์ประเภทตาราง (Excel และ CSV) แบบ Dynamic
    # ---------------------------------------------------------
    if ext in ['.csv', '.xlsx', '.xls']:
        try:
            if ext == '.csv':
                df = pd.read_csv(file_path)
            else:
                engine = 'xlrd' if ext == '.xls' else 'openpyxl'
                df = pd.read_excel(file_path, engine=engine)
            
            df = df.fillna("")
            
            for index, row in df.iterrows():
                row_data_list = []
                
                for col_name, value in row.items():
                    if str(value).strip() != "":
                        row_data_list.append(f"{col_name}: {value}")
                
                if row_data_list:
                    text_content = " | ".join(row_data_list)
                    
                    doc = Document(
                        page_content=text_content, 
                        metadata={
                            "source": os.path.basename(file_path), 
                            "row": index + 1 
                        }
                    )
                    documents.append(doc)
            
            return documents
            
        except Exception as e:
            print(f"Error loading tabular file {file_path}: {e}")
            return []

    # ---------------------------------------------------------
    # 2. จัดการไฟล์เอกสารทั่วไป (PDF, Word, Text)
    # ---------------------------------------------------------
    elif ext == '.pdf':
        loader = PyPDFLoader(file_path)
        docs = loader.load()

        # PyPDFLoader ดึงได้แค่ text layer ที่มีอยู่แล้วในไฟล์ PDF เท่านั้น
        # ถ้าไฟล์เป็น PDF แบบภาพสแกน (ไม่มี text layer) จะได้ page_content ว่างเปล่าทุกหน้า
        # ซึ่งถ้าปล่อยผ่านไปตรงๆ splitter จะไม่มี chunk ให้ embed เลย ทำให้ Chroma error ตอน upsert
        has_text = any(d.page_content.strip() for d in docs)
        if not has_text:
            return _ocr_pdf(file_path, poppler_path, tesseract_cmd)
        return docs
        
    elif ext == '.docx':
        return _load_docx_by_page_breaks(file_path)

    elif ext == '.doc':
        loader = Docx2txtLoader(file_path)
        return loader.load()
        
    elif ext == '.txt':
        loader = TextLoader(file_path, encoding='utf-8')
        return loader.load()
        
    else:
        raise ValueError(f"ระบบยังไม่รองรับไฟล์นามสกุล: {ext}")