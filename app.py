import streamlit as st
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain.vectorstores.elasticsearch import ElasticsearchStore
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.prompts import PromptTemplate
from vector_embedding import VectorEmbedding
from elasticsearch import Elasticsearch

# --- Streamlit UI setup
st.set_page_config(page_title="PDF Chatbot")
st.title("🤖 PDFPal: Your AI-Powered Document Chat")

# --- Initialize memory and chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- Load LLM and Embeddings
llm = OllamaLLM(model="llama3.2:latest", temperature=0.7)
embedding = OllamaEmbeddings(model="mxbai-embed-large")

# --- Elasticsearch setup
es_client = Elasticsearch("http://localhost:9200")
index_name = "pdf_chatbot_index"

vector_store = ElasticsearchStore(
    es_connection=es_client,
    index_name=index_name,
    embedding=embedding,
)

retriever = vector_store.as_retriever(search_kwargs={"k": 3})

# --- Prompt template
QA_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""
    You are a helpful assistant. Use the following context to answer the question.
    If you don't know the answer, say "I'm not sure based on the provided content."

    Context:
    {context}

    Question:
    {question}

    Answer:"""
)

# --- Set up memory
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    output_key="answer"  # <== THIS IS THE CRUCIAL FIX
)

# --- QA chain with output_key explicitly set
qa_chain = ConversationalRetrievalChain.from_llm(
    llm=llm,
    retriever=retriever,
    memory=memory,
    return_source_documents=True,
    combine_docs_chain_kwargs={"prompt": QA_PROMPT},
    output_key="answer",  # <== THIS IS THE CRUCIAL FIX
)

# --- Upload PDF and index
uploaded_file = st.file_uploader("Upload a PDF", type="pdf")
if uploaded_file is not None:
    ve = VectorEmbedding()
    with st.spinner("Processing and indexing PDF..."):
        ve.process_pdf(uploaded_file)
    st.success("PDF processed and indexed!")

# --- User question input
question = st.text_input("Ask a question about your PDF:")

if question:
    try:
        response = qa_chain.invoke({"question": question})
        answer = response["answer"]

        st.markdown(f"**Answer:** {answer}")

        # Optional: Show sources
        with st.expander("Sources"):
            for i, doc in enumerate(response["source_documents"]):
                st.markdown(f"**Source {i + 1}:** {doc.page_content}")

        st.session_state.chat_history.append((question, answer))

    except Exception as e:
        st.error(f"Error: {str(e)}")
