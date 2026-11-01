# 🤖 RAG Local Assistant

> ถาม-ตอบเอกสารด้วย AI บนเครื่องของคุณ — ไม่ต้องส่งข้อมูลออกนอกเครื่อง

ระบบ **Retrieval-Augmented Generation (RAG)** แบบ Local ที่รวม **Hybrid Search** (Vector + BM25) เพื่อค้นหาเนื้อหาจากเอกสาร แล้วใช้ LLM (ผ่าน Ollama) สร้างคำตอบภาษาไทย

## ✨ Features

- 📄 **รองรับหลายรูปแบบ** — PDF, DOCX, TXT, CSV, Excel
- 📑 **แบ่งหน้า DOCX** — ใช้ page break ที่ระบุในเอกสารเพื่อแนบเลขหน้าให้ข้อความ
- 🔍 **Hybrid Search** — ผสม Vector Search (Semantic) กับ BM25 (Keyword) ปรับน้ำหนักได้แบบ realtime
- 🧠 **Multiple LLMs** — เลือกใช้ Llama 3, Qwen 2.5 หรือโมเดลอื่นผ่าน Ollama
- 💬 **Streaming Response** — แสดงคำตอบแบบ realtime ด้วย Server-Sent Events
- 📎 **Source Citation** — แสดงหน้าและข้อความต้นฉบับที่ AI ใช้อ้างอิง
- 🔐 **100% Local** — ทุกอย่างรันบนเครื่อง ไม่มีข้อมูลออกไปข้างนอก
- 🌙 **Dark Mode** — สลับโหมดมืด/สว่างได้
- 📥 **Export PDF** — ส่งออกประวัติแชทเป็น PDF พร้อมข้อมูลอ้างอิง
- 🇹🇭 **Thai NLP** — ตัดคำไทยด้วย PyThaiNLP สำหรับ BM25 ที่แม่นยำ

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│                  pywebview (Desktop)             │
├───────────┬─────────────────────────────────────┤
│  Sidebar  │            Main Chat Area           │
│  Sessions │   ┌─────────────────────────────┐   │
│  Upload   │   │  Flask API (Backend)        │   │
│           │   │  ├── Document Loader        │   │
│           │   │  ├── Text Chunking          │   │
│           │   │  ├── Hybrid Search          │   │
│           │   │  │   ├── ChromaDB (Vector)  │   │
│           │   │  │   └── BM25 (Keyword)     │   │
│           │   │  └── Ollama LLM (Streaming) │   │
│           │   └─────────────────────────────┘   │
└───────────┴─────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.ai)** — ติดตั้งและดาวน์โหลดโมเดล: `ollama pull llama3`
- **Tesseract OCR** พร้อม language data ภาษาไทย (`tha`) และอังกฤษ (`eng`)
- **Poppler** *(optional; ใช้เป็น fallback หาก pypdfium2 แปลง PDF ไม่สำเร็จ)*

### Installation

```bash
# 1. Clone repository
git clone <repo-url>
cd Project_RAG_Year3_Term2

# 2. สร้าง virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux

# 3. ติดตั้ง dependencies
pip install -r requirements.txt

# 4. ตั้งค่า environment (optional)
copy .env.example .env
# แก้ไข .env ตามเครื่องของคุณ

# 5. รันโปรแกรม
python app.py
```

## ⚙️ Configuration

> หมายเหตุ: การแบ่งหน้า DOCX อ้างอิง page break ที่ฝังอยู่ในไฟล์ ไม่รวมหน้าที่เกิดจากการจัดหน้าอัตโนมัติของ Microsoft Word

คัดลอก `.env.example` เป็น `.env` แล้วปรับค่า:

| Variable | Default | Description |
|----------|---------|-------------|
| `TESSERACT_CMD` | *auto-detect* | Path ไปยัง Tesseract executable |
| `POPPLER_PATH` | *none* | Path ไปยัง Poppler bin directory |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | โมเดล embedding |
| `CHUNK_SIZE` | `1000` | ขนาด chunk (ตัวอักษร) |
| `CHUNK_OVERLAP` | `100` | ส่วนที่ซ้อนทับกันของ chunk |
| `LLM_TEMPERATURE` | `0` | Temperature ของ LLM (0 = deterministic) |
| `LLM_NUM_CTX` | `4096` | Context window size ของ LLM |

## 📁 Project Structure

```
Project_RAG_Year3_Term2/
├── app.py                  # Flask app + pywebview + API routes
├── evaluate_ocr.py         # เครื่องมือประเมินผล OCR
├── core/
│   ├── config.py           # Environment configuration
│   ├── document.py         # Document loaders (PDF, DOCX, CSV, etc.)
│   ├── rag_engine.py       # RAG engine (Chroma, LLM chain, embeddings)
│   └── text_utils.py       # Thai tokenizer for BM25
├── templates/
│   └── index.html          # Frontend HTML template
├── static/
│   ├── css/style.css       # Design system & styles
│   └── js/script.js        # Frontend logic
├── fonts/                  # Thai fonts for PDF export
├── .env.example            # Environment template
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## 📝 License

This project is for educational purposes (Year 3, Term 2).
