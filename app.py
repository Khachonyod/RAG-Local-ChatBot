import os
import sys
import uuid
import threading
import webview
from flask import Flask, request, jsonify, render_template

# LangChain Imports
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, UnstructuredExcelLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

def get_resource_path(relative_path):
    """จัดการ Path ให้รองรับการ Build ด้วย PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(__name__, template_folder=get_resource_path('templates'))
sessions = {}

def get_page_number(metadata):
    """Helper Function ป้องกัน Error กรณีไฟล์(เช่น .txt) ไม่มี metadata หน้า"""
    page = metadata.get("page")
    return int(page) + 1 if page is not None else 1

def build_rag_multiple(file_paths: list, session_id: str):
    """ฟังก์ชันเบื้องหลังสำหรับประมวลผลไฟล์และสร้าง Vector DB"""
    sessions[session_id]["status"] = "loading"
    try:
        all_docs = []
        for file_path in file_paths:
            ext = os.path.splitext(file_path)[1].lower()
            try:
                if ext == '.pdf': loader = PyPDFLoader(file_path)
                elif ext == '.txt': loader = TextLoader(file_path, encoding='utf-8')
                elif ext in ['.doc','.docx']: loader = Docx2txtLoader(file_path)
                elif ext in ['.xls','.xlsx']: loader = UnstructuredExcelLoader(file_path)
                else: continue

                docs = loader.load()
                filename = os.path.basename(file_path)
                for d in docs:
                    d.metadata["filename"] = filename
                all_docs.extend(docs)
            except Exception as e:
                print(f"ข้ามไฟล์{file_path} เนื่องจากError: {str(e)}")
                continue
        
        if not all_docs:
            raise ValueError("ไม่สามารถอ่านเนื้อหาจากไฟล์ใดๆ ได้เลย")

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        splits = splitter.split_documents(all_docs)

        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        PERSIST_DIR = os.path.join(os.getcwd(), "chroma_db")

        if sessions[session_id]["retriever"] is not None:
            vector_db = Chroma(
                collection_name=f"temp_{session_id}",
                embedding_function=embeddings,
                persist_directory=PERSIST_DIR
            )
            vector_db.add_documents(splits)
        else:
            vector_db = Chroma.from_documents(
                documents=splits, 
                embedding=embeddings,
                collection_name=f"temp_{session_id}",
                persist_directory=PERSIST_DIR
            )

        llm = ChatOllama(model="llama3", temperature=0)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "คุณคือผู้ช่วย AI จงตอบคำถามจากข้อมูลที่ให้มาเป็นภาษาไทยเท่านั้น\n"
                       "ข้อมูลด้านล่างนี้อาจมาจากเอกสารหลายชุด ให้สังเกตป้ายระบุ [ไฟล์: ...] อย่างละเอียด "
                       "หากผู้ใช้สั่งให้เปรียบเทียบ สรุปข้อเหมือน หรือข้อต่าง ให้ระบุข้อมูลแจกแจงแยกตามรายชื่อไฟล์อย่างชัดเจน\n\nContext: {context}"),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}")
        ])

        retriever = vector_db.as_retriever(search_kwargs={"k": 6})
        base_chain = prompt | llm | StrOutputParser()
        
        sessions[session_id]["retriever"] = retriever
        sessions[session_id]["base_chain"] = base_chain
        sessions[session_id]["status"] = "ready"
    except Exception as e:
        sessions[session_id]["status"] = f"error: {str(e)}"

# ==================== FLASK ROUTES ====================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/load", methods=["POST"])
def api_load():
    data = request.get_json()
    path = data.get("path")
    session_id = data.get("session_id")

    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "error": "ไฟล์ไม่ถูกต้อง"}), 400
    
    supported_ext = ['.pdf','.doc','.docx','.txt','.xls','.xlsx']
    files_to_process = []

    if os.path.isdir(path):
        for root, dir, files in os.walk(path):
            for file in files:
                if os.path.splitext(file)[1].lower() in supported_ext:
                    files_to_process.append(os.path.join(root, file))
    else:
        if os.path.splitext(path)[1].lower() in supported_ext:
            files_to_process.append(path)

    if not files_to_process:
        return jsonify({"ok": False, "error": "ไม่พบไฟล์เอกสารที่รับรอง"}), 400
    
    new_filenames = [os.path.basename(f) for f in files_to_process]
    
    filename = os.path.basename(path)

    if session_id and session_id in sessions:

        new_files_to_add = [f for f in new_filenames if f not in sessions[session_id]["filenames"]]
        if not new_files_to_add:
            return jsonify({"ok": False, "error": "ไฟล์ทั้งหมดในนี้ถูกเพิ่มไปแล้ว"}), 400
        sessions[session_id]["filenames"].extend(new_files_to_add)
    else:
        session_id = uuid.uuid4().hex
        sessions[session_id] = {
            "status": "idle",
            "filenames": new_filenames,
            "chat_history": [],
            "retriever": None,
            "base_chain": None
        }

    threading.Thread(target=build_rag_multiple, args=(files_to_process, session_id), daemon=True).start()
    return jsonify({"ok": True, "session_id": session_id, "filenames": sessions[session_id]["filenames"]})

@app.route("/api/sessions", methods=["GET"])
def api_sessions():
    session_list = [{"id": sid, "filenames": data["filenames"]} for sid, data in sessions.items()]
    return jsonify({"ok": True, "sessions": session_list})

@app.route("/api/history/<session_id>", methods=["GET"])
def api_history(session_id):
    if session_id not in sessions:
        return jsonify({"ok": False, "error": "ไม่พบ Session"}), 404
        
    history = []
    for msg in sessions[session_id]["chat_history"]:
        role = "user" if msg.type == "human" else "ai"
        pages = msg.additional_kwargs.get("pages", []) if role == "ai" else []
        chunks = msg.additional_kwargs.get("chunks", []) if role == "ai" else []
        history.append({"role": role, "content": msg.content, "pages": pages, "chunks": chunks})
        
    return jsonify({
        "ok": True, 
        "history": history, 
        "filenames": sessions[session_id]["filenames"],
        "status": sessions[session_id]["status"]
    })

@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json()
    session_id = data.get("session_id")
    query = data.get("query")

    if not session_id or session_id not in sessions:
        return jsonify({"ok": False, "error": "ไม่พบ Session กรุณาอัปโหลดไฟล์ใหม่"}), 400
        
    session_data = sessions[session_id]
    
    if session_data["status"] != "ready":
        return jsonify({"ok": False, "error": "กรุณารอประมวลผลเอกสารสักครู่..."}), 400
    
    try:
        docs = session_data["retriever"].invoke(query)

        context_items = []
        for d in docs:
            fname = d.metadata.get("filename", "ไม่ระบุไฟล์")
            page = get_page_number(d.metadata)
            context_items.append(f"[ข้อมูลจาก ไฟล์: {fname} หน้าที่: {page}]:\n{d.page_content}")

        context = "\n\n".join(context_items)
        
        answer = session_data["base_chain"].invoke({
            "context": context,
            "question": query,
            "chat_history": session_data["chat_history"]
        })
        
        pages = sorted(list(set(get_page_number(d.metadata) for d in docs)))

        chunks = [{
            "content": d.page_content,
            "page": get_page_number(d.metadata),
            "filename": d.metadata.get("filename", "ไม่ระบุไฟล์")
        } for d in docs]
        
        session_data["chat_history"].extend([
            HumanMessage(content=query),
            AIMessage(content=answer, additional_kwargs={"pages": pages, "chunks": chunks})
        ])
        
        return jsonify({"ok": True, "answer": answer, "pages": pages, "chunks": chunks})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ==================== PYWEBVIEW API ====================

class API:
    def pick_file(self):
        if not webview.windows: return None
        window = webview.windows[0] 
        file_types = ('Support Documents (*.pdf;*.txt;*.docx;*.xls;*.xlsx)', 'All files (*.*)')
        result = window.create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        return result[0] if result else None
    
    def pick_folder(self):
        if not webview.windows: return None
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def save_chat(self, session_id):
        if session_id not in sessions: return False
        history = sessions[session_id]["chat_history"]
        filename_str = ", ".join(sessions[session_id]["filenames"])
        
        export_text = f"=== รายงานการสนทนาจากเอกสาร: {filename_str} ===\n"
        export_text += "=" * 50 + "\n\n"
        
        for msg in history:
            role = "USER" if msg.type == "human" else "AI ASSISTANT"
            export_text += f"[{role}]:\n{msg.content}\n"
            if role == "AI ASSISTANT" and "pages" in msg.additional_kwargs:
                pages = msg.additional_kwargs["pages"]
                if pages: export_text += f"(อ้างอิงจากหน้า: {', '.join(map(str, pages))})\n"
            export_text += "-" * 30 + "\n\n"
        
        if not webview.windows: return False
        window = webview.windows[0]

        save_path = window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=f"Chat_Summary_{session_id[:6]}.txt",
            file_types=('Text Files (*.txt)',)
        )

        if save_path:
            actual_path = save_path[0] if isinstance(save_path, (tuple, list)) else save_path
            try:
                with open(actual_path, 'w', encoding='utf-8') as f:
                    f.write(export_text)
                return True
            except Exception as e:
                print(f"Error saving file: {e}")
                return False
        return False

if __name__ == "__main__":
    api = API()
    threading.Thread(target=lambda: app.run(port=5050), daemon=True).start()
    webview.create_window("Local RAG Assistant", "http://127.0.0.1:5050", js_api=api)
    webview.start()