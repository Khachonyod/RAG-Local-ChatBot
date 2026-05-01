from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel

# 1. Load ข้อมูลจาก PDF
loader = PyPDFLoader("sample.pdf")
docs = loader.load()

# 2. Split ข้อความออกเป็นส่วนย่อย
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
splits = text_splitter.split_documents(docs)

# 3. สร้าง Vector Database
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
vector_db = Chroma.from_documents(
    documents=splits,
    embedding=embeddings,
    persist_directory="./chroma_db"
)

# 4. กำหนดตัวโมเดล
llm = ChatOllama(model="llama3", temperature=0)

# 5. สร้าง Prompt
system_prompt = (
    "คุณคือผู้ช่วย AI ที่เชี่ยวชาญในการอ่านและสรุปเอกสาร "
    "จงใช้ข้อมูล (Context) ที่ให้มาเพื่อตอบคำถามอย่างละเอียด "
    "หากข้อมูลไม่มีคำตอบ ให้ตอบว่า 'ไม่พบข้อมูลในเอกสาร' ห้ามแต่งเรื่องขึ้นมาเองเด็ดขาด "
    "จงตอบเป็นภาษาไทยเท่านั้น"
    "\n\n"
    "{context}"
)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
])

# 6. Helper function แปลง docs → string สำหรับใส่ใน Prompt
def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

# 7. สร้าง LCEL Chain แบบ LangChain 1.x
retriever = vector_db.as_retriever(search_kwargs={"k": 5})

# ขั้นที่ 1: ดึง context docs และ input มาพร้อมกัน
rag_chain = RunnableParallel(
    context=retriever,
    input=RunnablePassthrough()
).assign(
    # ขั้นที่ 2: นำ context + input เข้า prompt → llm → parse output
    answer=lambda x: (
        prompt | llm | StrOutputParser()
    ).invoke({
        "context": format_docs(x["context"]),
        "input": x["input"]
    })
)

# 8. ถามคำถาม
query = "จำนวนหน่วยกิตรวมตลอดหลักสูตรคือกี่หน่วยกิต"
response = rag_chain.invoke(query)

print("\n--- คำตอบของ AI ---")
print(response["answer"])

print("\n--- ข้อมูลอ้างอิง (Source) ---")
for doc in response["context"]:
    print(f"- หน้าที่ {doc.metadata.get('page', 'N/A')}")