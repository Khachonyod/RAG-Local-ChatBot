import os
import zipfile
import xml.etree.ElementTree as ET
import pandas as pd
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader
)

try:
    import pypdfium2 as pdfium
    _HAS_PDFIUM = True
except ImportError:
    _HAS_PDFIUM = False

try:
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False

try:
    from pdf2image import convert_from_path
    _HAS_PDF2IMAGE = True
except ImportError:
    _HAS_PDF2IMAGE = False

from core.config import TESSERACT_CMD

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


def _ocr_pdf(
    file_path: str,
    poppler_path: str | None = None,
    tesseract_cmd: str | None = None,
) -> list:
    """
    OCR ไฟล์ PDF ที่เป็นภาพสแกน (ไม่มี text layer ให้ตัวอ่าน PDF ดึงได้)
    ใช้ Tesseract OCR สำหรับภาษาไทยและอังกฤษ
    ลำดับการแปลง PDF เป็นรูปภาพ:
    1) ใช้ pypdfium2 (เร็วกว่า ไม่ต้องลงโปรแกรม Poppler ภายนอก)
    2) Fallback ไปใช้ pdf2image
    """
    tesseract_cmd = tesseract_cmd or TESSERACT_CMD
    if not _HAS_TESSERACT:
        raise RuntimeError(
            "ไม่พบไลบรารี pytesseract กรุณาติดตั้งด้วย: pip install pytesseract"
        )
    if not tesseract_cmd:
        raise RuntimeError(
            "ไฟล์นี้เป็น PDF แบบภาพสแกน ต้องใช้ Tesseract OCR แต่ไม่พบโปรแกรม "
            "Tesseract ในเครื่อง กรุณาติดตั้งและตั้งค่า TESSERACT_CMD ใน .env"
        )

    images = []

    # 1. ลองใช้ pypdfium2 แปลงหน้า PDF เป็นภาพก่อน (ไม่ต้องพึ่งพา Poppler)
    if _HAS_PDFIUM:
        pdf = None
        try:
            pdf = pdfium.PdfDocument(file_path)
            for page_idx in range(len(pdf)):
                page = pdf[page_idx]
                # scale=2.0 ให้ resolution ~144 DPI เหมาะกับ OCR กำลังดี
                pil_image = page.render(scale=2.0).to_pil()
                images.append((page_idx, pil_image))
                page.close()
        except Exception as e:
            print(f"[WARNING] แปลง PDF ด้วย pypdfium2 ไม่สำเร็จ ({e}) — สลับไปใช้ pdf2image")
            images = []
        finally:
            if pdf is not None:
                pdf.close()

    # 2. Fallback ใช้ pdf2image
    if not images and _HAS_PDF2IMAGE:
        convert_kwargs = {"poppler_path": poppler_path} if poppler_path else {}
        try:
            pil_images = convert_from_path(file_path, **convert_kwargs)
            images = [(idx, img) for idx, img in enumerate(pil_images)]
        except Exception as e:
            raise RuntimeError(
                f"ไม่สามารถแปลงหน้า PDF เป็นรูปภาพเพื่อทำ OCR ได้ ({e}) "
                "หากใช้ Windows กรุณาตั้งค่า POPPLER_PATH ใน .env"
            )

    if not images:
        raise RuntimeError("ไม่สามารถดึงรูปภาพจากหน้า PDF เพื่อทำ OCR ได้")

    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    documents = []
    filename = os.path.basename(file_path)

    for page_idx, image in images:
        text = pytesseract.image_to_string(image, lang="tha+eng").strip()
        if text:
            documents.append(Document(
                page_content=text,
                metadata={"source": filename, "page": page_idx}
            ))

    return documents


def load_single_file(
    file_path: str,
    poppler_path: str | None = None,
    tesseract_cmd: str | None = None,
    *args,
    **kwargs,
):
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
        docs = []
        if _HAS_PDFIUM:
            pdf = None
            try:
                pdf = pdfium.PdfDocument(file_path)
                filename = os.path.basename(file_path)
                for page_idx in range(len(pdf)):
                    page = pdf[page_idx]
                    text_page = page.get_textpage()
                    text = text_page.get_text_range()
                    text_page.close()
                    page.close()
                    if text.strip():
                        docs.append(Document(
                            page_content=text,
                            metadata={"source": filename, "page": page_idx}
                        ))
            except Exception as e:
                print(f"[WARNING] อ่าน PDF ด้วย pypdfium2 ไม่สำเร็จ ({e}) — สลับไปใช้ PyPDFLoader")
                docs = []
            finally:
                if pdf is not None:
                    pdf.close()

        if not docs:
            loader = PyPDFLoader(file_path)
            docs = loader.load()

        has_text = any(d.page_content.strip() for d in docs)
        if not has_text:
            return _ocr_pdf(
                file_path,
                poppler_path=poppler_path,
                tesseract_cmd=tesseract_cmd,
            )
        return docs
        
    elif ext == '.docx':
        return _load_docx_by_page_breaks(file_path)
        
    elif ext == '.txt':
        loader = TextLoader(file_path, encoding='utf-8')
        return loader.load()
        
    else:
        raise ValueError(f"ระบบยังไม่รองรับไฟล์นามสกุล: {ext}")