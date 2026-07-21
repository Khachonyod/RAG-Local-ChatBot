# app.py
import os
import sys
import uuid
import threading
import webview
import json as json_lib
from html import escape as html_escape
from flask import Flask, request, jsonify, render_template, Response
from langchain_core.messages import HumanMessage, AIMessage, messages_from_dict, messages_to_dict
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

from core.document import load_single_file
from core.rag_engine import RAGEngine
from core.text_utils import thai_tokenize
from core.config import TESSERACT_CMD, POPPLER_PATH, SESSION_FILE, PERSIST_DIR, EMBEDDING_MODEL

app = Flask(__name__, template_folder='templates', static_folder='static')
sessions = {}

# เรียกใช้อินสแตนซ์ของ RAG Engine
rag = RAGEngine(persist_dir=PERSIST_DIR, embedding_model=EMBEDDING_MODEL)

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ลงทะเบียนฟอนต์ไทย (Sarabun) สำหรับ export PDF — ฟอนต์เริ่มต้นของ reportlab ไม่มีตัวอักษรไทย
# ถ้าไม่ลงทะเบียนฟอนต์นี้ ข้อความไทยใน PDF จะกลายเป็นกล่องสี่เหลี่ยมว่าง (.notdef glyph) ทั้งหมด
FONT_REGULAR, FONT_BOLD = "Sarabun", "Sarabun-Bold"
try:
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, get_resource_path("fonts/Sarabun-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, get_resource_path("fonts/Sarabun-Bold.ttf")))
except Exception as e:
    print(f"[WARNING] โหลดฟอนต์ไทยสำหรับ PDF ไม่สำเร็จ ({e}) — ตัวอักษรไทยใน PDF export อาจแสดงผลผิดพลาด")

def get_page_number(metadata):
    page = metadata.get("page")
    return int(page) + 1 if page is not None else 1

# ==================== SESSION MANAGEMENT ====================
def save_sessions():
    data_to_save = {
        sid: {"filenames": sdata["filenames"], "chat_history": messages_to_dict(sdata["chat_history"])}
        for sid, sdata in sessions.items() if sdata["status"] == "ready"
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json_lib.dump(data_to_save, f, ensure_ascii=False, indent=4)

def load_sessions():
    if not os.path.exists(SESSION_FILE): return
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json_lib.load(f)
            for sid, sdata in data.items():
                vector_db = rag.get_vector_db(sid)
                
                # ชุบชีวิตดัชนีคำ BM25 และดึงโครงสร้างย่อยของเอกสารกลับคืนมาจาก Chroma DB
                try:
                    ch_data = vector_db.get()
                    splits = [
                        Document(page_content=doc, metadata=meta)
                        for doc, meta in zip(ch_data['documents'], ch_data['metadatas'])
                    ]
                    tokenized_corpus = [thai_tokenize(d.page_content) for d in splits]
                    bm25 = BM25Okapi(tokenized_corpus) if tokenized_corpus else None
                except Exception as e:
                    print(f"ไม่สามารถดึงข้อมูล Chroma สำหรับ Session {sid}: {e}")
                    splits = []
                    bm25 = None

                sessions[sid] = {
                    "status": "ready",
                    "filenames": sdata["filenames"],
                    "chat_history": messages_from_dict(sdata["chat_history"]),
                    "vector_db": vector_db,
                    "bm25": bm25,
                    "splits": splits
                }
    except Exception as e:
        print(f"ไม่สามารถโหลดประวัติเดิมได้: {e}")

# ==================== BACKGROUND TASK ====================
def build_rag_task(file_paths: list, session_id: str, is_append: bool):
    sessions[session_id]["status"] = "loading"
    try:
        all_docs = []
        for file_path in file_paths:
            try:
                docs = load_single_file(file_path, POPPLER_PATH, TESSERACT_CMD)
                if docs: all_docs.extend(docs)
            except Exception as e:
                print(f"ข้ามไฟล์ {file_path} เนื่องจาก Error: {e}")

        if not all_docs:
            if not is_append: raise ValueError("ไม่สามารถอ่านเนื้อหาจากไฟล์ใดๆ ได้เลย")
            sessions[session_id]["status"] = "ready"
            return

        # 1. บันทึกลงฐานข้อมูล Vector เสมอ
        vector_db, _ = rag.build_or_append_db(session_id, all_docs, is_append=is_append)
        
        # 2. ดึงข้อมูล Chunk ทั้งหมด (รวมของเก่า + ของใหม่) จากฐานข้อมูลมาทำดัชนี BM25
        ch_data = vector_db.get()
        all_splits = [
            Document(page_content=doc, metadata=meta)
            for doc, meta in zip(ch_data['documents'], ch_data['metadatas'])
        ]
        
        tokenized_corpus = [thai_tokenize(doc.page_content) for doc in all_splits]
        bm25 = BM25Okapi(tokenized_corpus)

        # 3. อัปเดตคีย์โครงสร้างใหม่ลงใน Session ให้ครบถ้วนและสอดคล้องกับ api_ask
        sessions[session_id].update({
            "vector_db": vector_db,
            "bm25": bm25,
            "splits": all_splits,
            "status": "ready"
        })
        save_sessions()
    except Exception as e:
        sessions[session_id]["status"] = f"error: {str(e)}"

# ==================== FLASK ROUTES ====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def api_delete_sessions(session_id):
    if session_id not in sessions: return jsonify({"ok": False,"error": "ไม่พบ Session"}), 404
    try:
        rag.get_vector_db(session_id).delete_collection()
    except Exception as e:
        print(f"Warning: ไม่พบข้อมูล collection - {e}")
    if session_id in sessions:
        del sessions[session_id]
    save_sessions()
    return jsonify({"ok": True})

@app.route("/api/load", methods=["POST"])
def api_load():
    data = request.get_json()
    paths, session_id = data.get("paths", []), data.get("session_id")
    supported_ext = ['.pdf', '.doc', '.docx', '.txt', '.xls', '.xlsx']
    
    files_to_process = [f for f in paths if os.path.exists(f) and os.path.splitext(f)[1].lower() in supported_ext]
    if not files_to_process: return jsonify({"ok": False, "error": "ไม่พบไฟล์เอกสารที่รองรับ"}), 400

    is_append = False
    if session_id and session_id in sessions:
        is_append = True
        files_to_process = [f for f in files_to_process if os.path.basename(f) not in sessions[session_id]["filenames"]]
        if not files_to_process: return jsonify({"ok": False, "error": "ไฟล์ถูกเพิ่มไปแล้ว"}), 400
        sessions[session_id]["filenames"].extend([os.path.basename(f) for f in files_to_process])
    else:
        session_id = uuid.uuid4().hex
        sessions[session_id] = {
            "status": "idle", "filenames": [os.path.basename(f) for f in files_to_process],
            "chat_history": [], "vector_db": None, "bm25": None, "splits": None
        }

    threading.Thread(target=build_rag_task, args=(files_to_process, session_id, is_append), daemon=True).start()
    return jsonify({"ok": True, "session_id": session_id, "filenames": sessions[session_id]["filenames"]})

@app.route("/api/sessions", methods=["GET"])
def api_sessions():
    return jsonify({"ok": True, "sessions": [{"id": sid, "filenames": d["filenames"]} for sid, d in sessions.items()]})

@app.route("/api/history/<session_id>", methods=["GET"])
def api_history(session_id):
    if session_id not in sessions: return jsonify({"ok": False, "error": "ไม่พบ Session"}), 404
    sdata = sessions[session_id]
    history = [{"role": "user" if m.type == "human" else "ai", "content": m.content, 
                "pages": m.additional_kwargs.get("pages", []), "chunks": m.additional_kwargs.get("chunks", []),
                "query_terms": m.additional_kwargs.get("query_terms", [])} 
               for m in sdata["chat_history"]]
    return jsonify({"ok": True, "history": history, "filenames": sdata["filenames"], "status": sdata["status"]})

@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json()
    session_id, query, model_name = data.get("session_id"), data.get("query"), data.get("model", "llama3")

    # ===== รับค่า Weight จาก Slider ของ frontend ===
    try:
        vec_weight = float(data.get("vec_weight", 0.7))
    except (TypeError, ValueError):
        vec_weight = 0.7
    vec_weight = max(0.0, min(1.0, vec_weight)) #กันค่าเพี้ยนนอกช่วง 0-1
    bm25_weight = 1.0 - vec_weight


    if session_id not in sessions: 
        return jsonify({"ok": False, "error": "ไม่พบ Session"}), 400
    if sessions[session_id]["status"] != "ready": 
        return jsonify({"ok": False, "error": "กรุณารอประมวลผล..."}), 400

    try:
        vector_db = sessions[session_id]["vector_db"]
        bm25 = sessions[session_id]["bm25"]
        splits = sessions[session_id]["splits"]

        if bm25 is None:
            return jsonify({"ok": False, "error": "ยังไม่มีดัชนีค้นหาสำหรับ Session นี้"}), 400

        # ===== ส่วน Retrieval เหมือนเดิมทุกอย่าง ทำให้เสร็จก่อน stream =====
        vec_result = vector_db.similarity_search_with_score(query, k=10)
        vec_scores_map = {}
        if vec_result:
            vec_distances = [res[1] for res in vec_result]
            max_d, min_d = max(vec_distances), min(vec_distances)
            for doc, dist in vec_result:
                norm_score = 1.0 if max_d == min_d else (max_d - dist) / (max_d - min_d)
                vec_scores_map[doc.page_content] = {"doc": doc, "score": norm_score}

        tokenized_query = thai_tokenize(query)
        bm25_all_scores = bm25.get_scores(tokenized_query)
        top_10_idx = sorted(range(len(bm25_all_scores)), key=lambda i: bm25_all_scores[i], reverse=True)[:10]
        bm25_scores_map = {}
        if top_10_idx:
            bm25_top_scores = [bm25_all_scores[i] for i in top_10_idx]
            max_b, min_b = max(bm25_top_scores), min(bm25_top_scores)
            for i in top_10_idx:
                raw_score = bm25_all_scores[i]
                norm_score = 1.0 if max_b == min_b else (raw_score - min_b) / (max_b - min_b)
                doc = splits[i]
                bm25_scores_map[doc.page_content] = {"doc": doc, "score": norm_score}

        w_vec, w_bm25 = vec_weight, bm25_weight
        
        hybrid_result = []
        all_contents = set(vec_scores_map.keys()).union(set(bm25_scores_map.keys()))
        for content in all_contents:
            v_data = vec_scores_map.get(content, {"score": 0.0, "doc": None})
            b_data = bm25_scores_map.get(content, {"score": 0.0, "doc": None})
            actual_doc = v_data["doc"] if v_data["doc"] else b_data["doc"]
            final_score = (w_vec * v_data["score"]) + (w_bm25 * b_data["score"])
            hybrid_result.append((actual_doc, final_score))
        hybrid_result.sort(key=lambda x: x[1], reverse=True)
        top_docs = hybrid_result[:6]

        context = "\n\n".join([
            f"[ข้อมูลจาก ไฟล์: {doc.metadata.get('filename', 'ไม่ระบุ')} หน้าที่: {get_page_number(doc.metadata)}]:\n{doc.page_content}" 
            for doc, score in top_docs
        ])
        pages = sorted(list(set(get_page_number(doc.metadata) for doc, score in top_docs)))
        chunks = [{
            "content": doc.page_content,
            "page": get_page_number(doc.metadata),
            "filename": doc.metadata.get("filename", "ไม่ระบุ"),
            "score": f"{round(score * 100, 2)}%"
            } for doc, score in top_docs]

        # ===== dynamic_chain ตามข้อ 1 ที่แก้ไปแล้ว =====
        dynamic_chain = rag.get_chain(model_name)
        chat_history_snapshot = sessions[session_id]["chat_history"]

        def generate():
            full_answer = ""
            try:
                # .stream() คืน generator ของ token ทีละชิ้น ต่างจาก .invoke() ที่รอครบก่อน
                for token in dynamic_chain.stream({
                    "context": context, 
                    "question": query, 
                    "chat_history": chat_history_snapshot
                }):
                    full_answer += token
                    # SSE format: ต้องขึ้นต้นด้วย "data: " และปิดท้ายด้วย \n\n เสมอ
                    payload = json_lib.dumps({"token": token}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"

                # stream จบแล้ว ค่อยบันทึก history (ต้องรอให้ full_answer ครบก่อน)
                sessions[session_id]["chat_history"].extend([
                    HumanMessage(content=query),
                    AIMessage(content=full_answer, additional_kwargs={"pages": pages, "chunks": chunks, "query_terms": tokenized_query})
                ])
                save_sessions()

                # ส่ง event สุดท้ายพร้อม pages/chunks/query_terms ให้ frontend เอาไปแสดงผล (ใช้ query_terms ไฮไลต์ในเนื้อหา source chunk)
                final_payload = json_lib.dumps({"done": True, "pages": pages, "chunks": chunks, "query_terms": tokenized_query}, ensure_ascii=False)
                yield f"data: {final_payload}\n\n"

            except Exception as e:
                error_payload = json_lib.dumps({"error": str(e)}, ensure_ascii=False)
                yield f"data: {error_payload}\n\n"

        return Response(generate(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"  # กัน proxy บาง config buffer ทั้งก้อนไว้ก่อนส่ง
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ==================== PYWEBVIEW API ====================
class API:
    def pick_file(self):
        if not webview.windows: return None
        return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True) if (window := webview.windows[0]) else None

    def save_chat(self, session_id):
        if session_id not in sessions or not webview.windows: return False
        history = sessions[session_id]["chat_history"]
        filenames = ', '.join(sessions[session_id]['filenames'])

        save_path = webview.windows[0].create_file_dialog(webview.FileDialog.SAVE, save_filename="Chat_Summary.pdf")
        if not save_path:
            return False
        actual_path = save_path[0] if isinstance(save_path, (list, tuple)) else save_path

        styles = getSampleStyleSheet()
        # wordWrap="CJK" จำเป็นมากสำหรับภาษาไทย เพราะไม่มีช่องว่างระหว่างคำ
        # ถ้าไม่ใส่ reportlab จะไม่ตัดบรรทัด ทำให้ข้อความยาว ๆ ล้นขอบกระดาษ
        body_style = ParagraphStyle("ThaiBody", parent=styles["Normal"], fontName=FONT_REGULAR, fontSize=11, leading=16, wordWrap="CJK")
        title_style = ParagraphStyle("ThaiTitle", parent=styles["Title"], fontName=FONT_BOLD, fontSize=18, textColor=colors.HexColor("#1E2761"), wordWrap="CJK")
        user_role_style = ParagraphStyle("ThaiUserRole", parent=body_style, fontName=FONT_BOLD, fontSize=12, textColor=colors.HexColor("#0d6efd"), spaceBefore=8)
        ai_role_style = ParagraphStyle("ThaiAiRole", parent=body_style, fontName=FONT_BOLD, fontSize=12, textColor=colors.HexColor("#334155"), spaceBefore=8)
        cite_style = ParagraphStyle("ThaiCite", parent=body_style, fontSize=9.5, textColor=colors.HexColor("#6B7280"), leftIndent=12)

        doc = SimpleDocTemplate(actual_path, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm)
        story = [
            Paragraph("สรุปการสนทนา", title_style),
            Paragraph(f"เอกสารอ้างอิง: {html_escape(filenames)}", body_style),
            Spacer(1, 0.4*cm),
            HRFlowable(width="100%", color=colors.HexColor("#CADCFC")),
            Spacer(1, 0.3*cm),
        ]

        for msg in history:
            is_user = msg.type == "human"
            story.append(Paragraph("ผู้ใช้ (User)" if is_user else "ผู้ช่วย AI (Assistant)", user_role_style if is_user else ai_role_style))
            story.append(Paragraph(html_escape(msg.content).replace("\n", "<br/>"), body_style))

            if not is_user:
                pages = msg.additional_kwargs.get("pages")
                if pages:
                    story.append(Spacer(1, 0.1*cm))
                    story.append(Paragraph(f"อ้างอิงจากหน้า: {', '.join(map(str, pages))}", cite_style))
                for c in msg.additional_kwargs.get("chunks", []):
                    header = f"{html_escape(str(c.get('filename', '')))} (หน้า {c.get('page', '')}, distance {c.get('score', '')})"
                    body = html_escape(str(c.get('content', ''))).replace("\n", "<br/>")
                    story.append(Spacer(1, 0.1*cm))
                    story.append(Paragraph(f"<b>{header}</b><br/>{body}", cite_style))

            story.append(Spacer(1, 0.25*cm))
            story.append(HRFlowable(width="100%", color=colors.HexColor("#E2E8F0")))
            story.append(Spacer(1, 0.25*cm))

        doc.build(story)
        return True

if __name__ == "__main__":
    load_sessions()
    app.template_folder = get_resource_path('templates')
    app.static_folder = get_resource_path('static')
    api = API()
    threading.Thread(target=lambda: app.run(port=5050), daemon=True).start()
    webview.create_window("Local RAG Assistant", "http://127.0.0.1:5050", js_api=api, width=1200, height=800)
    webview.start()