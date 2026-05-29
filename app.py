import threading
import webview
from flask import Flask, request, jsonify, render_template
import os
import sys
import uuid

from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage

def get_resource_path(relative_path):
    """ฟังก์ชันช่วยหา Path ที่แท้จริงเวลาแปลงเป็น .exe"""
    try:
        # PyInstaller จะเก็บ Path จำลองไว้ใน _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # ถ้าไม่ได้รันเป็น .exe ให้ใช้ Path ปัจจุบัน
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(__name__, template_folder=get_resource_path('templates'))
sessions = {}

def build_rag(file_path: str, session_id: str):
    sessions[session_id]["status"] = "loading"
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.pdf':
            loader = PyPDFLoader(file_path)
        elif ext == '.txt':
            loader = TextLoader(file_path, encoding='utf-8')
        elif ext in ['.doc', '.docx']:
            loader = Docx2txtLoader(file_path)
        else:
            raise ValueError(f"ระบบยังไม่รองรับไฟล์ประเภท {ext}")
        
        docs = loader.load()
        filename = os.path.basename(file_path)

        # ฝังชื่อไฟล์ลงใน metadata ของเอกสารก่อนแบ่ง chunks
        for d in docs:
            d.metadata["filename"] = filename

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        splits = splitter.split_documents(docs)

        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        PERSIST_DIR = os.path.join(os.getcwd(), "chroma_db")

        # ตรวจสอบว่าถ้ามี Retriever อยู่แล้วให้แอดเพิ่มเข้าไป ห้ามสร้างทับ
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
    
    filename = os.path.basename(path)

    if session_id and session_id in sessions:
        if filename in sessions[session_id]["filenames"]:
            return jsonify({"ok": False, "error": "ไฟล์นี้ถูกเพิ่มไปแล้ว"}), 400
        sessions[session_id]["filenames"].append(filename)
    else:
        session_id = uuid.uuid4().hex

        sessions[session_id] = {
            "status": "idle",
            "filename": [filename],
            "chat_history": [],
            "retriever": None,
            "base_chain": None
        }
    
    threading.Thread(target=build_rag, args=(path, session_id), daemon=True).start()
    return jsonify({"ok": True, "session_id": session_id, "filename": filename})

@app.route("/api/sessions", methods=["GET"])
def api_sessions():
    session_list = [{"id": sid, "filename": data["filename"]} for sid, data in sessions.items()]
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
        "filename": sessions[session_id]["filename"],
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
            fname = d.metadata("filename", "ไม่ระบุไฟล์")
            page = d.metadata("page", 0) + 1
            context_items.append(f"[ข้อมูลจาก ไฟล์: {fname} หน้าที่: {page}]:\n{d.page_content}")

        context = "\n\n".join(context_items)
        
        answer = session_data["base_chain"].invoke({
            "context": context,
            "question": query,
            "chat_history": session_data["chat_history"]
        })
        
        pages = sorted(list(set(d.metadata.get("page", 0) + 1 for d in docs)))

        #เก็บ metadata ชื่อไฟล์แนบกลับไปแสดงผลฝั่งหน้าบ้านด้วย
        chunks = [{
            "content": d.page_content,
            "page": d.metadata.get("page", 0) + 1,
            "filename": d.metadata.get("filename", "ไม่ระบุไฟล์")
            } for d in docs]
        
        session_data["chat_history"].extend([
            HumanMessage(content=query),
            AIMessage(content=answer, additional_kwargs={"pages": pages, "chunks": chunks})
        ])
        
        return jsonify({"ok": True, "answer": answer, "pages": pages, "chunks": chunks})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

class API:
    def pick_file(self):
        if not webview.windows: return None
        window = webview.windows[0] # รับประกันว่าชี้ไปที่หน้าต่างหลักแน่นอน
        file_types = ('Support Documents (*.pdf;*.txt;*.docx)', 'All files (*.*)')
        result = window.create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        return result[0] if result else None
    
    def save_chat(self, session_id):
        if session_id not in sessions: return False
        history = sessions[session_id]["chat_history"]
        filename_str = ", ".join(sessions[session_id]["filename"])
        
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
            # ดึง string ออกมาจาก tuple อย่างปลอดภัย
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
    webview.start() # เอา debug ออกเพื่อให้แอปทำงานสมูทที่สุด