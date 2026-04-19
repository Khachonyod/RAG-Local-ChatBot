from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaLLM
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate

# 1. Load ข้อมูลจาก PDF
loader = PyPDFLoader("sample.pdf")
data = loader.load()

# 2. Split ข้อความออกเป็นส่วนย่อย
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
chunks = text_splitter.split_documents(data)

# 3. สร้าง Vector Database ด้วย Embedding ที่เก่งภาษาไทยขึ้น
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
vector_db = Chroma.from_documents(documents=chunks, embedding=embeddings, persist_directory="./chroma_db")

# 4. สร้าง Prompt Template เพื่อบังคับ AI
prompt_template = """
คุณคือผู้ช่วย AI ที่เชี่ยวชาญในการอ่านและสรุปเอกสาร จงใช้ข้อมูล(Context)ที่ให้มาเพื่อตอบคำถามอย่างละเอียด 
หากข้อมูลไม่มีคำตอบ ให้ตอบว่า "ไม่พบข้อมูลในเอกสาร" ห้ามแต่งเรื่องขึ้นมาเองเด็ดขาด
จงตอบเป็นภาษาไทยเท่านั้น

ข้อมูล (Context): {context}

คำถาม (Question): {question}

คำตอบ:"""
PROMPT = PromptTemplate(template=prompt_template, input_variables=["context", "question"])

# 5. ตั้งค่า Retrieval QA Chain
llm = OllamaLLM(model="llama3")
rag_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=vector_db.as_retriever(search_kwargs={"k": 5}),
    chain_type_kwargs={"prompt": PROMPT},
    return_source_documents=True
)

# 6. เริ่มถามคำถาม
query = "หน่วยกิตรวมตลอดหลักสูตรคือกี่หน่วยกิต"
response = rag_chain.invoke(query)

print("\n--- คำตอบของ AI ---")
print(response["result"])

# print("\n--- ข้อมูลจาก PDF ที่ AI ดึงมาอ่าน (Debug) ---")
# for i, doc in enumerate(response["source_documents"]):
#     print(f"ส่วนที่ {i+1}: {doc.page_content[:200]}...")