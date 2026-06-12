# core/rag_engine.py
import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

class RAGEngine:
    def __init__(self, persist_dir: str, embedding_model: str):
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)

    def get_vector_db(self, session_id: str) -> Chroma:
        """ดึงหรือสร้างอินสแตนซ์ของ Chroma สำหรับแต่ละเซสชัน"""
        return Chroma(
            collection_name=f"temp_{session_id}",
            embedding_function=self.embeddings,
            persist_directory=self.persist_dir
        )

    def get_prompt_template(self) -> ChatPromptTemplate:
        """กำหนดโครงสร้างของ Prompt สำหรับระบบ"""
        return ChatPromptTemplate.from_messages([
            ("system", "คุณคือผู้ช่วย AI จงตอบคำถามจากข้อมูลที่ให้มาเป็นภาษาไทยเท่านั้น\n"
                       "ข้อมูลด้านล่างนี้อาจมาจากเอกสารหลายชุด ให้สังเกตป้ายระบุ [ไฟล์: ...] อย่างละเอียด "
                       "หากผู้ใช้สั่งให้เปรียบเทียบ สรุปข้อเหมือน หรือข้อต่าง ให้ระบุข้อมูลแจกแจงแยกตามรายชื่อไฟล์อย่างชัดเจน\n\nContext: {context}"),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}")
        ])

    def build_or_append_db(self, session_id: str, documents: list, is_append: bool = False) -> Chroma:
        """ทำการ Chunk และบันทึกลงฐานข้อมูล Vector"""
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        splits = splitter.split_documents(documents)
        
        if is_append:
            vector_db = self.get_vector_db(session_id)
            vector_db.add_documents(splits)
        else:
            vector_db = Chroma.from_documents(
                documents=splits, 
                embedding=self.embeddings,
                collection_name=f"temp_{session_id}", 
                persist_directory=self.persist_dir
            )
        return vector_db

    def get_chain(self, model_name: str = "llama3"):
        """คอมโพส Chain ตามโมเดลที่ผู้ใช้ระบุ"""
        llm = ChatOllama(model=model_name, temperature=0)
        return self.get_prompt_template() | llm | StrOutputParser()